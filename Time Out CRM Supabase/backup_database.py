"""
Export every Time Out Lawncare CRM PostgreSQL table to a ZIP of CSV files.

Run from the project directory:

    python backup_database.py "C:\\CRM Backups"
"""

from __future__ import annotations

import csv
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
from psycopg import sql


PROJECT_FOLDER = Path(__file__).resolve().parent
SECRETS_FILE = (
    PROJECT_FOLDER
    / ".streamlit"
    / "secrets.toml"
)


def postgres_settings() -> dict:
    if not SECRETS_FILE.exists():
        raise FileNotFoundError(
            f"Secrets file not found: {SECRETS_FILE}"
        )

    with SECRETS_FILE.open("rb") as file:
        secrets = tomllib.load(file)

    settings = secrets.get("postgres")

    if not isinstance(settings, dict):
        raise RuntimeError(
            "The secrets file has no [postgres] section."
        )

    return settings


def backup_database(destination_folder: Path) -> Path:
    destination_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )
    destination = destination_folder / (
        f"timeoutcrm_postgres_{timestamp}.zip"
    )
    settings = postgres_settings()

    with psycopg.connect(
        host=str(settings["host"]),
        port=int(settings.get("port", 5432)),
        dbname=str(settings.get("dbname", "postgres")),
        user=str(settings["user"]),
        password=str(settings["password"]),
        sslmode=str(settings.get("sslmode", "require")),
        connect_timeout=30,
    ) as connection:

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
            tables = [
                row[0]
                for row in cursor.fetchall()
            ]

        with tempfile.TemporaryDirectory() as temp_folder:
            temp_path = Path(temp_folder)

            with ZipFile(
                destination,
                "w",
                compression=ZIP_DEFLATED,
            ) as archive:

                for table in tables:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                "SELECT * FROM {}"
                            ).format(
                                sql.Identifier(table)
                            )
                        )
                        rows = cursor.fetchall()
                        columns = [
                            column.name
                            for column in cursor.description
                        ]

                    csv_path = temp_path / f"{table}.csv"

                    with csv_path.open(
                        "w",
                        newline="",
                        encoding="utf-8-sig",
                    ) as csv_file:
                        writer = csv.writer(csv_file)
                        writer.writerow(columns)
                        writer.writerows(rows)

                    archive.write(
                        csv_path,
                        arcname=csv_path.name,
                    )

    print(
        f"Backup completed successfully: {destination}"
    )

    return destination


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: backup_database.py "
            "\"DESTINATION_FOLDER\""
        )

    backup_database(Path(sys.argv[1]))
