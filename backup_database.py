from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys


PROJECT_FOLDER = Path(__file__).resolve().parent
SOURCE_DATABASE = (
    PROJECT_FOLDER
    / "data"
    / "timeoutcrm.db"
)


def backup_database(destination_folder: Path):
    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            f"Database not found: {SOURCE_DATABASE}"
        )

    if not destination_folder.parent.exists():
        raise FileNotFoundError(
            "The external backup drive is not connected."
        )

    destination_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    destination = destination_folder / (
        f"timeoutcrm_{timestamp}.db"
    )

    with sqlite3.connect(
        SOURCE_DATABASE
    ) as source:

        with sqlite3.connect(
            destination
        ) as backup:

            source.backup(backup)

            result = backup.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if not result or result[0] != "ok":
                raise RuntimeError(
                    "Backup database failed its integrity check."
                )

    print(
        f"Backup completed successfully: {destination}"
    )


if __name__ == "__main__":

    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: backup_database.py "
            "\"DESTINATION_FOLDER\""
        )

    backup_database(
        Path(sys.argv[1])
    )