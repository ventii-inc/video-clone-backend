# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Run development server with hot reload
python main.py
# or
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Install dependencies
uv sync

# Add a new dependency
uv add <package-name>
```

## Environment Configuration

The app loads environment variables from `.env.{ENV}` files based on the `ENV` variable:
- `.env.local` - Local development
- `.env.staging` - Staging environment
- `.env.production` - Production environment

Set `ENV=local` (default) to use `.env.local`.

Required environment variables:
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` - PostgreSQL connection

## Architecture

**Stack:** FastAPI + SQLAlchemy 2.0 + PostgreSQL

**Structure:**
```
main.py              # App entry point, loads env files before imports
app/
  config.py          # Pydantic Settings for typed configuration
  db/
    database.py      # SQLAlchemy engine, session factory, Base
    __init__.py      # Exports: get_db, get_db_session, engine, SessionLocal, Base
  models/
    __init__.py      # Import models here, exports Base
```

**Database Session Patterns:**
- `get_db()` - FastAPI dependency for route injection (use with `Depends(get_db)`)
- `get_db_session()` - Context manager for standalone operations (auto-commits on success, rolls back on error)

**Adding New Models:**
1. Create model file in `app/models/`
2. Import the model in `app/models/__init__.py` to register with Base
3. Models inherit from `Base` imported from `app.db`
