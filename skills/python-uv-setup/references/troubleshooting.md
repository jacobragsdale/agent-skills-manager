# uv sync troubleshooting playbook

Match the error output against the signatures below, apply the fix, re-run
`uv sync`. Fixes must land in `pyproject.toml` or `.env.example` — never in
a shell script or a manual install.

**This file is meant to grow.** When you solve an error that isn't listed,
append an entry in this format (edit this file in the skills repo at
`~/Development/jacob-agent-skills/skills/python-uv-setup/references/troubleshooting.md`,
then remind the user to commit the skills repo):

```markdown
## <short name> — YYYY-MM-DD
**Signature:** `<distinctive line from the error output>`
**Cause:** <root cause, one or two sentences>
**Fix:** <the pyproject/.env.example change, as a code block>
```

---

## Undeclared build dependencies
**Signature:** `ModuleNotFoundError: No module named 'setuptools'` (or
`'Cython'`, `'numpy'`, `'wheel'`, `'pkg_resources'`) while building an sdist;
or `Failed to build <pkg>` with a traceback inside the package's `setup.py`.
**Cause:** Old package declares no `build-system.requires`; uv builds it in an
isolated env that lacks the tool it assumes.
**Fix:** Declare the missing build deps for that one package:

```toml
[tool.uv.extra-build-dependencies]
some-package = ["setuptools", "cython"]
```

Requires a recent uv (`uv self update` if the table is unrecognized). If the
package insists on importing project deps at build time (e.g. torch), fall
back to:

```toml
[tool.uv]
no-build-isolation-package = ["flash-attn"]
```

and make sure the dep it imports is in `[project] dependencies` — with
no-build-isolation the package builds against the project venv, so the dep
must be installed before it builds (uv handles ordering for locked deps, but
you may need `uv sync` twice on first setup; if so, note it in the README
troubleshooting section).

## Broken metadata on a legacy pinned package
**Signature:** resolution fails while "building" a package just to read its
metadata, and the build itself is what's broken.
**Cause:** uv must build old sdists to discover their dependencies.
**Fix:** Supply the metadata by hand so uv never builds it during resolution:

```toml
[[tool.uv.dependency-metadata]]
name = "legacy-pkg"
version = "1.2.3"
requires-dist = ["requests>=2"]
```

## Git dependency fails with SSL error
**Signature:** `SSL certificate problem: unable to get local issuer certificate`
or `server certificate verification failed` during a git clone step.
**Cause:** Corporate TLS interception / internal CA not in git's trust store.
**Fix (in order of preference):**
1. Switch the dependency to SSH — sidesteps TLS entirely:
   ```toml
   [tool.uv.sources]
   internal-pkg = { git = "ssh://git@git.internal.corp/team/internal-pkg.git", tag = "v1.4.0" }
   ```
2. Point git at the corporate CA bundle — add to `.env.example`:
   ```bash
   # Corporate CA bundle for cloning internal git remotes
   GIT_SSL_CAINFO=/path/to/corp-ca.pem
   ```
   (export before `uv sync`: `set -a; source .env; set +a`)

Do NOT set `http.sslVerify false`.

## uv itself hits SSL errors talking to an index
**Signature:** `invalid peer certificate: UnknownIssuer` (or similar rustls
error) fetching from PyPI or an internal index.
**Cause:** uv uses its own trust store by default; the corporate CA is only in
the system store.
**Fix:**

```toml
[tool.uv]
native-tls = true
```

If the CA isn't in the system store either, add
`SSL_CERT_FILE=/path/to/corp-ca.pem` to `.env.example`. Last resort only, and
flag it to the user as insecure: `UV_INSECURE_HOST=<host>`.

## Corporate proxy — timeouts / connection refused
**Signature:** `error sending request`, connect timeouts, or downloads that
hang on a machine that needs a proxy.
**Cause:** Proxy env vars not set (or not exported when running `uv sync`).
**Fix:** Add to `.env.example` and export before sync:

```bash
HTTP_PROXY=http://proxy.corp:8080
HTTPS_PROXY=http://proxy.corp:8080
NO_PROXY=localhost,127.0.0.1,.internal.corp
# Slow proxy? uv's default timeout can be too short:
UV_HTTP_TIMEOUT=120
```

## Private PyPI index — 401/403 or package not found
**Signature:** `401 Unauthorized` / `403 Forbidden` from an internal index, or
an internal package that "does not exist" because resolution only looked at
public PyPI.

> **TODO(jacob): fill in our private PyPI details** — index URL, how auth is
> issued (token? LDAP password? keyring backend?), and which packages must
> come from it. Until then, the shape of the fix:

```toml
[[tool.uv.index]]
name = "internal"
url = "https://TODO.pypi.internal.corp/simple/"

# Pin internal packages to the internal index so uv never asks public PyPI:
[tool.uv.sources]
internal-billing-client = { index = "internal" }
```

Credentials go in the environment, never in pyproject — add to `.env.example`:

```bash
# Auth for the internal PyPI index (name INTERNAL matches [[tool.uv.index]] name)
UV_INDEX_INTERNAL_USERNAME=TODO
UV_INDEX_INTERNAL_PASSWORD=TODO   # token goes here if token-based
```

## No 3.11-compatible version / wheel
**Signature:** `no version of <pkg> ... requires-python` conflicts, or only
wheels for newer/older Pythons.
**Cause:** Pinned version predates 3.11 support (or dropped it).
**Fix:** Loosen the pin and let uv pick a compatible release
(`uv add 'pkg>=X'`). If the repo pinned an ancient version deliberately,
surface it to the user instead of silently upgrading.
