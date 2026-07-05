# Keeping fake data in sync with reality

Static fixtures rot because nothing executes the link between the fixture
and the real schema. Every strategy here re-establishes that link so drift
becomes a red test instead of a silent lie. Every piece of fake external
data in a suite must use exactly one of these mechanisms — pick from the
decision table, apply the pattern, done.

## Decision table

| Faking...                       | Mechanism                                   |
|---------------------------------|---------------------------------------------|
| External API response           | 1. Model it in pydantic, build via factory  |
| Serialized payload that must live in a file | 2. Fixture-validation test      |
| A boundary you faked by hand (gateway, repo) | 3. Contract test               |
| Stored-proc / query result sets | 4. Shape contract (see dataframes-and-databases.md) |
| Large/gnarly expected output    | 5. Snapshots — opt-in, propose first        |
| Real third-party HTTP traffic   | 6. Recorded cassettes — opt-in, propose first |

## 1. Model + factory (default for API responses)

Never hand-write a dict that "looks like" the API's response. Model the
response with pydantic, parse the real response through the model in
production code, and build test instances from the model:

```python
# app/github.py — production code parses through the model
class RepoInfo(BaseModel):
    full_name: str
    stargazers_count: int
    archived: bool

# tests/test_ranking.py
from polyfactory.factories.pydantic_factory import ModelFactory

class RepoInfoFactory(ModelFactory[RepoInfo]):
    __model__ = RepoInfo

def test_archived_repos_are_excluded_from_ranking():
    repos = [RepoInfoFactory.build(archived=True),
             RepoInfoFactory.build(archived=False, stargazers_count=5)]

    ranked = rank(repos)

    assert all(not r.archived for r in ranked)
```

Why it can't drift: rename/remove a field on `RepoInfo` and every factory
call and override breaks at test time. Override ONLY the fields the test
cares about — the overrides document what the behavior depends on.

If the API itself changes shape, the pydantic model is the single place
that fails (production parse error), and fixing the model fixes the tests.

## 2. Fixture-validation test (when a file must exist)

Sometimes the file format is the point (parsing a vendor CSV, a sample
webhook payload). Then commit the file, but add the test that makes rot
impossible:

```python
FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.parametrize("path", sorted(FIXTURES.glob("webhook_*.json")), ids=lambda p: p.name)
def test_fixture_still_matches_schema(path):
    WebhookEvent.model_validate_json(path.read_text())
```

Corollary: generate the file FROM the model where possible
(`WebhookEvent(...).model_dump_json(indent=2)`) in a small checked-in
script, so regeneration after a schema change is one command. A fixture
file no test validates or reads is an orphan — `audit_tests.py` flags them.

## 3. Contract test for hand-written fakes

When you fake a boundary you own (an `InMemoryOrderRepo` standing in for
the real Oracle-backed one), write the behavior tests ONCE and run them
against both implementations. The fake cannot drift because the same
assertions exercise the real thing:

```python
@pytest.fixture(params=["fake", pytest.param("real", marks=pytest.mark.integration)])
def repo(request, oracle_conn):
    if request.param == "fake":
        return InMemoryOrderRepo()
    return OracleOrderRepo(oracle_conn)

def test_saved_order_is_retrievable_by_id(repo):
    order = OrderFactory.build()

    repo.save(order)

    assert repo.get(order.id) == order
```

Unit runs exercise the fake (fast, every commit); integration runs prove
the fake still behaves like Oracle. One fake per boundary — twenty ad-hoc
MagicMocks each encode a private guess about the API; one contract-tested
fake encodes a verified one.

## 4. Stored-proc result sets

Read `references/dataframes-and-databases.md` — the shape-contract pattern
against `cursor.description` lives there with the FakeCursor.

## 5. Snapshots (opt-in — propose to the user first)

For wide serialized output where hand-writing the expected value is
impractical. `syrupy` stores snapshots in files, `pytest --snapshot-update`
regenerates. The discipline that keeps snapshots honest: updates land only
via a reviewed diff — never update and commit blind. Snapshots are
regression detectors, not correctness proofs; pair every snapshot test with
a few hand-asserted values. Don't introduce without asking: it's a new
concept for the reader and a blind-approval trap.

## 6. Recorded HTTP cassettes (opt-in — propose to the user first)

`pytest-recording` (vcrpy) records real HTTP responses to cassette files;
the shape is real by construction. Sync strategy is routine re-recording:
`--record-mode=rewrite` against the sandbox API when the upstream versions,
plus a `before_record_response` hook to redact secrets. Prefer mechanism 1
(model + factory) as the default; cassettes earn their keep only when
responses are too large/varied to model by hand.
