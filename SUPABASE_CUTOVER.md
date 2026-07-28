# Time Out Lawncare CRM — Supabase Cutover

The CRM must remain shut down until the migration and deployment verification
are complete.

## 1. Preserve the final SQLite backup

Keep `timeoutcrm_2026-07-27_05-37-31.db` unchanged in a safe location. Do not
rename or overwrite your only copy.

## 2. Update the local project

Extract the converted project into a new folder. Do not overwrite the existing
working project until the Supabase migration has been verified.

Create:

```text
.streamlit/secrets.toml
```

Copy the current Streamlit Cloud secrets into that local file. It must include
the new PostgreSQL settings:

```toml
[postgres]
host = "YOUR_SESSION_POOLER_HOST"
port = 5432
dbname = "postgres"
user = "postgres.YOUR_PROJECT_REFERENCE"
password = "YOUR_CURRENT_DATABASE_PASSWORD"
sslmode = "require"
```

The secrets file is excluded by `.gitignore`. Never upload or commit it.

## 3. Install dependencies

From Command Prompt in the converted project folder:

```bat
python -m pip install -r requirements.txt
```

## 4. Run the one-time migration

Use the full path to the final SQLite backup:

```bat
python migrate_to_supabase.py --sqlite "C:\FULL\PATH\timeoutcrm_2026-07-27_05-37-31.db"
```

The migration:

- validates SQLite integrity and foreign keys;
- creates all 29 PostgreSQL tables;
- copies records in foreign-key-safe order;
- preserves primary-key values;
- resets PostgreSQL identity sequences;
- compares every table's SQLite and PostgreSQL record counts; and
- rolls back if verification fails.

Do not use `--allow-nonempty` unless specifically troubleshooting a previously
interrupted migration.

The successful verification must include:

```text
customers                       SQLite=45      PostgreSQL=45      OK
imported_applications           SQLite=153     PostgreSQL=153     OK
imported_application_chemicals SQLite=463     PostgreSQL=463     OK
```

Every listed table must end with `OK`.

## 5. Test locally

Start the converted app:

```bat
python -m streamlit run app.py
```

Verify:

1. Google login succeeds.
2. The dashboard shows 45 customers.
3. Customer records open and can be edited.
4. The imported application history is present.
5. Treatment and invoice records load.
6. A temporary test customer can be added, edited, and deleted.
7. Restart Streamlit and confirm the same records remain.

## 6. Deploy

Commit only the sanitized converted source files. Confirm that none of these
are staged:

```text
.streamlit/secrets.toml
*.db
venv/
.venv/
__pycache__/
*.xlsx
```

Deploy the converted project to Streamlit Community Cloud. The existing
Streamlit Cloud Secrets must contain the current `[auth]`, `USER_ROLES`,
`GOOGLE_API_KEY`, and `[postgres]` entries.

## 7. Production verification

After deployment:

1. Sign in with an authorized account.
2. Confirm the dashboard shows 45 customers.
3. Add a clearly identified test note or test customer.
4. Reboot the Streamlit app from **Manage app**.
5. Sign in again and confirm the test record remains.
6. Remove the test record.
7. Test geocoding and route creation with the rotated Google API key.

Do not delete the final SQLite backup after cutover.
