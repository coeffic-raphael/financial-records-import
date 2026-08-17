# Financial Records Import

[![CI](https://github.com/coeffic-raphael/financial-records-import/actions/workflows/ci.yml/badge.svg)](https://github.com/coeffic-raphael/financial-records-import/actions/workflows/ci.yml)

Imports, extracts, validates, corrects and approves financial records from **CSV**
and **PDF** sources. CSV rows and AI-extracted PDF content converge on a single
normalized model.

---

## 1. Setup and run instructions

**Docker is required.** The application runs on PostgreSQL only; there is no
SQLite fallback.

### Run the platform

```bash
docker compose up --build
```

That is the whole command. From a **clean clone, with no `.env` and no API key**:

| | Address | |
|---|---|---|
| Interface | http://localhost:5173 | Register an account — registration is open |
| API | http://localhost:8000 | Applies its migrations at startup |
| API docs | http://localhost:8000/docs | Generated from the code |
| Database | localhost:5432 | PostgreSQL 17 |

Two choices make the first run credential-free: in debug the application
**generates a signing secret** at startup, and extraction falls back to a
**mock provider** returning canned records. The whole workflow — import,
validate, correct, approve — is exercisable without an account anywhere.
Section 2 explains what to add for real AI extraction.

Your data survives a restart: the database and the uploaded documents live on
named volumes, so `docker compose down` then `up` finds your batches intact.
`down -v` is what throws them away.

### Sign in

Registration from the interface is the quickest path. `make seed` also creates
two demonstration accounts:

| Email | Password |
|---|---|
| `demo@example.com` | `demo-password-123` |
| `second@example.com` | `demo-password-123` |

Each owns a separate workspace, which is the quickest way to see tenant
isolation: sign in as one, create a batch, sign in as the other, and it is not
there.

### Sample files

The files supplied with the assignment are committed under
[`samples/`](samples/) and are used directly by the test suite — nothing needs
to be placed manually. `transactions_import.csv` is a test suite in disguise,
one row per validation rule: importing it yields **18 `VALID`** and
**12 `NEEDS_REVIEW`** records, and a test asserts the exact error codes of every
row.

### Run the tests

The backend suite needs a database, so start that one service first:

```bash
docker compose up -d db

cd backend  && make test              # 564 tests
cd frontend && npm ci && npm test     # 132 tests
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

### Develop outside the containers

Useful when you want reload-on-save. Keep the database in Docker and run the two
servers on the host:

```bash
docker compose up -d db
cd backend  && make seed && make run
cd frontend && npm install && npm run dev
```

The frontend runs on a different origin from the API on purpose rather than
behind a dev proxy: a proxy would put both on one origin and hide the CORS
configuration and cookie rules that ship, so nobody would exercise them until
production.

---

## 2. Environment variables

**No real credential is in this repository, and none can be.** `.env` is
git-ignored, and CI scans the whole history with `gitleaks` on every push — a
key committed by accident fails the build rather than sitting there.

What *is* committed is `backend/.env.example` and `frontend/.env.example`:
templates with every variable documented and every secret **left empty**.

```bash
cp backend/.env.example backend/.env
docker compose up -d --force-recreate api    # picked up on restart
```

### How to obtain each one

| Variable | Where to get it |
|---|---|
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> — create a key, then add credit under Billing. Needs a few dollars; a document costs a few thousand tokens |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> — free, no card. The free tier is rate-limited, which is enough to try it and not enough to lean on |
| `JWT_SECRET` | Generate it yourself, it is not obtained from anyone:<br>`python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | Already set by `docker-compose.yml`. Only write it yourself when running outside the containers, pointing at the compose database:<br>`postgresql+psycopg://app:app@localhost:5432/financial_records` |

### What each one does, and what happens without it

| Variable | Needed when | Without it |
|---|---|---|
| `EXTRACTION_PROVIDER` | you want real PDF extraction | Defaults to `mock`; the workflow still runs end to end |
| `OPENAI_API_KEY` | `EXTRACTION_PROVIDER=openai` | The application **refuses to start**, rather than failing on someone's first upload |
| `GEMINI_API_KEY` | `EXTRACTION_PROVIDER=gemini`, or as the fallback link of the chain | Same |
| `JWT_SECRET` | anywhere but local debug | In debug an ephemeral one is generated, which invalidates open sessions on every restart — that is why it is a local mode and not a deployment |
| `DATABASE_URL` | always | No default at all: a wrong default would silently point a deployment at the wrong database |

Optional knobs — timeouts, the confidence threshold, upload size, token
lifetimes — are documented inline in `.env.example` with their defaults.

### One rule about the frontend

`frontend/.env` may hold exactly one variable, the API address. Every `VITE_*`
value is compiled into the JavaScript sent to the browser, where anyone can read
it. That is publication, not configuration, so **no provider key ever belongs
there**. Extraction is server-side only; the interface does not even know which
provider is used.

### What your file cannot decide

The `api` service loads `backend/.env` when present and ignores its absence —
that is how a clean clone starts. But `DATABASE_URL`, `UPLOAD_STORAGE_DIR` and
`CORS_ALLOWED_ORIGINS` are set in `docker-compose.yml` and **override** it. A
`DATABASE_URL` pointing at `localhost` is right on your machine and wrong inside
the container network, so your file decides *what* the application does and the
compose file decides *where* it runs.

Precedence, lowest to highest: the image's own `ENV` — which is what makes
`mock` the *default*, not a link in the provider chain — then `backend/.env`,
then `docker-compose.yml`.

---

## 3. Main architecture and technical choices

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

### Where a rule lives

The backend is split by *what a thing decides*, not by framework convention.

| | |
|---|---|
| `app/domain/` | The rules themselves: normalization, validation, the enums the data dictionary fixes. No database, no HTTP. |
| `app/services/` | Orchestration and transactions: import, extraction, correction, summary. |
| `app/api/` | HTTP only — request shape, status codes, and the tenant resolved from the token. |
| `app/providers/` | One interface, three implementations. Swapping the model is configuration, never a code change. |

One rule inside that split is worth naming, because getting it wrong is the
usual source of half-written data: **mutation and transaction are separate**.
`correct_in_transaction` changes a record and does not commit;
`apply_correction` and `apply_corrections` commit exactly once. A bulk edit of
two hundred records is therefore one transaction that either lands whole or not
at all, and the single-record path reuses the same function rather than a copy.

### Why PostgreSQL, and why nothing lighter

Not a preference: an import must be able to run while another one is running on
the same batch, and `SELECT … FOR UPDATE` is what makes that correct. Seven code
paths take that row lock before reading, so two concurrent imports cannot both
believe they own the same sequence number. SQLite has no equivalent, which is
why it was removed rather than kept as a convenience for local runs — one engine
in development and another in production is a class of bug nobody sees until
deployment.

### Frontend state: two stores, on purpose

**Server state belongs to TanStack Query. Session state belongs to Zustand.
Nothing else lives in the store.**

The store has **no `persist` middleware**, and that is a security decision
rather than an omission: `persist` writes to `localStorage`, which would undo
the "access token in memory only" choice in a single import and reopen the XSS
exposure the rest of the design avoids.

**Query keys are prefixed with the user id** — `["u", userId, …]`. The cache is
the one leak vector between two people sharing a machine that the server cannot
close by itself, so a collision between two users is made structurally
impossible, and signing out clears the cache on top of that. It is the same
concern as the tenant isolation below, handled at the other end of the wire.

Every mutation names what it invalidates rather than refetching everything, and
one invalidation exists because of a bug: polling told the UI when extraction
*finished*, but nothing told the records table or the summary, so both kept
showing the state from before the upload until the user navigated away and
back — which is precisely what hid the problem during a manual check.

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

## 4. Data model

Seven tables. The shape follows one rule, stated here because it explains every
column width and every missing constraint below.

```
tenant ──┬── user ──── refresh_token
         └── import_batch ──┬── source_document ──┐
                            ├── financial_record ─┤  (source_document_id)
                            └── extraction_job ───┘
```

| Table | Holds |
|---|---|
| `tenant` | A workspace. Every query filters on it |
| `user` | An account. `tenant_id` is a plain foreign key, so a workspace may hold several |
| `refresh_token` | A rotating session, stored as a SHA-256 hash, never in clear |
| `import_batch` | The unit of import, and of deletion |
| `source_document` | An uploaded file: its name, media type, size and content hash |
| `financial_record` | The 20 fields of the data dictionary, plus how it got there |
| `extraction_job` | One PDF's extraction: status, provider, model, tokens, duration |

### The governing rule: strict on system columns, permissive on user data

The assignment requires importing **every** CSV row, flagging the bad ones. A
constraint on a user-supplied column would turn a reportable error into a failed
`INSERT` — and because an import is one transaction, one bad cell would lose the
whole file.

So the columns split in two:

| | Type | Why |
|---|---|---|
| `status`, `source_type`, provider names | Bounded, with `CHECK` constraints | The application decides these; a wrong value is a bug, not user input |
| `reference`, `description`, `counterparty_name`, `country`, `category`… | `TEXT`, unbounded, nullable | A person typed these. `country VARCHAR(2)` would make `"LUX"` fail the insert instead of being reported as `INVALID_COUNTRY_CODE` |

Plausibility limits live in the domain, where breaking one is a business error
with a code and a message, not a database exception.

### Three decisions worth naming

**Amounts are `NUMERIC(18, 2)`, never floats.** Money never touches binary
floating point, and psycopg returns `Decimal`. The scale is enforced as a
business rule too: more than two decimals is reported as
`AMOUNT_SCALE_EXCEEDED` rather than silently rounded — `0.0001` must not become
a `VALID` record holding `0.00`.

**`raw_payload` is the source of truth.** Every record keeps the values exactly
as they arrived, as JSON. A correction is merged into it and the whole pipeline
is replayed, which is what makes the import path and the correction path
impossible to drift apart. It is also what lets the interface show
*as extracted* next to a corrected field.

**No `UNIQUE` on `reference`.** Uniqueness is per import and per batch, and the
assignment requires a duplicated row to be **imported and flagged**, not
rejected. A database constraint would refuse it. Ordering comes from
`import_sequence`, the arrival position, so the first of two duplicates stays
`VALID` and only the second is flagged — and stays that way when revalidated.

Identifiers are `CHAR(36)` rather than PostgreSQL's native `UUID`. That began as
a portability constraint and is now a retained choice: retyping fifteen columns
and the eight foreign keys between them, on a schema that works, would buy
twenty bytes a row and a validation the application already performs.

### Migrations

Alembic, applied from an empty database by the test suite, by the API container
at startup, and by CI — which also downgrades to empty and back, so every
revision is reversible. A new `NOT NULL` column is added nullable, backfilled,
then tightened; a `server_default` would quietly give every existing row the
same value.

---
## 5. AI provider integration approach

PDF content is extracted by a language model and converted into the same
normalized records a CSV produces.

### What the code requires of a model

Two requirements come from the code itself, and they remove most of the
catalogue before any preference is expressed.

**It must accept a PDF directly.** The file is handed over as bytes —
`input_file` on OpenAI, `type: "document"` on Gemini. There is no OCR step and
no text pre-extraction, because a statement's meaning is carried by its table
layout: flattening it to a line of text is exactly what produced the merged-cell
failure described further down.

**It must honour a strict output schema.** The call is
`responses.parse(text_format=ExtractionEnvelope)` on OpenAI, and a
`response_format` carrying a JSON Schema on Gemini. Fifteen fields per record,
each with its own confidence. Free-form prose would need a parser, and a parser
would have to guess.

Text-only, audio, embedding and code-completion models are therefore not
candidates whatever their benchmark scores, which is most of what a provider
offers.

### Which models are actually callable

Availability was checked rather than assumed, and it is not a fixed list:
`gemini-2.5-flash` is **retired** on the `interactions` API this code uses — it
answers `404 no longer available` — while still being listed for the older
`generateContent` surface. A model that exists is not a model you can call.

### Choosing the OpenAI model

Reading fifteen fields off an invoice separates nothing: every candidate does it
correctly. The dense six-column bank statement separates them, and the
assignment supplies it precisely because it is the harder document. Each
candidate received the same prompt and the same file, twice, scored against the
eight transaction rows the statement actually holds — rows found, and among
those rows how many carried the right reference, amount and date:

| | Rows | References | Amounts | Dates | Duration | Cost per statement |
|---|---|---|---|---|---|---|
| **`gpt-5.4-mini-2026-03-17`** | **8, 8** | 8, 8 | 8, 8 | 8, 8 | **9–15 s** | **$0.0096** |
| `gpt-5.6` (→ `gpt-5.6-sol`) | 8, 8 | 8, 8 | 8, 8 | 8, 8 | 26–27 s | $0.0785 |
| `gemini-3.5-flash` | 2, 8 | 1, 8 | 0, 8 | 0, 8 | 15–23 s | $0.0474 |
| `gemini-3.7-flash` | *abandoned* | | | | > 380 s | — |

Cost is computed from the tokens the runs actually reported against each
vendor's published per-million rates, not estimated.

**`gpt-5.4-mini` is the primary model**, and the reason is the first two rows:
the expensive tier buys nothing measurable on this workload. `gpt-5.6` scored
exactly the same on every dimension while taking two to three times as long and
costing **eight times as much**. It was the earlier default here by inheritance
rather than by decision, which is what the measurement corrected.

**Where that argument is weak, stated plainly.** Two passes are enough to
establish a *difference* and thin for establishing an *equality*: what is
demonstrated is that mini did not lose a single field on the hardest supplied
document, not that it never would on a messier one. The mitigation is that the
choice costs one variable to revisit, and that a degraded extraction lands in
`NEEDS_REVIEW` rather than in an approved record.

`gemini-3.7-flash` was dropped for a measurable reason rather than a suspected
one: a single extraction ran past **380 seconds**, more than twice the
`EXTRACTION_TIMEOUT_SECONDS` budget, so it cannot hold a fallback slot without
raising the timeout for every document.

### Why the model is pinned rather than named

`gpt-5.6` is a floating **alias**: it resolves to `gpt-5.6-sol` today and may
point elsewhere tomorrow. For financial extraction that is the wrong default —
behaviour would change with no commit, and the table above would quietly stop
being reproducible. The primary is therefore pinned to an exact build,
`gpt-5.4-mini-2026-03-17`, and moving to a newer one is a deliberate edit that a
test enforces.

The fallback **cannot** be pinned the same way: Gemini publishes no dated build
for this tier, so `gemini-3.5-flash` is the only name available and its
behaviour can shift without notice. That is a real gap rather than an oversight,
and it is tolerable only because this is the fallback and not the primary.

### Choosing the Gemini model, and what it is for

Gemini is the **fallback**, so its job is to answer when OpenAI is
transiently unavailable — not to match it. `gemini-3.5-flash` is the flash-tier
model this key can call on the `interactions` API, and the table shows what it
delivers: one pass read all eight rows, the other collapsed the table into two
records with the references empty. Its recorded history agrees, including a
140-second run that returned a single record.

Two open items are worth naming rather than hiding. `gemini-3.6-flash` is now
callable — it was quota-refused when this default was chosen, which is why the
older model is still here — and at \$0.75/\$3.75 per million it is **cheaper**
than the 3.5 tier it would replace. It is unmeasured, so it is not the default
yet.

**The residency trade-off has not gone away.** The same SDK reaches Vertex AI,
where processing can be pinned to an EU region (`europe-west1`) under a data
residency commitment. For an application handling European bank statements that
matters, and a deployment bound by it should set `EXTRACTION_PROVIDER=gemini`
and accept the reliability shown above — or pay for a stronger Gemini model,
which is the same trade-off seen from the other side. The decision made here is
correctness and cost on the supplied documents; a production decision may differ,
and the point is that it costs one environment variable.

### How to configure it

Three variables, in `backend/.env`. Section 2 says where each key comes from.

```bash
# openai | gemini | mock  — this one name decides the whole chain
EXTRACTION_PROVIDER=openai

OPENAI_API_KEY=sk-...           # required by the name above
GEMINI_API_KEY=AQ...            # optional here: it becomes the fallback link
```

Then restart the API so it reads the file:

```bash
docker compose up -d --force-recreate api
```

**The name is the order.** `EXTRACTION_PROVIDER` names the primary, and when the
other key is present it becomes the fallback — `openai` yields
`[openai, gemini]` and `gemini` yields the reverse. A transient failure on the
primary falls through; a permanent one — bad key, unknown model — is never
retried, since retrying cannot help and only delays the fallback. Switching them
is this one variable and no code change, which is what let the measurement above
be made so cheaply.

Leave it at `mock` and the application needs no credential at all, which is how
a clean clone starts.

The models and the timeout are configurable too, and these are the values the
measurement used:

```bash
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
GEMINI_MODEL=gemini-3.5-flash
# Sized for the slowest provider in the chain, not the primary: OpenAI answers
# the statement in 9-15 s, Gemini has taken 140 s on the same document.
EXTRACTION_TIMEOUT_SECONDS=180
```

Two guarantees worth knowing. A **misconfigured provider stops the application
from starting** — `lifespan` builds the provider before serving, so a name with
no matching key fails at boot rather than on someone's first upload. And **no
provider key may ever carry a `VITE_` prefix**: those are compiled into the
browser bundle. Extraction is server-side only, and the frontend never learns
which provider is used.

The full list, with every default, is in
[`backend/.env.example`](backend/.env.example).

### What the model is told, and what it is not trusted with

The prompt states twelve numbered rules drawn from the supplied documents —
first among them **never invent a value**: an absent field must come back as
`null` with confidence 0. Several exist because a specific extraction went
wrong: the statement is described as a table whose rows and cells may not be
merged, the header is declared to describe the *account* rather than the
counterparty, and the per-line `Amount` is named as the figure to read, never
the running `Balance` beside it. The enumerated fields — currency, category,
payment method, country — are constrained to the values the domain accepts, so
the model cannot invent a vocabulary the validator would then reject.

Nothing the model returns is trusted. The response is validated against a
structural schema **before anything reaches the database**, and every field is
optional in that schema: whether a field is required is a business rule, so it
belongs to the domain. An incomplete extraction therefore produces a
`NEEDS_REVIEW` record rather than a parse failure.

### A limit worth stating

The dense six-column statement is where extraction becomes unreliable, and the
unreliability belongs to a **specific provider rather than to the feature**.
Every recorded run on the pinned OpenAI model read all eight rows. Gemini, on
the same document, has returned 8 rows, 2 rows and 1 row across runs.

Two things were done about it. The prompt now describes the statement as a
table and forbids merging rows or concatenating cells, which removed a failure
where eight rows collapsed into one record holding `"2026-07-0101/07/2026"` —
two date cells joined. And an instruction to count the rows before answering
was tried and **reverted**: it pushed the model to invent a tenth row, which
breaks the rule that matters most.

What remains is a model limit, not a code one, and the application degrades
safely into it: a short extraction produces records with missing required
fields and zero confidence, which land in `NEEDS_REVIEW` for a person to
check. It is also why the fallback is ordered the way it is — falling back
costs accuracy on this document, so it happens only when the primary cannot
answer at all.

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

---

## 6. Assumptions

Where the assignment left room, these are the readings taken. Each one is a
decision that could have gone the other way.

**A bank statement row does not state its counterparty.** The supplied statement
names exactly one party — "Account holder: Northbridge Fund SCSp", the account
owner — and the data dictionary defines `counterparty_name` as "supplier,
customer, bank or investor", which is the *other* side. So the account holder is
never it, and rows that name no other party leave the field empty. Filling it
would put the wrong name on all eight rows and clear a required field.

**`country` is the exception, and the dictionary's own naming is why.** Two
fields carry the `counterparty_` prefix and one does not; `country` is defined
as "ISO alpha-2 country code" without saying whose. It is therefore taken from
the account's IBAN, while `counterparty_account` stays empty because its name
says whose account it is.

**A statement row states what was settled, not how it was composed.** So
`gross_amount`, `tax_amount` and `fee_amount` stay empty unless the row itself
gives them. Writing `gross = net` asserts there was no tax, which the document
never says — and the invoice for one of those rows proves it wrong: 4,680.00 on
the statement is 3,900.00 plus 780.00 of VAT.

**`payment_method` is optional**, per the dictionary. This is why one sample row
without it is `VALID` rather than flagged.

**`VALIDATED` is a human act.** The dictionary lists three statuses and the
engine derives only two: a record becomes `VALID` when it has no errors, and
`VALIDATED` only through an explicit approval. `status` is therefore not
writable through the API at all.

**Enumerations are matched case-insensitively after trimming.** A spreadsheet
export rarely writes `MANAGEMENT_FEE` perfectly, and refusing `management_fee`
would ask a person to fix data that is not wrong. The stored value is the
canonical form.

**One account, one workspace.** Registration creates both. The schema does not
require it (§3), but no invitation flow exists.

---

## 7. Completed and incomplete features

### Required by the assignment — complete

| | |
|---|---|
| Common data model | The 20 fields, 15 categories, 4 currencies, 3 statuses |
| CSV ingestion | Every row imported, never the file rejected. The only global refusal is a header missing required columns |
| PDF extraction through a real provider | OpenAI primary, Gemini as the fallback link, both with live tests |
| Validation | The 10 rules of the dictionary, verified individually |
| Status machine | `NEEDS_REVIEW` / `VALID` / `VALIDATED`, with correction always revalidating |
| Backend API | The 10 required endpoints, plus jobs, source documents and a paginated record list |
| Frontend | The 9 required screens: batch creation, upload, processing status, record list, filters, field-level errors, editing, revalidation, individual validation, batch summary |
| Tests | 564 backend, 132 frontend |

### Bonus features — complete

Authentication (Argon2id, rotating refresh tokens with reuse detection),
multi-tenant isolation, provider fallback chain, token and cost accounting,
per-field confidence, background PDF processing, Docker Compose, CI.

### Beyond the assignment

Kept because the workflow was unusable without them: the **source document**
viewable next to a record — reviewing an extraction means comparing it to
something — **batch deletion**, the only way to undo a wrong upload,
**duplicate-document refusal** with an explicit override, and **bulk
correction**, because a statement leaves eight records needing the same value.

### Incomplete

| | |
|---|---|
| Inviting an account into an existing workspace | The schema supports several members; no route creates the second one |
| Renaming a batch | Delete and re-import is the only way |
| Deleting or bulk-deleting a record | Deliberate: records are auditable artifacts. Batches are the unit of deletion |
| Undoing a correction | Would need a history of replaced values, which does not exist |
| A video walkthrough | To be linked here |

---

## 8. Known limitations

**The fallback provider is unreliable on a dense table.** On the supplied bank
statement, every recorded run of the pinned OpenAI model read all eight rows
with all eight references; `gemini-3.5-flash` returned 8 rows on one pass and 2
rows with a single usable reference on another. Falling back therefore costs
accuracy on exactly the document that is hardest, which is why it happens only
when the primary cannot answer at all. The prompt was strengthened to describe
the table and forbid merging rows, which removed a failure where eight rows
collapsed into one; an instruction to count the rows first was tried and
**reverted** — it produced a tenth, invented row. What remains is a model limit,
and the application degrades into it safely: a short extraction lands in
`NEEDS_REVIEW` for a person.

**The model choice rests on two passes per candidate.** Enough to show that the
cheap tier lost nothing on the hardest supplied document, not enough to prove it
never would on an unseen one. §5 states the measurement and its size.

**Two required fields will always be empty on a statement**, per §6. Every
statement row therefore needs human input before it can be approved. That is
the assignment's own rule working, not a defect — and bulk correction exists so
the cost is one entry rather than eight.

**Adding accounts to a database that predates them is refused.** Batches used to
belong to a workspace with no user, and a workspace with no account cannot be
signed into. The migration cannot repair this — attaching a user would mean
inventing a password and committing it to migration history — so it **refuses to
run** on a populated database and says how to proceed:

```
This database holds 3 batch(es) created before accounts existed.
Either start from an empty database, or re-import the data into a
registered account afterwards and set ALLOW_ORPHANED_DATA=1 to proceed.
```

A fresh installation is unaffected.

**Extraction runs in-process.** A background task does not survive a restart and
does not spread across workers. Uploads accepted moments before a redeploy are
lost, and their jobs stay `PENDING`.

**Transitive dependencies are unpinned.** Direct ones are; a clean install in
three weeks may resolve a different `starlette`.

**Amounts are aggregated in Python, not in SQL.** Correct and covered by tests;
it would not survive a batch of a hundred thousand records.

**`1.200,00` and `1,200.00` are both accepted** by inferring the decimal
separator from position. The heuristic is documented and tested, but it is a
heuristic: a genuinely ambiguous value gets one reading, not a question.

---

## 9. Production improvements

Deliberately out of scope here, with the approach that would be taken:

- **Dependency locking.** Direct dependencies are pinned; transitive ones are
  not, so a clean install three weeks from now may resolve a different
  `starlette`. Production would use a full lockfile (`pip-tools`, `uv`, or a
  committed `pip freeze`), regenerated in CI.
- **Background job queue.** PDF extraction runs in-process; it does not
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
- **Reference uniqueness in the schema.** Concurrency inside a batch is
  handled: every path that reads references or writes a status takes a row lock
  on the batch first, and a test proves two simultaneous imports neither
  overlap their positions nor miss a duplicate between them. What is still
  application-level rather than declared is the uniqueness itself — the
  assignment requires importing a duplicated row instead of rejecting it, which
  a plain constraint would refuse. A partial unique index
  (`WHERE reference IS NOT NULL`) plus conflict handling that marks the losing
  row `NEEDS_REVIEW` would move it into the schema.
- **TLS to a managed PostgreSQL**, rate limiting on authentication, and full
  security headers.

---
## 10. AI tools used

**Claude Code** was used as a development assistant, and **Codex** was used for
code review.

Before each development stage, a markdown plan of the steps to follow was
written with Claude Code: what to change, in what order, and what would count as
done. Development then followed that plan rather than improvising, and each
stage was reviewed by Codex once implemented.

A large part of the test suite was generated with Claude Code: the 564 hermetic
backend tests, the 11 live provider cases, and the 132 frontend tests.

The plans live in `docs/plans/`, which is not committed.

---
