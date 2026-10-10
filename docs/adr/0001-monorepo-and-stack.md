# ADR-0001: Monorepo and default stack

**Status:** accepted · 2026-10-10

**Decision.** One repository with `services/common` (shared core), `services/api` (FastAPI), `services/worker` (Celery + CLI), `adapters/project315`, `wordpress/trial-knowledge`, `db/migrations` (SQL-first, run by Alembic), `contracts` (JSON Schema 2020-12 + OpenAPI). Python 3.12, Pydantic v2, SQLAlchemy 2 (Core), Alembic, Celery/Redis, PostgreSQL 16 + pgvector + pg_trgm, boto3, pytest; PHP ≥ 8.1 and `@wordpress/scripts` for the plugin — exactly the brief's defaults.

**Why SQLAlchemy Core, not ORM models.** The spec defines the schema in SQL (enums, `tstzrange`, exclusion constraints, `halfvec`). Core with explicit SQL keeps the database the single source of truth and avoids a second, drifting model definition. Alembic revisions execute the reviewed SQL files.

**Consequences.** One Docker image (`Dockerfile.base`) serves API, worker and beat with different start commands.
