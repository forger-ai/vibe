---
name: stack-database-extension
description: Use when building or updating apps from the vite-fastapi-sqlite skeleton that need database models, schema initialization, migrations, Docker Compose helper mounts, or scripts that depend on app.database. Preserve the stack pattern: commons owns the shared database helper; each app owns model registration and app-specific migrations through database_ext.
---

# Stack Database Extension

This skill is for the agent, not for the end user.

Use it when creating or updating a `vite-fastapi-sqlite` app that needs backend
database models, SQLite schema setup, migrations, Docker Compose helper mounts,
or internal scripts that initialize the database.

## Stack Contract

The shared stack database helper lives in:

```text
commons/backend/database.py
```

In Docker Compose, that helper is mounted over the app-local database helper.
For apps generated from this skeleton, the mounted target follows the backend
layout used by the app:

```text
/app/src/app/database.py
```

or, for apps that use a flat backend package:

```text
/app/app/database.py
```

That mount is intentional. Do not remove it as the normal fix for app-specific
schema behavior.

The shared helper owns:

- `DATABASE_URL` resolution;
- the shared SQLModel `engine`;
- SQLite foreign-key pragma setup;
- `get_session()`;
- generic `init_db()` based on `SQLModel.metadata.create_all()`.

Each app owns:

- SQLModel table declarations in its local models module;
- model registration before `init_db()` runs;
- app-specific migrations;
- startup sequencing;
- internal scripts that need app-specific database initialization.

## Required Pattern

When an app needs schema behavior beyond `create_all()`, keep the shared
`app.database` helper mounted from commons and add app-specific behavior in a
local extension module:

```text
backend/src/app/database_ext.py
```

For flat backend packages, use:

```text
backend/app/database_ext.py
```

The extension module registers models and exposes an app-level initializer:

```python
from app import models as _models  # noqa: F401
from app.database import init_db


def init_app_db() -> None:
    run_app_specific_migrations()
    init_db()
```

Application startup should import and call that app-level initializer:

```python
from app.database_ext import init_app_db


@app.on_event("startup")
def on_startup() -> None:
    init_app_db()
```

Internal scripts should call the same app-level initializer when they need a
ready app database:

```python
from app.database import engine
from app.database_ext import init_app_db as init_db
```

This keeps script behavior aligned with the running app.

## Migration Rules

Use the app-local `database_ext.py` for migrations that depend on app models,
tables, domain data, or data semantics.

Do not put app-specific migrations in `commons/backend/database.py`. Commons
must stay reusable across apps in the stack.

Do not remove the `commons/backend/database.py` bind mount from
`docker-compose.yml` just to make an app-specific migration run. If the mount
blocks the migration, the migration is in the wrong place for this stack
contract.

Use idempotent migrations:

- detect the current schema first;
- return immediately when the schema already matches;
- preserve existing user data;
- run data-moving changes inside transactions where SQLite permits it;
- call the shared `init_db()` after app-specific migration steps so any missing
tables are created from registered SQLModel metadata.

For SQLite table rebuild migrations:

- read legacy rows first;
- derive any new required fields from existing related tables when possible;
- drop or rename the legacy table only after data is captured;
- recreate the table through SQLModel metadata or explicit SQL;
- insert preserved rows with the new shape;
- verify the resulting columns and row count.

## Verification

After changing database initialization or migrations, verify the running app and
any internal scripts that depend on database setup.

Typical internal checks:

```bash
docker compose up -d --build backend
curl -sS -i http://localhost:8000/api/health
docker compose exec -T backend uv run python <script-that-calls-init-db>
```

When changing a migration, also test against a temporary legacy SQLite database
that reproduces the old schema. Confirm that:

- new columns exist;
- existing rows remain present;
- derived foreign keys are correct;
- startup remains idempotent when run twice.

These commands are internal agent tools. Do not present them as normal user
instructions unless the user explicitly asks for technical details.
