# Audit principles

The numbered checklist every python-package-audit finding must cite. Each
entry: the principle, why it matters, the smell that violates it, the fix
direction, and the source (every URL verified live 2026-07-03). Groups:
A dependency declarations (1–5), B public interface (6–11), C handlers &
repositories (12–17), D verification (18–20).

The unifying failure taxonomy — every package incident traces to one of:
(1) a consumer's environment won't resolve or breaks on upgrade → 1–4;
(2) a consumer coupled to something that was never a promise → 6, 9, 15;
(3) the package broke its importers without warning → 10, 20;
(4) importing or configuring it did something surprising → 5, 8, 16;
(5) it can't be tested without real infrastructure → 12–18.

## A. Dependency declarations

### 1. Libraries declare ranges; applications lock. No pins, no blanket caps

Exact pins and speculative upper bounds in `[project.dependencies]`
propagate transitively: one library capping `flask<2` forces every
downstream app to that cap, blocks security fixes, and creates
unsolvable resolver conflicts. "Anyone can fix a missing cap, but users
cannot fix an over restrictive cap."
**Smell:** `requests==2.31.0` or `httpx<0.28` in a library's runtime
deps; Poetry `^`/`~=` majors added "just in case"; sub-dependencies
listed directly; a lockfile treated as the published contract.
**Fix:** `requests>=2.28` — cap only on a known, verified, documented
incompatibility, and remove the cap when it's fixed. Lockfiles are for
this repo's own dev/CI environments only.
**Source:** Henry Schreiner, [Should You Use Upper Bound Version Constraints?](https://iscinumpy.dev/post/bound-version-constraints/);
Hynek Schlawack, [Semantic Versioning Will Not Save You](https://hynek.me/articles/semver-will-not-save-you/);
[packaging.python.org — install_requires vs requirements files](https://packaging.python.org/en/latest/discussions/install-requires-vs-requirements/).

### 2. Lower bounds are honest and tested

`>=` is the legitimate constraint direction — but only if true. An
untested `>=1.0` that actually needs 2.3 features fails at runtime for
consumers on old pins; a needlessly new floor conflicts with their other
packages.
**Smell:** bare names with no lower bound; floors nobody has ever
installed; no CI job resolving to minimums.
**Fix:** declare the oldest version actually supported and prove it —
`uv pip install --resolution lowest-direct` (or a constraints file)
plus the test suite.
**Source:** Schreiner (above) — "tight lower limits are much better
than tight upper limits… test with a constraints.txt file that forces
your lower bounds."

### 3. Every dependency in its right box

Runtime deps are what every consumer must install — nothing else goes
there. Optional user-facing features go in `[project.optional-dependencies]`
(extras). Dev tooling goes in PEP 735 `[dependency-groups]` — excluded
from built distributions and installable without the package, which
extras can't do.
**Smell:** `pytest`/`ruff`/`mypy` in `[project].dependencies`; a `dev`
extra publishing tooling as public metadata; matplotlib mandatory when
plotting is one feature; `requirements-dev.txt` next to pyproject.toml.
**Fix:** minimal runtime deps; `plot = ["matplotlib>=3.7"]` extras with
a clear ImportError naming the extra; `[dependency-groups]` for test/
lint/docs, composed with `include-group`.
**Source:** [PEP 735](https://peps.python.org/pep-0735/);
[packaging.python.org — Dependency Groups](https://packaging.python.org/en/latest/specifications/dependency-groups/);
[Scientific Python Development Guide — packaging](https://learn.scientific-python.org/development/guides/packaging-simple/).

### 4. `requires-python` is a tested minimum, never capped; floors move on a policy

Installers use `requires-python` to back-solve older releases for old
runtimes — an upper cap breaks that mechanism and "always translates to
an error", even where the code works fine. Raising floors ad hoc is as
bad as never raising them: adopt a written window (SPEC 0: drop Python
3 years after release, core deps 2 years after).
**Smell:** missing `requires-python`; `>=3.10,<3.13`; a 2026 library
claiming `>=3.7`; floors raised silently in patch releases.
**Fix:** `requires-python = ">=3.11"` matching the oldest CI job;
document the support window; bump floors in minor releases with
changelog entries.
**Source:** [Scientific Python guide (PP004)](https://learn.scientific-python.org/development/guides/packaging-simple/);
Schreiner (above); [SPEC 0](https://scientific-python.org/specs/spec-0000/).

### 5. Dependencies are deliberate; heavy ones load lazily

Every direct dep lands on every consumer, transitively — supply-chain
surface, conflict surface, and import cost they didn't choose. "Before
adding a dependency, consider whether you need it at all."
**Smell:** `requests` for one GET; a dataframe library for one CSV;
nobody can name the transitive tree; multi-second `import yourlib`
because `__init__.py` eagerly imports the plotting subsystem.
**Fix:** justify each direct dep in review; inspect with `pipdeptree`,
scan with `pip-audit`; defer heavy/optional imports into the functions
that need them or use the SPEC 1 lazy-loading pattern.
**Source:** Bernát Gábor, [Python supply chain security](https://bernat.tech/posts/securing-python-supply-chain/);
[SPEC 1 — Lazy Loading](https://scientific-python.org/specs/spec-0001/).

## B. Public interface

### 6. The public surface is declared, not accidental

"Any backwards compatibility guarantees apply only to public
interfaces" — which only works if consumers can tell which is which.
Whatever is importable without an underscore is a promise someone will
depend on (Hyrum's law).
**Smell:** implementation helpers importable as `pkg.utils.helpers`;
no `__all__` anywhere; consumers found importing from modules you
considered private.
**Fix:** implementation lives in `_internal/` (or `_module.py`); the
intended names re-export from `__init__.py`; `__all__` declared in
every public module — under the SciPy convention, an underscored module
makes *all* its members private.
**Source:** [PEP 8 — Public and Internal Interfaces](https://peps.python.org/pep-0008/#public-and-internal-interfaces);
[SciPy API reference conventions](https://docs.scipy.org/doc/scipy/reference/index.html).

### 7. Ship type information: py.typed plus fully annotated public signatures

Without the PEP 561 marker, type checkers ignore every annotation in
the package — consumers get `Any` for everything, and the interface is
undeclared to their tooling.
**Smell:** annotated code but no `py.typed` file; public functions with
unannotated params or implicit-Any returns; the marker present while
half the surface is untyped (worse than absent — checkers now trust
the holes).
**Fix:** empty `py.typed` inside the package (in package data); every
public function, method, and attribute annotated; a type checker in CI
on the public surface.
**Source:** [PEP 561](https://peps.python.org/pep-0561/);
[typing spec — distributing type information](https://typing.python.org/en/latest/spec/distributing.html).

### 8. Importing is free: no side effects, no self-configuration, NullHandler only

Import-time work breaks testability, tooling, and multiprocessing
spawn, and steals decisions that belong to the application. The logging
docs are explicit: "do not add any handlers other than NullHandler to
your library's loggers… configuration of handlers is the prerogative of
the application developer."
**Smell:** module-level `load_config(os.environ[...])`, connections or
clients built at import; `logging.basicConfig()` anywhere in the
package; `print()` to a stdout the consumer owns.
**Fix:** defer work into functions/constructors or an explicit
`configure()`; loggers get `NullHandler` at most; stdout/stderr belong
to the caller.
**Source:** [Python Logging HOWTO — library configuration](https://docs.python.org/3/howto/logging.html#configuring-logging-for-a-library);
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) (import-time execution, mutable global state).

### 9. Exceptions are API: one package base, semantic subclasses, no leaks

A root exception lets callers catch everything you raise *on purpose*
with one except — "all other types of exceptions raised by your module
must be the ones that you didn't intend to raise. These are bugs." A
documented failure mode surfacing as `psycopg2.OperationalError` or
`KeyError` couples consumers to internals you meant to hide.
**Smell:** `raise RuntimeError("bad config")` / `raise Exception(...)`;
third-party exceptions escaping for expected failures; consumers
writing `except Exception` because there's nothing narrower to catch.
**Fix:** `class OrderlibError(Exception)` at top level, semantic
subclasses (`ConfigError`, `OrderNotFound`); at adapter boundaries wrap
expected third-party failures with `raise OrderlibError(...) from exc`.
**Source:** Slatkin, *Effective Python* — [define a root exception](https://github.com/SigmaQuan/Better-Python-59-Ways/blob/master/item_51_define_a_root_exception.py);
charlax, [error-handling antipatterns](https://github.com/charlax/professional-programming/blob/master/antipatterns/error-handling-antipatterns.md).

### 10. Versioning communicates; deprecation is a process

SemVer "can only help you determine whether the breakage is on purpose"
— what actually protects consumers is the warn → grace period → remove
pipeline with alternatives named. NEP 23's floor: `DeprecationWarning`
with the alternative and a `stacklevel` pointing at user code, never
introduced in a patch release, removal after ≥2 releases and ≥1 year.
**Smell:** behavior changed silently in a minor release; deprecation
and removal in the same release; warnings with no replacement named;
no written stability policy.
**Fix:** adopt the NEP 23-shaped policy sized to the package's blast
radius (internal packages may shorten the window — but write it down);
every deprecation in the changelog.
**Source:** [Hynek — Semantic Versioning Will Not Save You](https://hynek.me/articles/semver-will-not-save-you/);
[NEP 23 — backwards compatibility policy](https://numpy.org/neps/nep-0023-backwards-compatibility.html).

### 11. Deep modules; keyword-only options; no boolean traps

The interface is the cost consumers pay forever; the implementation can
churn behind it. A module is deep when its interface is far simpler
than what it does. And `f(data, True, False)` freezes argument order
into the compatibility contract while saying nothing at the call site.
**Smell:** shallow pass-through wrappers mirroring internal structure
1:1; three imports and four calls to do the package's one job; every
internal knob a parameter; positional boolean flags.
**Fix:** one obvious entry point per use case with sensible defaults;
bare-`*` keyword-only for everything optional
(`def connect(host, *, timeout=10, verify=True)`); enums over
behavior-switching booleans.
**Source:** Ousterhout, [*A Philosophy of Software Design*](https://web.stanford.edu/~ouster/cgi-bin/book.php) (deep modules);
[PEP 3102](https://peps.python.org/pep-3102/);
[Adam Johnson — the boolean trap](https://adamj.eu/tech/2021/07/10/python-type-hints-how-to-avoid-the-boolean-trap/).

## C. Handlers & repositories

### 12. Persistence behind a narrow, collection-like repository returning domain objects

The repository "hides the boring details of data access by pretending
that all of our data is in memory" — `add()`, `get()`, minimal listing,
returning domain objects, never rows/DTOs/sessions. The test: **the
fake must be a set/dict wrapper of one-liners.** "If it's hard to fake,
the abstraction is probably too complicated." One repository per
aggregate root — repositories returning child entities let invariants
be bypassed.
**Smell:** SQLAlchemy `Session`/query objects or SQL strings in
service code; `filter_by(**kwargs)` query-builder repos; a repository
per table; a fake that reimplements query logic to make tests pass.
**Fix:** shrink the port until the fake is trivial; expose only
aggregate-root repositories; ORM/SQL stays inside the concrete adapter.
**Source:** Percival & Gregory, [ch. 2 — Repository](https://www.cosmicpython.com/book/chapter_02_repository.html),
[ch. 7 — Aggregates](https://www.cosmicpython.com/book/chapter_07_aggregate.html).

### 13. Atomic operations go through a Unit of Work

The UoW is "our abstraction over the idea of atomic operations" and the
single entrypoint to storage: a context manager exposing repositories
and `commit()`; exiting on an exception rolls back.
**Smell:** `session.commit()` scattered through handlers; partial
writes surviving exceptions; handlers taking a raw `session` argument.
**Fix:** an abstract UoW context manager; handlers say
`with uow: ... uow.commit()`; a fake UoW records whether commit
happened.
**Source:** Percival & Gregory, [ch. 6 — Unit of Work](https://www.cosmicpython.com/book/chapter_06_uow.html).

### 14. Handlers orchestrate; business rules live in the domain; entrypoints stay thin

The service/handler layer does the boring sequence — fetch, check
preconditions, call domain, persist — "keeping it separate from
business logic helps keep things tidy," while too much logic there
"leads to the Anemic Domain antipattern." Entrypoints (HTTP/CLI) do
transport only, so use cases work from any adapter — API, CLI, or the
tests.
**Smell:** price calculations and invariant `if`s inside handler
functions; JSON parsing inside services; a use case exercisable only
through the web framework.
**Fix:** rules push down into entities/domain functions; handlers
compose them; entrypoints deserialize → call → serialize.
**Source:** Percival & Gregory, [ch. 4 — Service Layer](https://www.cosmicpython.com/book/chapter_04_service_layer.html).

### 15. Depend on abstractions: ports as Protocols, defined by the consumer

The domain and service layer never import infrastructure — "your ORM
should import your model, and not the other way around." In modern
Python the port is a `typing.Protocol` living next to the code that
*consumes* it: structural typing means adapters (even third-party
classes) satisfy it without importing or inheriting anything.
**Smell:** `from pkg.adapters import postgres_repo` inside domain or
service modules; model classes that only exist as ORM subclasses; a
central `interfaces.py` ABC every adapter must inherit; `isinstance`
checks as control flow.
**Fix:** `class OrderRepository(Protocol)` beside the service layer,
shaped by what the consumer needs, checked by the type checker.
**Source:** Percival & Gregory (ch. 2, 4 above);
Hynek, [Subclassing in Python Redux](https://hynek.me/articles/python-subclassing-redux/);
[mypy — Protocols](https://mypy.readthedocs.io/en/stable/protocols.html).

### 16. Explicit DI, one composition root, no self-configuration

Declaring dependencies implicitly by import and monkeypatching them in
tests "tightly couples us to the implementation." Dependencies enter as
constructor/function parameters typed as ports; one bootstrap module —
the composition root — builds real adapters for prod and is the only
place (besides tests) that reads config. Inner layers never read
`os.environ`: config is parsed once at the edge and passed down as
values.
**Smell:** module-level singletons built at import; adapters
instantiated deep inside business code; `os.environ["DB_HOST"]` in a
service module; behavior changing on env vars the caller never passed.
**Fix:** parameters + Protocols everywhere below the edge; a
`bootstrap.py`/`config.py` pair at the top; the caller owns the
environment.
**Source:** Percival & Gregory, [ch. 13 — Dependency Injection](https://www.cosmicpython.com/book/chapter_13_dependency_injection.html),
[appendix B — project structure](https://www.cosmicpython.com/book/appendix_project_structure.html);
[The Twelve-Factor App — Config](https://12factor.net/config).

### 17. Layering is enforced mechanically; cycles are an architecture signal

"Python has no formal way of declaring, and enforcing, a dependency
flow" — without a CI check, `domain → adapters` imports creep in
silently. import-linter contracts (layers, forbidden, independence,
acyclic siblings) make the architecture executable. Function-local
imports added to dodge `ImportError` are cycles papered over, not
solved.
**Smell:** layering that exists only in a README; deferred imports
inside functions hiding cycles; no `lint-imports` in CI.
**Fix:** a `[tool.importlinter]` layers contract (entrypoints →
services → domain; adapters may import domain, never the reverse), run
via `uvx --from import-linter lint-imports`; break cycles by extracting
shared code downward or depending on a Protocol.
**Source:** [import-linter docs](https://import-linter.readthedocs.io/en/stable/);
David Seddon, [Meet import-linter](https://seddonym.me/2019/05/20/meet-import-linter/).

## D. Verification

### 18. Fakes over mocks — and contract-test the fakes

"Mocking frameworks, particularly monkeypatching, are a code smell":
mock tests verify interactions, coupling tests to implementation. Use
hand-written fakes implementing the port and assert on resulting state.
An unverified fake drifts, so run the *same* contract suite against
fake and real: parametrized fixture yielding each implementation — fake
on every commit, real adapter in integration CI.
**Smell:** `mock.patch("pkg.adapters.email.send")` across the suite;
`assert_called_with` instead of outcomes; fake `get()` returning None
where the real one raises.
**Fix:** one shared contract test module per port, parametrized over
implementations.
**Source:** Percival & Gregory, [ch. 3 — On Coupling and Abstractions](https://www.cosmicpython.com/book/chapter_03_abstractions.html);
Turner-Trauring, [verified fakes](https://pythonspeed.com/articles/verified-fakes/).

### 19. Layer-match the test strategy

Exhaustive fast tests on the pure domain core; the bulk of tests
against the service layer edge-to-edge with fakes ("the place to
exhaustively cover all the edge cases"); a few integration tests
proving each real adapter honors its contract; one end-to-end test per
feature. The inverted pyramid — business edge cases exercised through
real infrastructure — is the smell.
**Smell:** logic untestable without Docker; slow suites; happy-path
E2E as the only coverage of domain rules.
**Source:** Bernhardt, [Boundaries](https://www.destroyallsoftware.com/talks/boundaries);
Percival & Gregory, [ch. 5 — High Gear, Low Gear](https://www.cosmicpython.com/book/chapter_05_high_gear_low_gear.html).

### 20. The public API is under regression control

Humans miss accidental breakage — a renamed parameter, a dropped
re-export. Griffe "compares two snapshots of your project to detect API
breakages": `uvx griffe check <pkg> -s <src> --against <tag>` exits 1
and lists every breakage. Run it in CI against the last release;
undeclared breakage fails the build.
**Smell:** no API diff gate; breaking changes discovered by importers'
bug reports; "it's just a refactor" PRs that moved public names.
**Fix:** griffe check in CI; intentional changes land with the
deprecation machinery from principle 10, visibly.
**Source:** [Griffe — checking for API breakages](https://mkdocstrings.github.io/griffe/guide/users/checking/).
