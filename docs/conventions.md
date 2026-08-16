# Project conventions

> Rules that apply to the whole codebase. They are written to be **checkable in
> review**, not decorative.

---

## 1. Money and correctness

| Rule | Why |
|---|---|
| `Decimal` everywhere in Python, **never `float`** | With a 0.01 tolerance on `net_amount`, a floating-point error becomes a business false positive |
| Amounts serialized as JSON **strings** (`"1463.09"`) | A JSON number is turned back into a float by `JSON.parse` — precision is lost before it is even displayed |
| The frontend **never recomputes** `gross + tax − fee` | The server is the single arithmetic authority; the client displays the expected value it is given |
| `Numeric(18, 2)` in the database | No SQL floating-point type |

Check: no `float(` and no `: float` anywhere under `app/domain/`. A unit test
locks this in by asserting `Decimal("0.1") + Decimal("0.2") == Decimal("0.3")`,
which is false in float arithmetic.

---

## 2. Database

### 2.1 Normalisation

The relational core is in **3NF**: `tenant`, `user`, `refresh_token`,
`import_batch`, `financial_record`, `extraction_job`. No data is duplicated
across tables and every functional dependency goes through a key.

Tenant isolation is carried by **a single edge**: `import_batch.tenant_id`.
`financial_record` inherits it through `batch_id` and **does not duplicate**
`tenant_id` — two sources of truth for the same fact are a guarantee of
divergence eventually.

### 2.2 Three deliberate exceptions

Three columns are JSON rather than dedicated tables. Each is justified by the
same criterion: **a derived value that is replaced wholesale, never updated
individually, and never read without its parent row is not an entity — it needs
no identity of its own.**

| Column | Normalised alternative | Why JSON wins |
|---|---|---|
| `validation_errors` | `validation_error(record_id, field, code, message)` | Regenerated in full on every validation, never edited one by one, never read without their record |
| `field_confidence` | `field_confidence(record_id, field, value)` | Same, and the field set follows the extraction schema rather than a relational model |
| `raw_payload` | — | Schemaless by nature: it is the trace of what came in |

If a need appeared to aggregate *"every record carrying `NET_AMOUNT_MISMATCH`"*
across batches, the normalised table would become the right choice. That need
does not exist here — the batch summary counts by **status**, not by error code.

### 2.3 The governing rule: strict on what we control, permissive on what the user supplies

The application's premise is that invalid data must be **persisted** and shown as
`NEEDS_REVIEW`, never rejected. Any database constraint applied to a
user-supplied column therefore turns a reportable business error into a failed
insert -- and because the import runs in one transaction, one bad value loses
the whole file.

Hence one rule, applied to every kind of constraint:

| Constraint | System-controlled columns | User-supplied columns |
|---|---|---|
| `NOT NULL` | yes — `id`, `batch_id`, `source_type`, `source_document_name`, `import_sequence`, `status`, `validation_errors`, `raw_payload`, timestamps | **no** |
| `CHECK` on enums | yes — `status`, `source_type`, job status | **no** — `currency`, `category`, `payment_method` must be able to hold an unsupported value |
| Length and precision | tight | **generous** — user-supplied columns are `TEXT`; a too-long value is a business error (`VALUE_TOO_LONG`), not a crash |
| `UNIQUE` | — | **no** — see §2.4 |

The certainty is not lost, it is relocated. It lives in three `NOT NULL`
columns: `status` (the verdict), `validation_errors` (why), and `raw_payload`
(what actually arrived). The database records the judgement instead of enforcing
it destructively -- which is what a tool whose job is to get bad data corrected
needs.

Being strict on a user-supplied column is the single mistake this codebase is
most likely to make, because it always looks like good schema design. It has
been made three times so far — nullability, `CHECK` constraints and column
widths — and only the third one reached the schema, where `country VARCHAR(2)`
would have made PostgreSQL reject the value `LUX` and lose the whole import.
SQLite ignores `VARCHAR` limits, so no test could have caught it.

Amounts get the same treatment from the other side. A value beyond
`NUMERIC(18, 2)` is reported as `AMOUNT_OUT_OF_RANGE` rather than handed to the
database to reject, and a value with more than two decimals is reported as
`AMOUNT_SCALE_EXCEEDED` rather than quietly rounded.

That second one guards a rule worth stating on its own: **what validation
accepts must be what storage keeps.** Accepting `0.0001`, declaring the record
VALID because the amount is non-zero, and then storing `0.00` makes the record
assert something about a value the database never received. Rounding money
silently is worse than refusing it.

The one deliberate exception is `extraction_confidence`, which *is* rounded to
two decimals: it is an estimate, so 0.9512 and 0.95 carry the same meaning.
Rounding money loses money; rounding a confidence loses nothing anyone acts on.

### 2.4 Trap: `reference` has NO uniqueness constraint in the schema

The assignment requires *"import all rows rather than rejecting the whole file"*,
and the supplied CSV deliberately contains a duplicate (`TX-2026-0003`, row 21).

A `UNIQUE(batch_id, reference)` — the natural reflex when normalising properly —
would **crash the import on that row** instead of persisting it as
`NEEDS_REVIEW`.

Uniqueness is therefore an **application-level validation rule**, not a schema
constraint. This is an assumed exception to "constraints live in the database",
and it is commented in the model so a reviewer does not "fix" it.

The policy is **first occurrence wins**, and it must be stable: the same record
must get the same verdict every time it is revalidated. That requires an
explicit arrival order, which `import_sequence` provides -- a UUID primary key
carries none. Uniqueness is compared against records that arrived *before* this
one, which also excludes the record itself.

### 2.5 Everything else

| Topic | Rule |
|---|---|
| Naming | `snake_case`, **singular** table names, `id` (uuid) primary key, `<table>_id` foreign keys |
| Enums | **`VARCHAR` + CHECK**, never a native Postgres enum — adding a category must not require a type migration |
| Foreign keys | Declared in the database, with `ON DELETE CASCADE` on `batch → records` |
| Indexes | `import_batch(tenant_id)`, `financial_record(batch_id, status)`, unique `user(email)`, unique `refresh_token(token_hash)` |
| Timestamps | `created_at` everywhere, `updated_at` on mutable tables (`financial_record`) |
| Migrations | **Alembic from the start**, never `create_all()` |
| Migration history | **Immutable.** A committed migration must keep running forever, so a symbol it references is never renamed away — see the `Money` alias in `db.py` |
| Backfills | A new `NOT NULL` column is added nullable, backfilled, then tightened. A `server_default` would quietly give every existing row the same value |
| `alembic check` blind spot | It runs on SQLite, where `ExactDecimal(3, 2)` and `ExactDecimal(18, 2)` both render as `String(64)`. A precision change is therefore invisible to it. Type changes that only differ on PostgreSQL need review, not CI |

---

## 3. Backend structure

### 3.1 CRUD, yes — but not everywhere

CRUD suits resources: create/list/read a batch, read/correct a record. It does
**not** suit the operations that carry the business value.

`import CSV`, `extract a PDF`, `revalidate`, `approve` and `summarize` are
**commands**, not resource mutations. Forcing them into CRUD would have a
concrete and serious consequence: if approving were written
`PATCH /records/{id} {"status": "VALIDATED"}`, **a client could declare itself
valid without going through server-side validation** — exactly what the
assignment forbids.

Hence the rule: `status` is **never** a `PATCH`-writable field. It changes only
through server-side recomputation or the explicit
`POST /records/{id}/validate` action.

### 3.2 Three layers, no ceremony

```
router  (api/)      HTTP only: parsing, status codes, DTOs
   │                no business rule, no SQL query
   ▼
service (services/) orchestration + transaction boundary
   │                owns the session, calls the domain
   ▼
domain  (domain/)   pure functions: normalization, validation
                    no session, no SQLAlchemy import
```

**No generic Repository layer.** The SQLAlchemy session *is* the repository;
adding one on top is an abstraction with no use here, and one more thing to
defend.

### 3.3 Routers

One `APIRouter` per resource — `auth`, `batches`, `records` — mounted with a
`prefix` and `tags`. Side benefit: the generated OpenAPI is grouped cleanly,
which makes the API immediately explorable.

### 3.4 Secure by default: dependencies on the **router**, not per-endpoint decorators

The common reflex is to decorate every endpoint:

```python
@router.get("/batches/{id}")
@require_auth            # ← opt-in: forgettable
@require_tenant_access   # ← opt-in: forgettable
def get_batch(...): ...
```

The intent is right — two layers, authentication then authorisation — but it is
**opt-in**: the day a route is added and a line is forgotten, the leak is silent.

We invert it. Dependencies are declared **on the router**, so they apply to
everything it contains:

```python
# app/api/batches.py — protected by construction
router = APIRouter(
    prefix="/batches", tags=["batches"],
    dependencies=[Depends(require_authenticated_tenant)],
)

# app/api/auth.py — the ONLY public router, explicitly
public_router = APIRouter(prefix="/auth", tags=["auth"])
```

Forgetting to *authenticate* a route becomes **impossible without a deliberate
act**: you would have to move it onto the public router.

Be precise about what this buys, though. The dependency guarantees the tenant is
**resolved** for every route on the router. It does **not** guarantee that each
SQL query filters on that tenant -- that stays the query author's
responsibility. The parametrised cross-tenant matrix in the test suite is what
guards scoping, by failing when a route is added without it.

Dependency chain:

```
require_authenticated_tenant
  └─▶ get_current_user   : verifies JWT signature and expiry  → 401
      └─▶ get_current_tenant : reads tenant_id from the token, never from the request
```

Extra safety net: the cross-tenant test matrix is parametrised over the list of
routes, so it fails if an unscoped route appears.

---

## 4. Errors

Two distinct notions, never to be conflated:

| | Nature | Shape |
|---|---|---|
| `FieldError` | **Business data**, persisted on the record | `{field, code, message}` in the database |
| API error | **Transport** | `{code, message, details}` in a 4xx/5xx response |

The latter go through centralised FastAPI exception handlers — no improvised
`HTTPException("something")` inside routers.

No error message returned to a client contains a stack trace, a table name, a
SQL query, or any fragment of a key.

---

## 5. Secrets and configuration

| Rule | Detail |
|---|---|
| Single source | One `Settings` object (pydantic-settings), read **once at startup** |
| Fail fast | A missing required variable means the application **does not start** |
| No scattered `os.getenv` | Everything goes through `Settings` |
| Masking `__repr__` | `print(settings)` must never reveal a key |
| Versioning | `.env.example` committed, `.env` never — `.gitignore` in place before any code |
| Logs | No key, no token, not even truncated |

### 5.1 Frontend: the `VITE_` trap

**Any variable prefixed `VITE_` is compiled into the JavaScript bundle sent to
the browser.** Anyone can read it in DevTools. That is not configuration, it is
publication.

Therefore:

- **No Gemini or OpenAI key ever carries the `VITE_` prefix.** Extraction is
  server-side only; the frontend calls `POST /batches/{id}/uploads/pdf` and has
  no knowledge of the provider.
- The only acceptable `VITE_` variables are **public by nature**:
  `VITE_API_BASE_URL`.
- Check: the CI `secrets` job (gitleaks), plus review of the frontend
  `.env.example`.

---

## 6. Security

### 6.1 Always verify certificates

TLS verification is never disabled, anywhere: no `verify=False`, no
`rejectUnauthorized: false`, no equivalent of `tlsAllowInvalidCertificates`.

Here this concerns the **outbound calls to Gemini and OpenAI**. Disabling
verification there would open a man-in-the-middle on financial documents *and*
on the API key itself. The SDKs verify by default: the rule is to **do nothing**
that undoes it, and to treat any suggested workaround for a certificate error as
a bug to fix at the root.

### 6.2 The refresh cookie and the `Secure` flag in development

`Secure` prevents the cookie from being sent over anything but HTTPS. In local
development over `http://localhost`, a `Secure` cookie is **never transmitted**
and authentication fails opaquely.

Cookie attributes are therefore **configuration-driven**: `Secure=False` in local
development, `Secure=True` everywhere else, with `httpOnly` and
`SameSite=Strict` **unconditional**. The switch is documented in the README.

### 6.3 Everything else

| Topic | Rule |
|---|---|
| Uploads | Maximum size, real type verified (not just the declared `Content-Type`), **sanitised filename** before persistence and display, storage outside any served directory |
| CORS | **Explicit** origin list. With credentials, browsers forbid `*` — this is not optional |
| Caching | `Cache-Control: no-store` on every authenticated response |
| Another tenant's resource | **`404`, never `403`** — a 403 would confirm the resource exists |
| Logs | Provider, model, duration, tokens, outcome. **Never document content**: this is personally identifiable financial data |

---

## 7. Frontend

### 7.1 State ownership — one rule, no exception

| Kind of state | Tool | Examples |
|---|---|---|
| **Server state** | **TanStack Query** | batches, records, errors, summary |
| **Client state** | **Zustand** | session (user, tenant, access token), UI preferences |
| Local state | `useState` | modal open, field being typed |

**No server data ever passes through Zustand.** Duplicating it there creates two
sources of truth and reintroduces by hand the invalidation React Query already
provides.

### 7.2 What React Query buys us specifically

The central flow of this application is **correct → revalidate → refresh**. That
is exactly the mutation → invalidation pattern:

```
PATCH /records/{id}  ─▶  invalidate  ['record', id]
                                     ['batch', batchId, 'records']
                                     ['batch', batchId, 'summary']
```

The summary and the table refresh themselves, with no hand-written derived
state. Loading and error states come for free, which covers the "processing
status" requirement for PDF extraction.

### 7.3 Tenant isolation in the cache — two measures

The React Query cache is a **leak vector** between two users on the same
machine. Two cumulative countermeasures:

1. **Query keys are prefixed with the user id**:
   `['u', userId, 'batch', batchId, 'records']`. A cache collision between two
   users becomes structurally impossible.
2. **`queryClient.clear()` on logout**, in addition to resetting the store and
   calling `window.location.replace()`.

### 7.4 Zustand — narrow scope, and one prohibition

A single `useAuthStore`: `user`, `tenant`, `accessToken` (in memory), `login()`,
`logout()`.

**The `persist` middleware is forbidden on this store.** `persist` writes to
`localStorage` — it would undo the "access token in memory only" decision in one
import and reopen the XSS exposure. It is exactly the trap this design avoids,
and it fits on one line.

### 7.5 One API client

Every call goes through `src/lib/apiClient.ts`, which centralises the base URL,
the bearer header, `credentials: 'include'`, the single retry after
`401 → /auth/refresh`, and the error-shape mapping. **No `fetch` inside a
component**: otherwise every view reinvents token handling, and one that forgets
is enough.

### 7.6 Component decomposition

| Rule | Check |
|---|---|
| A component either **fetches** or **renders**, never both | The container owns the hook, the presentational one takes props |
| A component over ~150 lines gets split | Review |
| Logic outgrowing the JSX moves to a hook (`useRecordEditor`) | Review |
| One component per file, named after it | Review |
| No `any` in TypeScript | `tsc` in CI |

Target decomposition for the heaviest screen (batch detail): `BatchDetailPage`
(container) → `UploadPanel`, `RecordFilters`, `RecordTable` → `RecordRow` →
`FieldErrorList`, `ConfidenceBadge`, `BatchSummaryPanel`.

---

## 8. Tests

| Rule | Why |
|---|---|
| The domain is tested as **pure functions**, with no database and no HTTP | Fast, therefore actually run |
| **One record factory** with valid defaults | Otherwise twenty fields are repeated per test, and fewer tests get written |
| Assertions target error **codes**, never messages | Messages target humans and may change |
| No test touches the network | The provider is a double; this is what makes CI free |
| Real calls isolated behind `@pytest.mark.live` | Proves the integration without making the suite depend on a key |
| No coverage target | The CSV oracle and the cross-tenant matrix are the real goals |

---

## 9. Git

- **At least one commit per stage**, with an explicit message. The history is
  read by the reviewer; a single "initial commit" is a poor signal.
- Dependencies are **pinned** — CI on a clean runner plus floating versions
  means a red build one morning without anyone touching anything.

---

## 10. Language

Everything committed to this repository is written in **English**: code,
comments, docstrings, test names, error messages, configuration files and
documentation.
