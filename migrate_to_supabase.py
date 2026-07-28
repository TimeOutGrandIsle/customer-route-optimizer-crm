"""
One-time migration of the Time Out Lawncare CRM SQLite database to Supabase.

The script reads PostgreSQL connection settings from the [postgres] section of
.streamlit/secrets.toml. It creates an equivalent PostgreSQL schema, copies all
rows while preserving primary keys, resets identity sequences, and verifies
the record count of every table.

Run from the project directory:

    python migrate_to_supabase.py --sqlite data/timeoutcrm.db
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import tomllib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "timeoutcrm.db"
DEFAULT_SECRETS_PATH = PROJECT_ROOT / ".streamlit" / "secrets.toml"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Time Out Lawncare CRM from SQLite to Supabase."
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help="Path to the source SQLite database.",
    )
    parser.add_argument(
        "--secrets",
        type=Path,
        default=DEFAULT_SECRETS_PATH,
        help="Path to the local Streamlit secrets.toml file.",
    )
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="Allow migration into PostgreSQL tables that already contain rows.",
    )
    return parser.parse_args()


def load_postgres_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Streamlit secrets file not found: {path}\n"
            "Create it locally and add the same [postgres] settings used by "
            "Streamlit Community Cloud."
        )

    with path.open("rb") as file:
        secrets = tomllib.load(file)

    settings = secrets.get("postgres")

    if not isinstance(settings, dict):
        raise KeyError(
            f"No [postgres] section was found in {path}."
        )

    required = ("host", "port", "dbname", "user", "password")
    missing = [
        key
        for key in required
        if settings.get(key) in (None, "")
    ]

    if missing:
        raise KeyError(
            "Missing PostgreSQL setting(s): "
            + ", ".join(missing)
        )

    return {
        "host": str(settings["host"]),
        "port": int(settings["port"]),
        "dbname": str(settings["dbname"]),
        "user": str(settings["user"]),
        "password": str(settings["password"]),
        "sslmode": str(settings.get("sslmode", "require")),
        "connect_timeout": 30,
    }


def quote_sqlite_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqlite_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()

    return [str(row[0]) for row in rows]


def sqlite_create_sql(
    connection: sqlite3.Connection,
    object_type: str,
) -> list[tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = ?
          AND name NOT LIKE 'sqlite_%'
          AND sql IS NOT NULL
        ORDER BY name
        """,
        (object_type,),
    ).fetchall()

    return [
        (str(row[0]), str(row[1]))
        for row in rows
    ]


def table_dependencies(
    connection: sqlite3.Connection,
    tables: list[str],
) -> dict[str, set[str]]:
    table_set = set(tables)
    dependencies: dict[str, set[str]] = defaultdict(set)

    for table in tables:
        rows = connection.execute(
            f"PRAGMA foreign_key_list({quote_sqlite_identifier(table)})"
        ).fetchall()

        for row in rows:
            referenced_table = str(row[2])

            if (
                referenced_table in table_set
                and referenced_table != table
            ):
                dependencies[table].add(referenced_table)

        dependencies.setdefault(table, set())

    return dependencies


def topological_table_order(
    dependencies: dict[str, set[str]],
) -> list[str]:
    remaining = {
        table: set(required)
        for table, required in dependencies.items()
    }
    reverse: dict[str, set[str]] = defaultdict(set)

    for table, required in remaining.items():
        for dependency in required:
            reverse[dependency].add(table)

    ready = deque(
        sorted(
            table
            for table, required in remaining.items()
            if not required
        )
    )
    ordered: list[str] = []

    while ready:
        table = ready.popleft()
        ordered.append(table)

        for dependent in sorted(reverse.get(table, ())):
            remaining[dependent].discard(table)

            if (
                not remaining[dependent]
                and dependent not in ordered
                and dependent not in ready
            ):
                ready.append(dependent)

    unresolved = sorted(
        table
        for table in remaining
        if table not in ordered
    )

    if unresolved:
        raise RuntimeError(
            "Circular or unresolved table dependencies: "
            + ", ".join(unresolved)
        )

    return ordered


def convert_table_ddl(sqlite_ddl: str) -> str:
    ddl = sqlite_ddl.strip().rstrip(";")

    ddl = re.sub(
        r"^\s*CREATE\s+TABLE\s+",
        "CREATE TABLE IF NOT EXISTS ",
        ddl,
        count=1,
        flags=re.IGNORECASE,
    )
    ddl = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        ddl,
        flags=re.IGNORECASE,
    )
    ddl = re.sub(
        r"\bREAL\b",
        "DOUBLE PRECISION",
        ddl,
        flags=re.IGNORECASE,
    )
    ddl = re.sub(
        r"\bTIMESTAMP\b",
        "TIMESTAMPTZ",
        ddl,
        flags=re.IGNORECASE,
    )

    return ddl


def convert_index_ddl(sqlite_ddl: str) -> str:
    ddl = sqlite_ddl.strip().rstrip(";")

    return re.sub(
        r"^\s*CREATE\s+(UNIQUE\s+)?INDEX\s+",
        lambda match: (
            "CREATE "
            + (match.group(1) or "")
            + "INDEX IF NOT EXISTS "
        ),
        ddl,
        count=1,
        flags=re.IGNORECASE,
    )


def destination_public_tables(
    connection: psycopg.Connection[Any],
) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )

        return [str(row[0]) for row in cursor.fetchall()]


def destination_counts(
    connection: psycopg.Connection[Any],
    tables: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(
                sql.SQL("SELECT COUNT(*) FROM {}").format(
                    sql.Identifier(table)
                )
            )
            counts[table] = int(cursor.fetchone()[0])

    return counts


def create_destination_schema(
    sqlite_connection: sqlite3.Connection,
    postgres_connection: psycopg.Connection[Any],
    ordered_tables: list[str],
) -> None:
    table_ddl = dict(
        sqlite_create_sql(sqlite_connection, "table")
    )

    with postgres_connection.cursor() as cursor:
        for table in ordered_tables:
            cursor.execute(convert_table_ddl(table_ddl[table]))

        for _, index_ddl in sqlite_create_sql(
            sqlite_connection,
            "index",
        ):
            cursor.execute(convert_index_ddl(index_ddl))


def table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> list[str]:
    rows = connection.execute(
        f"PRAGMA table_info({quote_sqlite_identifier(table)})"
    ).fetchall()

    return [str(row[1]) for row in rows]


def copy_table(
    sqlite_connection: sqlite3.Connection,
    postgres_connection: psycopg.Connection[Any],
    table: str,
) -> int:
    columns = table_columns(sqlite_connection, table)
    quoted_table = quote_sqlite_identifier(table)
    source_cursor = sqlite_connection.execute(
        f"SELECT * FROM {quoted_table}"
    )
    rows = source_cursor.fetchall()

    if not rows:
        return 0

    insert_statement = sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING"
    ).format(
        sql.Identifier(table),
        sql.SQL(", ").join(
            sql.Identifier(column)
            for column in columns
        ),
        sql.SQL(", ").join(
            sql.Placeholder()
            for _ in columns
        ),
    )

    with postgres_connection.cursor() as cursor:
        cursor.executemany(
            insert_statement,
            [
                tuple(row[column] for column in columns)
                for row in rows
            ],
        )

    return len(rows)


def reset_identity_sequence(
    connection: psycopg.Connection[Any],
    table: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, 'id')",
            (f"public.{table}",),
        )
        sequence = cursor.fetchone()[0]

        if sequence is None:
            return

        cursor.execute(
            sql.SQL(
                """
                SELECT setval(
                    {},
                    COALESCE((SELECT MAX(id) FROM {}), 1),
                    EXISTS(SELECT 1 FROM {})
                )
                """
            ).format(
                sql.Literal(sequence),
                sql.Identifier(table),
                sql.Identifier(table),
            )
        )


def source_counts(
    connection: sqlite3.Connection,
    tables: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for table in tables:
        row = connection.execute(
            f"SELECT COUNT(*) FROM {quote_sqlite_identifier(table)}"
        ).fetchone()
        counts[table] = int(row[0])

    return counts


def print_count_report(
    source: dict[str, int],
    destination: dict[str, int],
) -> bool:
    width = max(len(table) for table in source)
    all_match = True

    print("\nVerification")
    print("-" * (width + 31))

    for table in sorted(source):
        source_count = source[table]
        destination_count = destination.get(table, -1)
        matches = source_count == destination_count
        all_match = all_match and matches
        status = "OK" if matches else "MISMATCH"
        print(
            f"{table:<{width}}  "
            f"SQLite={source_count:<7} "
            f"PostgreSQL={destination_count:<7} "
            f"{status}"
        )

    return all_match


def migrate(args: argparse.Namespace) -> int:
    sqlite_path = args.sqlite.resolve()

    if not sqlite_path.exists():
        raise FileNotFoundError(
            f"SQLite database not found: {sqlite_path}"
        )

    postgres_settings = load_postgres_settings(
        args.secrets.resolve()
    )

    sqlite_connection = sqlite3.connect(sqlite_path)
    sqlite_connection.row_factory = sqlite3.Row

    try:
        integrity = sqlite_connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                f"SQLite integrity check failed: {integrity}"
            )

        foreign_key_violations = sqlite_connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if foreign_key_violations:
            raise RuntimeError(
                "SQLite foreign-key check found "
                f"{len(foreign_key_violations)} violation(s)."
            )

        tables = sqlite_tables(sqlite_connection)
        dependencies = table_dependencies(
            sqlite_connection,
            tables,
        )
        ordered_tables = topological_table_order(dependencies)
        expected_counts = source_counts(
            sqlite_connection,
            tables,
        )

        print(f"Source database: {sqlite_path}")
        print(f"Tables found: {len(tables)}")
        print("SQLite integrity and foreign-key checks passed.")

        with psycopg.connect(**postgres_settings) as postgres_connection:
            existing_tables = destination_public_tables(
                postgres_connection
            )

            if existing_tables and not args.allow_nonempty:
                existing_counts = destination_counts(
                    postgres_connection,
                    existing_tables,
                )
                populated = {
                    table: count
                    for table, count in existing_counts.items()
                    if count
                }

                if populated:
                    details = ", ".join(
                        f"{table}={count}"
                        for table, count in populated.items()
                    )
                    raise RuntimeError(
                        "The destination already contains data "
                        f"({details}). Migration stopped to prevent "
                        "duplicates. Use --allow-nonempty only after "
                        "reviewing the destination."
                    )

            create_destination_schema(
                sqlite_connection,
                postgres_connection,
                ordered_tables,
            )

            for table in ordered_tables:
                copied = copy_table(
                    sqlite_connection,
                    postgres_connection,
                    table,
                )

                if "id" in table_columns(
                    sqlite_connection,
                    table,
                ):
                    reset_identity_sequence(
                        postgres_connection,
                        table,
                    )

                print(f"Copied {table}: {copied} row(s)")

            migrated_counts = destination_counts(
                postgres_connection,
                tables,
            )

            if not print_count_report(
                expected_counts,
                migrated_counts,
            ):
                raise RuntimeError(
                    "Migration verification failed. "
                    "The PostgreSQL transaction was rolled back."
                )

            postgres_connection.commit()

        print("\nMigration completed successfully.")
        return 0

    finally:
        sqlite_connection.close()


def main() -> int:
    try:
        return migrate(parse_arguments())
    except Exception as error:
        print(f"\nMigration stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
