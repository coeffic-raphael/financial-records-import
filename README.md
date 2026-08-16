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

## AI provider

PDF content is extracted by a language model and converted into the same
normalized records a CSV produces.

**The choice of vendor is deliberately not load-bearing.** Reading fifteen
fields off a two-page invoice is not a discriminating task: both candidates read
PDFs natively and constrain their output to a JSON schema server-side, so
capability did not decide anything. What decided it is the path to production.

**Google Gemini** is the primary provider because the same SDK reaches Vertex
AI, where processing can be pinned to an EU region (`europe-west1`) under a data
residency commitment. For an application handling European bank statements that
is a regulatory requirement, and it costs a constructor argument rather than a
rewrite: the prototype and a sovereign deployment share the same connector,
schema, prompt and tests.

**OpenAI** is implemented as the second link of a fallback chain. When both keys
are present, a transient failure on the primary falls through. A permanent
failure — bad key, unknown model — is never retried, since retrying cannot help
and only delays the fallback.

**Mock** keeps the application fully usable with no credentials, and is what the
test suite runs against.

Switching primary provider is one environment variable. That is not an
aspiration: the mock satisfying the same interface is what 346 tests exercise.

### Configuration

```bash
EXTRACTION_PROVIDER=gemini      # gemini | openai | mock
GEMINI_API_KEY=...
OPENAI_API_KEY=...              # optional; enables the fallback chain
```

The full list is in [`backend/.env.example`](backend/.env.example). No provider
key may ever carry a `VITE_` prefix: those are compiled into the browser bundle.
Extraction is server-side only, and the frontend never learns which provider is
used.

A misconfigured provider **stops the application from starting** rather than
surfacing as an error on someone's first upload.

### What the model is told, and what it is not trusted with

The prompt states five constraints drawn from the supplied documents — most
importantly **never invent a value**: an absent field must come back as `null`
with confidence 0. On the bank statement it must take the per-line `Amount` and
never the running `Balance`, the two being adjacent numeric columns.

Nothing the model returns is trusted. The response is validated against a
structural schema **before anything reaches the database**, and every field is
optional in that schema: whether a field is required is a business rule, so it
belongs to the domain. An incomplete extraction therefore produces a
`NEEDS_REVIEW` record rather than a parse failure.

Confidence is reported per field, bounded to `[0, 1]`, and aggregated to the
**minimum** across required fields — a record is only as trustworthy as its
least certain required value.

### Processing

Uploading PDFs returns **202** immediately with one job per file; extraction
runs in the background and the client follows progress on
`GET /api/batches/{id}/jobs`.

Two limits are enforced rather than declared. Uploads are read in chunks and
refused the moment they exceed the size limit, so an oversized file never
becomes resident. Extraction concurrency is capped, because provider quotas are
counted in requests per minute — which also caps how many documents are in
memory at once, since each is read only once its turn comes.

## Requirements

- Python 3.11+

## Setup

Every command below is run from the `backend/` directory.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

No API key is required at this stage.

## Run

```bash
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

Interactive API documentation is generated at <http://localhost:8000/docs>.

## Tests

```bash
.venv/bin/pytest
```

The suite is **hermetic**: no network, no API key, no external service, and no
billable API call. Tests that talk to a real provider are excluded by default,
not merely marked — a mark enables selection, it does not deselect.

Run them deliberately, with a key configured:

```bash
.venv/bin/pytest -m live
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
- Invalid values are persisted and reported, never rejected: user-supplied
  columns are unbounded, and plausibility limits are business rules
- CSV ingestion — every row is imported, never the whole file rejected
- Batch and record API: create, list, filter, field-level errors, correct,
  revalidate, approve, batch summary
- Tenant scoping on every query, with cross-tenant access returning `404`
- Alembic migrations, applied by the test suite from an empty database (SQLite;
  PostgreSQL portability is claimed, not yet verified in CI)
- PDF extraction through Gemini, with an OpenAI fallback, per-field confidence,
  token accounting and background processing
- CI: lint, tests on three Python versions, migration drift, secret scanning

**Not yet**

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
- **EU data residency.** The public Gemini endpoint offers no region control.
  Production would use the same SDK against Vertex AI with `location` pinned to
  an EU region, which is a constructor argument rather than a redesign.
- **Unpaid provider tiers must not receive real documents.** Google's terms
  allow human review of content submitted through the unpaid service and
  explicitly warn against sending confidential information. The sample documents
  here are synthetic; real bank statements require the paid tier.
- **Concurrent imports into one batch.** Both the duplicate check and the
  arrival-order allocation read then write outside a lock, so two simultaneous
  imports into the same batch can miss a duplicate between them. Sequential
  imports are unaffected. Production would use an atomic counter or a unique
  constraint with retry.
- **TLS to a managed PostgreSQL**, rate limiting on authentication, and full
  security headers.

## Language

Everything in this repository is written in English: code, comments, tests,
configuration and documentation.
