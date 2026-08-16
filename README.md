# Financial Records Import

[![CI](https://github.com/coeffic-raphael/financial-records-import/actions/workflows/ci.yml/badge.svg)](https://github.com/coeffic-raphael/financial-records-import/actions/workflows/ci.yml)

Imports, extracts, validates, corrects and approves financial records from **CSV**
and **PDF** sources. CSV rows and AI-extracted PDF content converge on a single
normalized model.

> **Work in progress.** This README will be replaced by the full documentation
> once the application is feature-complete. See [Current state](#current-state).

---

## Architecture in one picture

Both sources share one pipeline. Only acquisition differs.

```
   CSV ─────────────┐
                    ├──▶ raw payload ──▶ normalization ──▶ validation ──▶ persistence
   PDF ──▶ AI ──────┘                         │                 │
                                         cleans FORM       judges SUBSTANCE
                                     (amounts, dates)     (business rules)
```

Two consequences this design is built for:

- **A business rule lives in exactly one place.** Changing one means editing one
  function, not two code paths.
- **Correcting a record replays the same pipeline as importing it.** A
  correction is merged into the stored raw payload and revalidated through the
  identical code, so the import path and the correction path cannot drift apart.

## Requirements

- Python 3.11+

## Setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

Copy the environment template and adjust if needed:

```bash
cp backend/.env.example backend/.env
```

No API key is required at this stage.

## Run

```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

Interactive API documentation is generated at <http://localhost:8000/docs>.

## Tests

```bash
cd backend
.venv/bin/pytest
```

The suite is **hermetic**: no network, no API key, no external service. Tests
that call a real AI provider are marked `live` and skipped automatically.

```bash
cd backend
.venv/bin/pytest -m "not live"
```

## Sample files

The files supplied with the assignment are committed under [`samples/`](samples/)
and are used directly by the test suite. Nothing needs to be placed manually.

`transactions_import.csv` is a test suite in disguise — one row per validation
rule. Importing it yields **18 `VALID`** and **12 `NEEDS_REVIEW`** records, and a
test asserts the exact set of error codes for every row.

## Current state

**Done**

- Common data model, normalization and validation engine
- CSV ingestion — every row is imported, never the whole file rejected
- Batch and record API: create, list, filter, field-level errors, correct,
  revalidate, approve, batch summary
- Tenant scoping on every query, with cross-tenant access returning `404`
- Alembic migrations, applied by the test suite from an empty database
- CI: lint, tests, secret scanning

**Not yet**

- PDF extraction through an AI provider
- Authentication
- Frontend
- Docker Compose

## Production improvements

Deliberately out of scope here, with the approach that would be taken:

- **Dependency locking.** Direct dependencies are pinned; transitive ones are
  not, so a clean install three weeks from now may resolve a different
  `starlette`. Production would use a full lockfile (`pip-tools`, `uv`, or a
  committed `pip freeze`), regenerated in CI.
- **Background job queue.** PDF extraction will run in-process; it does not
  survive a restart and does not spread across workers. Celery, RQ or Arq with
  Redis would replace it.
- **Reference uniqueness under concurrency.** Uniqueness is enforced in the
  application rather than the schema, because the assignment requires importing
  a duplicated row instead of rejecting the file. A partial unique index
  (`WHERE reference IS NOT NULL`) plus conflict handling that marks the losing
  row NEEDS_REVIEW would reconcile the constraint with that requirement.
- **TLS to a managed PostgreSQL**, rate limiting on authentication, and full
  security headers.

## Language

Everything in this repository is written in English: code, comments, tests,
configuration and documentation.
