# Audit principles

The numbered checklist every fastapi-audit finding must cite. Each entry:
the principle, why it matters, the FastAPI smell that violates it, the fix
direction, and the source. Groups: A contract & types (1–5),
B exception handling (6–9), C structure & testability (10–13),
D verification (14–15).

The unifying failure taxonomy — every API incident traces to one of:
(1) client got 200 but the operation failed → 2, 7; (2) client got an
error it couldn't parse or act on → 3, 6, 8; (3) client sent garbage that
got deep into the system → 4; (4) the contract changed and nobody noticed
→ 1, 5, 15; (5) the service fell over under load or at startup → 9, 12,
13.

## A. Contract & types

### 1. Every route declares its response type

The response model is the contract. Without one, FastAPI serializes
whatever the function returns — a renamed field, an extra ORM column, or
a leaked secret ships silently, and OpenAPI documents `{}`. A declared
model also *filters*: extra attributes on the returned object are
dropped, so an ORM `User` with `password_hash` cannot leak through a
`UserOut` response model.
**Smell:** `-> dict` or no return annotation and no `response_model=`;
returning SQLAlchemy/ORM objects raw; `JSONResponse(content=...)` built
by hand for normal success paths; one model reused for create-input,
update-input, and output.
**Fix:** a pydantic model per representation (`OrderIn`, `OrderOut`),
returned or declared via `response_model=`; `from_attributes=True` for
ORM sources; separate input/output models so server-set fields (id,
timestamps) are non-optional on output and absent on input.
**Source:** [FastAPI — Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).

### 2. Status codes are explicit, semantic, and declared

The status code is the one field every client branches on. FastAPI
defaults everything to 200, so an unconfigured POST-create, DELETE, or
async-accepted endpoint lies about what happened. Worse is the inverted
form: HTTP 200 carrying `{"success": false}` — monitoring, retries,
caches, and clients all read that as success.
**Smell:** POST that creates returning 200 with no `status_code=`;
DELETE returning 200 with a body instead of 204; 200 with an error
payload; 500 used for expected rejections; the same code for "not found"
and "not yours" when the distinction matters (or leaking existence when
it doesn't).
**Fix:** `status_code=status.HTTP_201_CREATED` / `204` / `202` stated on
the decorator; house mapping for rejections — 404 missing resource, 409
conflict/duplicate, 400 domain rule violated, 422 left to FastAPI's
request validation; every non-default status a route can emit listed in
its `responses={...}`.
**Source:** [FastAPI — Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/);
[Zalando RESTful API Guidelines — HTTP status codes](https://opensource.zalando.com/restful-api-guidelines/#http-status-codes-and-errors).

### 3. One error shape for the whole API

Clients can only handle errors they can parse. FastAPI already emits two
shapes out of the box (`{"detail": "..."}` from HTTPException,
`{"detail": [...]}` from validation), and every hand-rolled
`{"error": ...}` or `{"message": ...}` multiplies the parsing burden.
An error response is a contract like any other.
**Smell:** routes returning ad-hoc error dicts; exception handlers each
inventing their own JSON; `str(exc)` as the client-facing message
(internals leak); error bodies with no machine-readable code, only prose.
**Fix:** one error schema — RFC 9457 problem details
(`type`, `title`, `status`, `detail`, `instance`) or a house equivalent
with a stable machine-readable `code` — emitted *only* by exception
handlers, declared in `responses=` so it shows in OpenAPI.
**Source:** [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457);
[Zalando — Problem JSON](https://opensource.zalando.com/restful-api-guidelines/#176).

### 4. Parse, don't validate — at the request boundary

Same rule as etl-audit principle 13, and FastAPI makes it nearly free:
whatever the pydantic signature declares is parsed, rejected with a 422,
and documented before the function body runs. Every check done *inside*
the route or service instead is shotgun parsing — discovered late,
duplicated, undocumented.
**Smell:** `payload: dict` or `Any` body params; `await request.json()`
plus manual key checks; `if x < 0: raise` re-checks inside services;
`str` fields compared to magic strings where an `Enum` belongs; `float`
for money; optional-everything models where absence is actually illegal.
**Fix:** constrained request models — `Field(gt=0)`,
`Annotated[str, StringConstraints(...)]`, `Enum` for closed sets,
`Decimal` for money, required fields required; typed path/query params;
the core only ever sees parsed types.
**Source:** Alexis King, [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/);
[FastAPI — Body](https://fastapi.tiangolo.com/tutorial/body/).

### 5. OpenAPI descriptions are written for the client developer

The generated `/docs` is the API's front door and the only spec most
consumers will read. A route with no summary, fields with no
descriptions, and undocumented error responses force consumers to read
the source or guess — and guessing consumers file bugs against *your*
service.
**Smell:** decorators with no `summary=`/`description=` and functions
with no docstring; models whose fields carry no `description`/`examples`;
only the 200 response documented while the route can return 404/409;
routers without `tags`.
**Fix:** summary + description (docstring works) on every route, written
as *what the client achieves*, not what the code does; `Field(description=...,
examples=[...])` on non-obvious model fields; `responses={404: {"model":
Problem, "description": "..."}}` for every error status; one tag per
router.
**Source:** [FastAPI — Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).

## B. Exception handling

### 6. HTTP stays at the edge: services raise domain exceptions, handlers translate

`raise HTTPException(404)` inside a service welds business logic to the
transport: the service can't be reused from a worker or CLI, can't be
unit-tested without asserting HTTP semantics, and scatters status-code
policy across the call tree. The mapping domain-error → status code is
API policy and belongs in exactly one place.
**Smell:** `HTTPException` raised anywhere except a router or exception
handler; `from fastapi import ...` in service/repository/domain modules;
the same "not found" mapped to 404 in one route and 400 in another.
**Fix:** typed domain exceptions (`OrderNotFound`, `DuplicateSku`,
`InsufficientStock`) raised freely below the edge; one
`@app.exception_handler` per exception (or per base class) producing the
principle-3 shape; routers themselves raise HTTPException only for
transport-level concerns.
**Source:** [FastAPI — Handling Errors, custom exception handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/);
Percival & Gregory, [Architecture Patterns with Python](https://www.cosmicpython.com/book/part1.html).

### 7. Never swallow exceptions in routes; unexpected errors belong to one 500 handler

The API twin of etl-audit principle 1. Starlette already converts an
uncaught exception into a logged 500 — a broad `except Exception` around
a route body *defeats* that, turning crashes into fake 200s or
unstructured 500s and hiding the traceback. Per-route try/except also
guarantees the handling is inconsistent.
**Smell:** `try:` blanketing a whole route body; `except Exception:
return {"error": str(e)}` (fake success + internals leak);
`except Exception: logger.error(e); return None`; the same broad handler
catching `ConnectionError` and domain rejections alike.
**Fix:** catch only exceptions the route can *correct* (retry, fallback)
— everything else propagates; one app-level 500 handler logs with a
correlation id and returns the principle-3 shape with a generic message;
`str(exc)` never reaches the client on a 500.
**Source:** charlax, [Error handling antipatterns](https://github.com/charlax/professional-programming/blob/master/antipatterns/error-handling-antipatterns.md);
[Starlette — Exceptions & error handling](https://www.starlette.io/exceptions/).

### 8. Expected rejections are typed values, not None/bool/sentinel returns

Mirror of etl-audit principle 20. A service returning `None` for "not
found", `False` for "rule violated", and `-1` for "duplicate" forces
every caller to reverse-engineer meaning, and the route ends up choosing
status codes by guesswork. Each distinct rejection a client should
distinguish needs a distinct type carrying the offending values.
**Smell:** `Optional` returns where absence means failure, checked (or
not) at each call site; `raise ValueError("not found")` caught by string
matching; three different rejections all mapped to one bare 400.
**Fix:** one domain exception per rejection category (principle 6), each
carrying the data the error response needs (which sku, which limit);
alternatively a Result type at the service boundary — but pick one
convention service-wide. Where the "error" is better defined out of
existence (idempotent delete, empty list), do that instead.
**Source:** John Ousterhout, *A Philosophy of Software Design* (define
errors out of existence); [dry-python returns — Railway](https://returns.readthedocs.io/en/latest/pages/railway.html).

### 9. Fail at startup, not on request N

Missing config discovered on the first request is a live 500 in front of
a customer; discovered at boot it's a failed deploy the orchestrator
catches and rolls back. Startup is the moment someone is watching.
**Smell:** `os.getenv(...)` inside handlers or dependencies;
`or "localhost"` fallbacks on required settings; the DB first touched by
whichever request happens to arrive first; secrets parsed lazily.
**Fix:** `pydantic-settings` `BaseSettings` parsed once in the app
factory / lifespan — construction raises on missing or malformed values;
dependencies receive the settings object; optionally ping critical
backends in lifespan so a dead dependency fails the deploy.
**Source:** [FastAPI — Settings and Environment Variables](https://fastapi.tiangolo.com/advanced/settings/);
[FastAPI — Lifespan Events](https://fastapi.tiangolo.com/advanced/events/);
Jim Shore, [Fail Fast](https://martinfowler.com/ieeeSoftware/failFast.pdf).

## C. Structure & testability

### 10. Thin routers: parse → call one function → shape the response

A route function needs the whole HTTP machine to execute, so every
branch inside one is a branch you can only test through TestClient.
Business decisions belong in pure functions where they can be tested
exhaustively; the route declares the contract and delegates.
**Smell:** 50-line route bodies; `if`/`for` chains over rows inside the
route; queries composed inline in the route; the same rule re-implemented
in two routes because there was no shared function to call.
**Fix:** route body of a few lines — signature does the parsing
(principle 4), one service/core call does the work, the return value is
the response model. All conditional logic lives below, in functions
that take parsed values and return values.
**Source:** Gary Bernhardt, [Boundaries](https://www.destroyallsoftware.com/talks/boundaries);
Percival & Gregory (service layer).

### 11. Dependencies are injected seams — no module-level clients, no hidden inputs

`app.dependency_overrides` is FastAPI's built-in fake-injection point,
and it only sees what flows through `Depends`. A module-level
`httpx.Client`, engine, or session used directly is invisible to it —
tests then need `mock.patch` stacks coupled to import paths. Hidden
inputs (clock, uuid, env) inside logic are the same disease as
etl-audit principle 7: untestable, nondeterministic.
**Smell:** module-level `requests.Session()` / `create_engine(...)` /
`boto3.client(...)` used from routes or services; `datetime.now()` /
`uuid4()` inside business logic; `os.environ` read below the settings
boundary; tests with stacked `@mock.patch` asserting call signatures.
**Fix:** every I/O collaborator and every hidden input enters through
`Depends` (routes) or an explicit parameter (services/core): a
`get_session` dependency, a clock dependency or `as_of` parameter, ports
as `Protocol`s with hand-written fakes overridden in tests.
**Source:** [FastAPI — Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/);
Percival & Gregory, [ch. 3 on fakes vs mocks](https://www.cosmicpython.com/book/chapter_03_abstractions.html).

### 12. `async def` never blocks; `def` is a deliberate choice

One blocking call inside an `async def` route stalls the event loop —
*every* in-flight request waits, and the service that survived load
tests dies in production. Sync `def` routes are safe (threadpool) but
bounded; the choice between them is per-route and must match the I/O
style actually used inside.
**Smell:** `requests.get(...)`, `time.sleep(...)`, sync SQLAlchemy
sessions, or heavy CPU work inside `async def`; `async def` with no
`await` in the body; a codebase mixing sync and async DB access to the
same database.
**Fix:** async routes use async collaborators (`httpx.AsyncClient`,
async driver) end to end; routes whose collaborators are sync are
declared `def`; CPU-bound work goes to a worker/process pool. Pick one
DB access style per service.
**Source:** [FastAPI — Async](https://fastapi.tiangolo.com/async/).

### 13. App factory; importing the module does nothing

Mirror of etl-audit's module-side-effect rule. `app = FastAPI()` at
module top with routes registered and an engine created at import time
means the test suite connects to prod config the moment it imports, and
no two test configurations can coexist.
**Smell:** import-time `create_engine`/client construction; module-level
code mutating `app.state`; settings read at import; circular imports
worked around with mid-function imports (usually a symptom of routers
importing the app).
**Fix:** `create_app(settings: Settings) -> FastAPI` builds the app —
routers included, exception handlers registered, lifespan attached,
collaborators constructed inside; the ASGI entrypoint module is two
lines; tests call `create_app(test_settings)` per fixture.
**Source:** [Flask — Application Factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
(the pattern's origin; applies unchanged); Percival & Gregory
(composition root).

## D. Verification

### 14. Test each layer with its own tool

Mirror of etl-audit principle 21. Pure core: exhaustive unit tests, no
HTTP anywhere. Routes: contract tests through `TestClient`/`httpx.AsyncClient`
against a factory-built app with fakes via `dependency_overrides`,
asserting *status code and parsed response shape* — including one test
per declared error status (each mapped domain exception exercised
edge-to-edge). Adapters: a few real integration tests. The inversion —
everything tested through HTTP with mocked internals, no error-path
tests — is the smell.
**Smell:** only happy-path route tests; asserting `mock.assert_called_with`
instead of responses; error handlers that no test ever triggers; tests
that monkeypatch the service the route calls (testing the mock).
**Fix:** for every route: one contract test per declared status code;
core logic tested directly without the app; fakes are hand-written
implementations of the ports from principle 11.
**Source:** [FastAPI — Testing](https://fastapi.tiangolo.com/tutorial/testing/);
Bernhardt, Percival & Gregory (above).

### 15. The OpenAPI schema is under regression control

Every principle-1..5 property lands in the generated schema — which
means a snapshot of `app.openapi()` turns silent contract drift (field
renamed, status removed, model loosened) into a reviewable diff in the
PR. Without it, consumers discover breaking changes in production.
**Smell:** no schema snapshot or diff gate; "it's just a refactor"
PRs that change response models; consumers learning about changes from
incidents.
**Fix:** a test that dumps `app.openapi()` (sorted, stable) and compares
against a committed snapshot — intentional changes update the snapshot
in the same PR, visibly. Property-based conformance testing
(schemathesis) on top where the service is critical.
**Source:** [Schemathesis](https://schemathesis.readthedocs.io/) ;
[Zalando — API as a product / compatibility rules](https://opensource.zalando.com/restful-api-guidelines/#general-guidelines).
