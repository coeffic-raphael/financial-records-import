# Financial Records Import

[![CI](https://github.com/coeffic-raphael/financial-records-import/actions/workflows/ci.yml/badge.svg)](https://github.com/coeffic-raphael/financial-records-import/actions/workflows/ci.yml)

Imports, extracts, validates, corrects and approves financial records from **CSV**
and **PDF** sources. CSV rows and AI-extracted PDF content converge on a single
normalized model.

> **Work in progress.** This README will be replaced by the full documentation
> once the application is feature-complete. See [Current state](#current-state).

## Getting started

Three things: run it, test it, and — only if you want real AI extraction —
give it a key.

### 1. Run the platform

```bash
docker compose up --build
```

That is the whole command. From a **clean clone, with no `.env` and no API key**:

| | Address | |
|---|---|---|
| Interface | http://localhost:5173 | Sign in, or register — registration is open |
| API | http://localhost:8000 | Applies its migrations at startup |
| API docs | http://localhost:8000/docs | Generated from the code |
| Database | localhost:5432 | PostgreSQL 17 |

Two choices make the first run credential-free: in debug the application
**generates a signing secret** at startup, and extraction falls back to a
**mock provider** that returns canned records. The whole workflow — import,
validate, correct, approve — is exercisable without an account anywhere.

Your data survives a restart: the database and the uploaded documents live on
named volumes, so `docker compose down` then `up` finds your batches intact.
`down -v` is what throws them away.

**Docker is required.** The application runs on PostgreSQL only; there is no
SQLite fallback.

### 2. Run the tests

The backend suite needs a database, so start that one service first:

```bash
docker compose up -d db

cd backend && make test        # 562 tests
cd frontend && npm ci && npm test   # 132 tests
```

`make test` supplies the two database URLs itself. They are written in the
Makefile rather than defaulted in the code, because the suite **empties every
table** in the test database — which one that is should be readable, not
guessed. The harness refuses to start if that URL matches the application's, or
if its database name does not end in `_test`.

Tests that call a real AI provider are excluded by default. Run them
deliberately, with a key configured:

```bash
cd backend && make test-live
```

### 3. Credentials and environment variables

**No real credential is in this repository, and none can be.** `.env` is
git-ignored, and CI scans the whole history with `gitleaks` on every push — a
key committed by accident fails the build rather than sitting there.

What is committed is `backend/.env.example` and `frontend/.env.example`:
templates with every variable documented and every secret **left empty**. Copy
one when you need it:

```bash
cp backend/.env.example backend/.env
```

The variables that matter:

| Variable | Needed when | What happens without it |
|---|---|---|
| `EXTRACTION_PROVIDER` | you want real PDF extraction | Falls back to `mock`; the workflow still runs end to end |
| `OPENAI_API_KEY` | `EXTRACTION_PROVIDER=openai` | The application **refuses to start**, rather than failing on someone's first upload |
| `GEMINI_API_KEY` | `EXTRACTION_PROVIDER=gemini`, or as the fallback link | Same |
| `JWT_SECRET` | anywhere but local debug | In debug, an ephemeral one is generated — which invalidates open sessions on every restart, and is why it is a local mode and not a deployment |
| `DATABASE_URL` | always | No default at all: a wrong default would silently point a deployment at the wrong database |

**One rule about the frontend**: `frontend/.env` may hold exactly one variable,
the API address. Every `VITE_*` value is compiled into the JavaScript sent to
the browser, where anyone can read it. That is publication, not configuration,
so no provider key ever belongs there. Extraction is server-side only; the
interface does not even know which provider is used.

Generate a real signing secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Signing in

The API requires authentication. Registration is open, so the quickest path is
to create an account from the interface. `make seed` also creates two
demonstration accounts:

| Email | Password |
|---|---|
| `demo@example.com` | `demo-password-123` |
| `second@example.com` | `demo-password-123` |

Each owns a separate workspace, which is the quickest way to see tenant
isolation: sign in as one, create a batch, sign in as the other, and it is not
there. Registration is open, so a new account works too.

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

### Isolation is on the tenant, not the user

Registration creates one account and one workspace, so in practice every user
has their own today. Neither the schema nor the authorisation requires that.

`user.tenant_id` is a plain foreign key: the only `UNIQUE` on the table is
`email`, and the index on `tenant_id` is deliberately **not** unique. Several
accounts can therefore belong to one workspace — verified by adding a second
member to an existing tenant and signing in as them:

```
bug@example.com        -> 1 batch: ['Bug']
colleague@example.com  -> 1 batch: ['Bug']      # same workspace, same data
del@example.com        -> 0 batches             # another workspace, nothing
```

**This works because authorisation was never built on the user.** Every query
filters on the tenant resolved from the token, never on who is signed in — the
same property that makes cross-tenant access return `404`. A second member
inherits it without a line changing.

What is genuinely missing is the way in: no route invites an account into an
existing workspace, and registration always creates a new one. Adding an
organisation would mean an invitation flow and roles, not a data model change —
the part that usually forces a migration is already there.

---

## AI provider

PDF content is extracted by a language model and converted into the same
normalized records a CSV produces.

**The choice was measured, not argued.** Reading fifteen fields off an invoice
does not separate these models — both did it correctly every time. The dense
six-column bank statement does, and it is the document the assignment supplies
precisely because it is harder.

Three runs each, same prompt, same document, counting records against the eight
transaction rows the statement actually holds:

| | Records returned | Duration | References read |
|---|---|---|---|
| **OpenAI `gpt-5.6`** | **8, 8, 8** | 24–37 s | all eight |
| Google `gemini-3.5-flash` | 2, 2, 8 | 30–157 s | none |

**OpenAI is the primary provider** on that evidence. Gemini did not merely
return fewer rows: it left every `reference` null and, before the prompt
described the table explicitly, concatenated two date cells into
`"2026-07-0101/07/2026"`.

**What that costs, stated plainly.** The earlier argument for Gemini was not
about capability, and it has not gone away: the same SDK reaches Vertex AI,
where processing can be pinned to an EU region (`europe-west1`) under a data
residency commitment. For an application handling European bank statements that
matters, and a deployment bound by it should set `EXTRACTION_PROVIDER=gemini`
and accept the reliability shown above — or pay for a stronger Gemini model,
which is the same trade-off seen from the other side. The decision here is
correctness on the supplied documents; the decision in production may differ,
and the point is that it costs one environment variable.

**The chain runs in whichever order the variable names.** With both keys
present, `openai` yields `[openai, gemini]` and `gemini` yields the reverse: a
transient failure on the primary falls through. A permanent failure — bad key,
unknown model — is never retried, since retrying cannot help and only delays
the fallback.

**Mock** keeps the application fully usable with no credentials, and is what the
test suite runs against.

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

### A limit worth stating

On the supplied bank statement — a dense six-column table of eight rows —
extraction is **not reliable**. Measured over six runs on `gemini-3.5-flash`,
the model returned 8 records three times, 2 records twice, and 1 record once.

Two things were done about it. The prompt now describes the statement as a
table and forbids merging rows or concatenating cells, which removed a failure
where eight rows collapsed into one record holding `"2026-07-0101/07/2026"` —
two date cells joined. And an instruction to count the rows before answering
was tried and **reverted**: it pushed the model to invent a tenth row, which
breaks the rule that matters most.

What remains is a model limit, not a code one, and the application degrades
safely into it: a short extraction produces records with missing required
fields and zero confidence, which land in `NEEDS_REVIEW` for a person to
check. Reliability here is a question of model choice and budget, and belongs
with the same trade-off as provider selection.

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

## Configuration in depth

[Getting started](#getting-started) covers the common path. This is the part
that bites once you change something.

**What `backend/.env` cannot decide.** The `api` service loads it when present
and ignores its absence — that is how a clean clone starts. But
`DATABASE_URL`, `UPLOAD_STORAGE_DIR` and `CORS_ALLOWED_ORIGINS` are set in
`docker-compose.yml` and **override** it. A `DATABASE_URL` pointing at
`localhost` is right on your machine and wrong inside the container network, so
your file decides *what* the application does and the compose file decides
*where* it runs.

Precedence, lowest to highest: the image's own `ENV` — which is what makes
`mock` the fallback — then `backend/.env`, then `docker-compose.yml`.

```bash
cp backend/.env.example backend/.env   # fill in EXTRACTION_PROVIDER and a key
docker compose up -d --force-recreate api
```

**Developing outside the containers.** Useful when you want reload-on-save.
Keep the database in Docker and run the two servers on the host:

```bash
docker compose up -d db
cd backend && make seed && make run
cd frontend && npm install && npm run dev
```

`make seed` creates the two demonstration accounts listed under
[Signing in](#signing-in), and needs `DATABASE_URL` in `backend/.env`;
`.env.example` already points at the compose database.

The frontend runs on a different origin from the API on purpose rather than
behind a dev proxy: a proxy would put both on one origin and hide the CORS
configuration and cookie rules that ship, so nobody would exercise them until
production.

## Upgrading an existing database

Authentication is a **breaking change for data created before it existed**.
Batches used to belong to a default workspace with no account attached, and a
workspace with no account cannot be signed into — so that data becomes
unreachable.

The migration cannot repair this: attaching a user would mean inventing a
password and committing it to migration history. So it **refuses to run** on a
database that already holds batches, rather than completing and quietly making
them unreachable:

```
This database holds 3 batch(es) created before accounts existed.
They belong to a workspace with no user, so after this migration no one
could sign in and reach them.

Either start from an empty database, or re-import the data into a
registered account afterwards and set ALLOW_ORPHANED_DATA=1 to proceed.
```

Accepting the consequence is a deliberate act. `make seed` also reports any
workspace left without an account, so nothing disappears silently.

**A fresh installation is unaffected** and needs none of this.

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
- Authentication: Argon2id, short-lived access tokens kept in memory, rotating
  refresh tokens with reuse detection
- Tenant scoping on every query, with cross-tenant access returning `404`
- PostgreSQL only, in Docker. Alembic migrations are applied from an empty
  database by the test suite, by the API container at startup, and by CI —
  which also downgrades to empty and back, so every revision is reversible
- PDF extraction through Gemini, with an OpenAI fallback, per-field confidence,
  token accounting and background processing
- React interface covering the whole workflow: sign-in, batches, upload,
  extraction progress, filters, field-level errors, correction, approval
- CI: lint, tests on three Python versions, migration drift, frontend types and
  build, secret scanning

**Not yet**

- Nothing from the assignment's scope. Remaining items are listed under
  [Production improvements](#production-improvements).

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
