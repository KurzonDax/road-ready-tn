# Python server options that need no image build

Research for [issue #4](https://github.com/KurzonDax/road-ready-tn/issues/4), part of the
[self-hosted Instance map](https://github.com/KurzonDax/road-ready-tn/issues/2).

**Question.** Which Python server setups can run an Instance with accounts and server-side
progress without building a container image (a stock `python` image with the source mounted
in), and what are the trade-offs?

**Scope.** This file sets out options and trade-offs. It does not pick a stack; the server
stack ticket makes that decision. Deployment is described generically: an HTTPS reverse
proxy sits in front of the container, and nothing else is assumed about the host.

**Method.** All sources were read on **2026-10-15**. Facts marked **[checked]** were run
on this date against the stock images listed below. Facts marked **[docs]** come from
documentation only. Facts marked **[inference]** follow from cited facts but no source
states them directly.

Images checked (pulled 2026-10-15):

| Tag | Python | Base | libc | Digest |
|---|---|---|---|---|
| `python:3.13-alpine` | 3.13.16 | Alpine 3.24 | musl | `sha256:2d9aefe2fef0…` |
| `python:3.13-slim` | 3.13.16 | Debian 13 trixie | glibc 2.41 | `sha256:70729b46c69b…` |
| `python:3.14-alpine` | 3.14.8 | Alpine 3.24 | musl | `sha256:f6a589d43c42…` |
| `python:3.14-slim` | 3.14.8 | Debian 13 trixie | glibc 2.41 | `sha256:a2b82f3c4855…` |
| `python:3.15-alpine` | 3.15.0 | Alpine 3.24 | musl | `sha256:ff4d3c9b1a48…` |
| `python:3.15-slim` | 3.15.0 | Debian 13 trixie | glibc 2.41 | `sha256:f48fda6d59b2…` |

Note: docs.python.org/3/ now serves the 3.15 docs. Version-specific notes below say which
version they apply to.

---

## 1. What the standard library in the stock images offers

### Results from running the images [checked]

| | alpine (3.13 / 3.14 / 3.15) | slim (3.13 / 3.14 / 3.15) |
|---|---|---|
| OpenSSL | 3.5.9 | 3.5.7 |
| `hashlib.scrypt` | present, works (n=2^14, r=8, p=1) | present, works |
| `hashlib.pbkdf2_hmac` | present | present |
| `secrets` (`token_urlsafe`, `compare_digest`) | present | present |
| `sqlite3.sqlite_version` | 3.53.4 | 3.46.1 |
| `PRAGMA journal_mode=wal` | returns `wal`; `-wal` and `-shm` files created | same |
| SQLite threading | `THREADSAFE=1` (serialized) | `THREADSAFE=1` |
| `http.server.ThreadingHTTPServer` | present | present |
| `wsgiref.simple_server` | imports | imports |
| `pip` | 26.2.1 | 26.2.1 |
| `curl` / `wget` | no curl; `wget` at `/usr/bin/wget` (BusyBox) | neither |
| Default user | root (uid 0) | root (uid 0) |

The check script is a plain stdlib script run with
`docker run --rm -v ./check.py:/check.py:ro python:<tag> python /check.py`.

### Where these come from

- **OpenSSL and SQLite come from the distro packages, not from Python.** The official
  Dockerfiles build CPython against `libssl-dev` and `libsqlite3-dev` (slim, Debian) or
  `openssl-dev` and `sqlite-dev` (alpine). They configure with
  `--enable-loadable-sqlite-extensions` and `--with-ensurepip`.
  - https://github.com/docker-library/python/blob/master/3.15/slim-trixie/Dockerfile
  - https://github.com/docker-library/python/blob/master/3.15/alpine3.24/Dockerfile

  This is why the SQLite versions differ by variant. They will change when the base distro
  updates. **[docs + checked]**
- `hashlib.scrypt` implements "scrypt password-based key derivation function as defined in
  RFC 7914". It was added in 3.6. The docs note "*maxmem* limits memory (OpenSSL 1.1.0
  defaults to 32 MiB)". The 3.15 page has no Availability line for scrypt. It is provided by
  the linked OpenSSL, and both variants' OpenSSL builds provide it **[checked]**.
  https://docs.python.org/3/library/hashlib.html
- `hashlib.pbkdf2_hmac` is "only available when Python is compiled with OpenSSL". Since 3.12
  "the slow pure Python implementation has been removed". The docs suggest "hundreds of
  thousands of iterations of SHA-256" (as of 2022), with an example using 500_000.
  https://docs.python.org/3/library/hashlib.html
- `secrets` is "used for generating cryptographically strong random numbers suitable for
  managing data such as passwords, account authentication, security tokens". It provides
  `token_bytes`, `token_hex` and `token_urlsafe`. `compare_digest` is a "constant-time
  compare". The docs say "32 bytes (256 bits) of randomness is sufficient for the typical
  use-case". `DEFAULT_ENTROPY` "is subject to change", so pass `nbytes` explicitly.
  https://docs.python.org/3/library/secrets.html
- `sqlite3`: `sqlite_version` is the runtime library's version. `connect()` timeout
  defaults to 5.0 s. `check_same_thread=True` by default; with `False`, "write operations
  may need to be serialized by the user". `autocommit` was added in 3.12. It currently
  defaults to `LEGACY_TRANSACTION_CONTROL`, and `False` "is the recommended value".
  `Connection.backup` "works even if the database is being accessed by other clients".
  https://docs.python.org/3/library/sqlite3.html
- SQLite WAL: "All processes using a database must be on the same host computer; WAL does
  not work over a network filesystem". `PRAGMA journal_mode=WAL` is persistent.
  https://www.sqlite.org/wal.html

### What the Python docs say about `http.server` and `wsgiref` in production [docs]

- `http.server`: "**`http.server` is not recommended for production. It only implements
  basic security checks.**" The security section says three things:
  - `SimpleHTTPRequestHandler` follows symlinks out of the served directory.
  - `send_header()` and `send_response_only()` "do not perform input validation such as
    checking for the presence of CRLF sequences" (header injection).
  - Control characters in logs are scrubbed only since 3.12.

  `ThreadingHTTPServer` (3.7+) is "useful to handle web browsers pre-opening sockets, on
  which `HTTPServer` would wait indefinitely".
  https://docs.python.org/3/library/http.server.html
- `wsgiref`: "`wsgiref` is a reference implementation and is not recommended for production.
  The module only implements basic security checks." https://docs.python.org/3/library/wsgiref.html

**Trade-off.** A stdlib-only server needs zero third-party code and zero install step. The
cost is that the Instance would run on a server its own docs call unsuitable for
production. The HTTPS proxy in front reduces some exposure (TLS, slow clients) but does not
change that statement. Routing, request parsing, cookies, CSRF and form handling would all
be hand-written.

---

## 2. Using third-party packages without an image build

### Wheel portability: the deciding constraint [docs + checked]

- A `py3-none-any` wheel installs anywhere. Compiled wheels carry a platform tag:
  `manylinux_x_y` for glibc and `musllinux_x_y` for musl. Alpine "cannot use the existing
  `manylinux` platform tags".
  - https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/
  - https://peps.python.org/pep-0656/
- A wheel's `Root-Is-Purelib` field says whether it is pure Python.
  https://packaging.python.org/en/latest/specifications/binary-distribution-format/
- **[checked]** `pip install --target /pkgs flask` on `python:3.14-alpine` pulled
  `markupsafe-3.0.4-cp314-cp314-musllinux_1_2_x86_64.whl`. That wheel has
  `Root-Is-Purelib: false` and ships `_speedups.cpython-314-x86_64-linux-musl.so`.
  - The same folder, mounted into `python:3.14-slim` (glibc), still imported Flask.
    MarkupSafe silently fell back to its pure-Python `markupsafe._native`.
  - On alpine it used `markupsafe._speedups`.
  - The fallback is a `try: from ._speedups … except ImportError: from ._native …` in
    MarkupSafe's source:
    https://github.com/pallets/markupsafe/blob/main/src/markupsafe/__init__.py
  - MarkupSafe 3.0.4 publishes **no** `py3-none-any` wheel, only platform wheels and an
    sdist. https://pypi.org/pypi/MarkupSafe/3.0.4/json
  - **[inference]** An installed package folder is tied to one Python minor version, libc
    and CPU architecture whenever any package in it has compiled parts. Packages with a
    pure fallback still work elsewhere, just without the speedup.
- Docker Hub notes:
  - On slim, "`pip install` may fail when installing a Python distribution package from a
    source distribution". There is no compiler.
  - Alpine "does use musl libc instead of glibc".

  https://hub.docker.com/_/python (source text:
  https://github.com/docker-library/docs/blob/master/python/README.md)

### Option A: vendor pure-Python packages into the repo

How it works: commit the packages' source under, for example, `vendor/`. Put it on
`sys.path` with `PYTHONPATH` or a `sys.path.insert` at startup.

- `PYTHONPATH` "augment[s] the default search path". `python -I` (isolated mode) ignores
  `PYTHONPATH`. https://docs.python.org/3/using/cmdline.html
- `sys.path` is "free to modify". https://docs.python.org/3/library/sys.html
- `.pth` files are processed only in site directories or via `site.addsitedir()`.
  - In 3.15, `.pth` lines starting with `import` are deprecated, and 3.15 adds `.start`
    files. This does not apply to 3.13 or 3.14.
  - https://docs.python.org/3/library/site.html
- pip's own vendoring policy makes a useful yardstick. Vendored libs "MUST function without
  any build steps such as `2to3` or compilation of C code". They must be released PyPI
  copies, with their LICENSE files kept.
  https://pip.pypa.io/en/stable/development/vendoring-policy/
- Licences of likely candidates all require keeping the notice. So the vendored copy must
  carry each project's LICENSE file.
  - Bottle (MIT): https://github.com/bottlepy/bottle/blob/master/LICENSE
  - Flask (BSD-3-Clause): https://github.com/pallets/flask/blob/main/LICENSE.txt
  - waitress (ZPL 2.1): https://github.com/Pylons/waitress/blob/main/LICENSE.txt

Trade-offs:

- (+) No network at start and no install step. The deployed code is exactly what is in git,
  and the source can be mounted read-only.
- (+) Works the same on alpine and slim if every vendored package is pure Python.
- (−) Security updates are manual: someone has to notice a release and re-vendor it.
- (−) The repo grows, and third-party code shows up in diffs and code search.
- (−) Only pure-Python packages are safe to vendor. Those with optional C speedups must be
  vendored as their pure source; see MarkupSafe above.
- (−) The licence notices must be kept.

### Option B: `pip install --target` into a mounted folder at container start

How it works: the container command first runs
`python -m pip install --target /deps -r requirements.txt`, then starts the app with
`PYTHONPATH=/deps`. **[checked]** As uid 1000 on `python:3.14-alpine`, this installed
bottle 0.13.4 and waitress 3.0.2 into a bind-mounted folder, and they imported fine.

Relevant pip options (https://pip.pypa.io/en/stable/cli/pip_install/, pip 26.2.1):

- `--target`: "By default this will not replace existing files/folders"; replacing needs
  `--upgrade`.
- `--require-hashes`.
- `--only-binary :all:`.
- `--no-deps`.
- `--constraint`.
- `--no-index` with `--find-links`.
- `--root-user-action [warn, ignore]`.

Hash-checking mode (https://pip.pypa.io/en/stable/topics/secure-installs/):

- Requirements must be pinned with `==`, and "Hashes are required for *all* dependencies".
- Local hashes in requirements.txt protect "against remote tampering and network issues".
- The page recommends `--only-binary :all:`.

Running as root: pip warns that "Running pip as the 'root' user can result in broken
permissions…". The stock images run as root unless told otherwise.
https://github.com/pypa/pip/blob/main/src/pip/_internal/utils/misc.py

Settings can be given as `PIP_<UPPER_LONG_NAME>` env vars.
https://pip.pypa.io/en/stable/topics/configuration/

The cache defaults to `~/.cache/pip` and respects `XDG_CACHE_HOME`.
https://pip.pypa.io/en/stable/topics/caching/

Trade-offs:

- (+) Third-party code stays out of the repo, and updating is a one-line pin change.
- (+) pip picks the right wheel for the running image, so compiled speedups work.
- (−) Every cold start needs network access and PyPI to be up. An install that fails means
  the Instance does not start. **[inference]**
- (−) It is reproducible only with exact pins plus hashes. Without hashes, a compromised
  index or mirror could change the code that runs (secure-installs page).
- (−) Startup is slower. The `/deps` folder must be writable by the container user, so the
  install target cannot share a read-only mount with the source.
- (−) The `/deps` folder is tied to the image's Python version, libc and architecture.
  Changing the image tag needs a clean reinstall. **[inference from the wheel tags above]**
- (−) pip running as root unless the container runs as non-root.

### Other options

- **Commit wheels and install offline.**
  - Download with `pip download -r requirements.txt -d wheels/`.
  - Install at start with `pip install --no-index --find-links=wheels/ -r requirements.txt`
    ("install from local packages only, with no traffic to PyPI").
  - Cross-platform downloads need `--only-binary=:all:` or `--no-deps` together with
    `--platform` and `--python-version`.
  - https://pip.pypa.io/en/stable/user_guide/ and
    https://pip.pypa.io/en/stable/cli/pip_download/
  - Trade-off: no network at start, but binary wheels in git. Compiled wheels are needed
    per libc, Python version and arch, while pure ones are not.
- **zipapp.** Install the dependencies with `--target` into the app dir, then run
  `python -m zipapp`. A C extension "cannot be run from a zip file (this is an OS
  limitation…)". https://docs.python.org/3/library/zipapp.html
  - Trade-off: a single artefact, but it is a build step and limited to pure Python.
    Extension modules can't load from zip
    (https://docs.python.org/3/using/cmdline.html).
- **A venv in a mounted volume.** Venvs are "not considered as movable or copyable".
  Shebangs hold absolute interpreter paths, so "environments are inherently non-portable".
  https://docs.python.org/3/library/venv.html
  - Trade-off: same start-time install as option B, plus being tied to one image's
    interpreter path. Rebuild it on any image change.
- **Named volume for pip's cache** with option B. This cuts repeat downloads but does not
  remove the dependency on the network or PyPI for a first or changed install.
  **[inference]**
- **Stdlib only.** See question 1. No third-party code at all.

---

## 3. Small pure-Python frameworks and servers

PyPI data was read on 2026-10-15. "Pure" means a `py3-none-any` (or `py2.py3-none-any`)
wheel is published.

| Package | Version (date) | Pure? | Required deps | Kind | Licence |
|---|---|---|---|---|---|
| [Bottle](https://pypi.org/project/bottle/) | 0.13.4 (2025-06-15) | yes | none | WSGI framework | MIT |
| [Flask](https://pypi.org/project/Flask/) | 3.1.3 (2026-02-19) | yes | Werkzeug, Jinja2, MarkupSafe, itsdangerous, click, blinker | WSGI framework | BSD-3-Clause |
| [Werkzeug](https://pypi.org/project/Werkzeug/) | 3.1.9 (2026-09-27) | yes | MarkupSafe | WSGI toolkit | BSD-3-Clause |
| [MarkupSafe](https://pypi.org/project/MarkupSafe/) | 3.0.4 | **no pure wheel**; pure fallback in source | none | escaping | BSD-3-Clause |
| [Falcon](https://pypi.org/project/falcon/) | 4.4.0 (2026-09-30) | yes, plus optional Cython wheels | none | WSGI and ASGI framework | Apache-2.0 |
| [Starlette](https://pypi.org/project/starlette/) | 1.8.0 (2026-10-13) | yes | anyio (which needs idna) | ASGI framework | BSD-3-Clause |
| [waitress](https://pypi.org/project/waitress/) | 3.0.2 (2024-11-16) | yes | stdlib only | WSGI server | ZPL 2.1 |
| [gunicorn](https://pypi.org/project/gunicorn/) | 26.2.0 (2026-08-24) | yes | none | WSGI server, UNIX only | MIT |
| [uvicorn](https://pypi.org/project/uvicorn/) | 0.54.0 (2026-09-25) | yes (plain install) | click, h11 | ASGI server | BSD-3-Clause |
| [hypercorn](https://pypi.org/project/hypercorn/) | 0.18.0 | not checked | h11, h2, priority, wsproto | ASGI server | MIT |

Combinations that are pure Python end to end (vendorable on either variant):

- Bottle + waitress: no dependencies at all.
- Bottle or Falcon + gunicorn.
- Starlette + uvicorn (plain): anyio, idna, click and h11.
- Flask + waitress or gunicorn, with MarkupSafe running in its pure fallback.

`uvicorn[standard]` adds Cython-based uvloop and httptools. Falcon's Cython build is
optional; "pip will pick a pure-Python wheel" when no binary matches.

### Behaviour behind an HTTPS reverse proxy [docs]

The proxy terminates TLS. The app then sees plain HTTP from the proxy's address and must be
told which forwarded headers to trust. This matters for secure cookies, redirects and
client-address logging.

- **waitress**: `trusted_proxy` (the proxy's IP, or `*`), `trusted_proxy_count`
  (default 1), `trusted_proxy_headers`, and `clear_untrusted_proxy_headers` (default
  True). `url_scheme` is overridden by `X-Forwarded-Proto` "only if the client address
  matches `trusted_proxy`". The default is 4 threads. It can listen on a Unix socket.
  - https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html
  - https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html
- **gunicorn**: `forwarded_allow_ips` defaults to `127.0.0.1,::1`.
  - **[inference]** In a container network the proxy isn't loopback, so forwarded headers
    are ignored until this is set.
  - `secure_scheme_headers` includes `X-FORWARDED-PROTO: https`.
  - The docs "strongly recommend running Gunicorn behind a proxy server" that buffers slow
    clients, "otherwise Gunicorn becomes vulnerable to denial-of-service attacks".
  - A wildcard `forwarded_allow_ips` "is **dangerous** if untrusted clients can reach
    Gunicorn directly".
  - The worker heartbeat writes to `worker_tmp_dir`. The FAQ suggests a tmpfs.
  - Sources:
    - https://gunicorn.org/reference/settings/
    - https://gunicorn.org/deploy/
    - https://gunicorn.org/faq/
- **uvicorn**: `--proxy-headers` is on by default but trusts only `--forwarded-allow-ips`
  (default `127.0.0.1,::1`, or the `FORWARDED_ALLOW_IPS` env var). "Only trust clients you
  can actually trust!"
  - https://uvicorn.dev/settings/
  - https://uvicorn.dev/deployment/
- **Werkzeug `ProxyFix`** (for Flask): `ProxyFix(app, x_for=1, x_proto=1, …)` sets
  `REMOTE_ADDR` and `wsgi.url_scheme` from `X-Forwarded-*`. Use it "only … if the
  application is actually behind a proxy", with the count of proxies; "It can be a security
  issue if you get this configuration wrong."
  - https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/
  - https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/
- **Flask dev server**: "Do not use the development server when deploying to production."
  https://flask.palletsprojects.com/en/stable/deploying/
- **Bottle**: its built-in server is "a very simple non-threading HTTP server", fine for
  development. Bottle ships adapters for waitress and gunicorn. `remote_route` "can be
  forged by malicious clients". No trusted-proxy setting was found in its docs.
  - https://bottlepy.org/docs/0.13/deployment.html
  - https://bottlepy.org/docs/0.13/api.html
- **Starlette**: it has no proxy-headers middleware of its own and points to uvicorn's. It
  provides `TrustedHostMiddleware` and `HTTPSRedirectMiddleware`.
  https://starlette.dev/middleware/
- **Falcon**: its access route headers "can be forged… Do not rely on the access route to
  authorize requests".
  https://falcon.readthedocs.io/en/stable/api/request_and_response_wsgi.html

**[inference]** Any of the servers above is usable behind an HTTPS proxy. waitress, gunicorn
and uvicorn have explicit, documented trusted-proxy settings. The frameworks themselves
(Bottle, Falcon) leave proxy trust to the server or to a middleware.

---

## 4. Non-root user, health checks, and a mounted SQLite folder

### Non-root

- The official Dockerfiles define **no `USER`, no app user and no `HEALTHCHECK`**.
  **[checked]** `docker image inspect` shows `User` is empty and `Healthcheck` is nil for
  all six tags. The images do contain a `nobody` user (uid 65534).
  https://github.com/docker-library/python
- Compose `user:` "overrides the user used to run the container process… If it's not set,
  then `root`." `docker run --user` takes `<name|uid>[:<group|gid>]`.
  - https://docs.docker.com/reference/compose-file/services/
  - https://docs.docker.com/reference/cli/docker/container/run/
- Docker's security docs favour running "as non-privileged users inside the container".
  https://docs.docker.com/engine/security/
- **[inference]** With no named app user in the image, a numeric `uid:gid` is the practical
  setting. It should match the owner of the host data folder. `HOME` is `/` for an unknown
  uid **[checked]**, so anything that writes under `~`, such as pip's cache, needs
  `HOME`/`XDG_CACHE_HOME` set or caching turned off.

### File permissions on a mounted SQLite folder [checked + docs]

- Bind-mounted files keep their host numeric owner. **[checked]**
  - As `--user 1000:1000` on a folder owned by uid 1000: WAL mode worked, and `app.db`,
    `app.db-wal` and `app.db-shm` were created.
  - As `--user 65534:65534` on the same folder: creating a new database failed with
    `unable to open database file`. Writing to the existing one failed with
    `attempt to write a readonly database`.
- The docs pages for bind mounts and volumes do not state UID mapping. They do state:
  - Bind mounts are read-write by default; use `:ro` or `readonly`.
  - `-v` creates a missing host path.
  - A new, empty *named volume* is pre-filled from the image path.
  - https://docs.docker.com/engine/storage/bind-mounts/
  - https://docs.docker.com/engine/storage/volumes/
- SQLite puts the rollback journal, `-wal` and `-shm` "in the same directory as the
  database file". https://www.sqlite.org/tempfiles.html

  The opening process needs write access to `-shm`, "or else write access on the directory".
  https://www.sqlite.org/wal.html

  **[inference]** Mount a data *directory* writable by the container's uid, not a single
  `.db` file. Keep it separate from the source mount, so the source can stay `:ro`.
- Keep the database off network filesystems.
  - "WAL does not work over a network filesystem". https://www.sqlite.org/wal.html
  - Network file locking is a known corruption cause.
    https://www.sqlite.org/howtocorrupt.html §2.1
  - A database open under two different paths is undefined behaviour (§2.6).
  - Backups that copy the file mid-transaction can be corrupt (§1.2). Use the backup API
    (`Connection.backup`) or `VACUUM INTO`.
- A read-only source mount with Python bytecode: if `__pycache__` can't be written, "the
  import will still succeed". https://peps.python.org/pep-3147/

  `PYTHONDONTWRITEBYTECODE` or `PYTHONPYCACHEPREFIX` keep `.pyc` files out of the source
  tree. https://docs.python.org/3/using/cmdline.html

### Health checks

- Compose `healthcheck:` takes `test`, `interval`, `timeout`, `retries`, `start_period`,
  `start_interval` and `disable`. Its defaults match Dockerfile `HEALTHCHECK`: interval
  30s, timeout 30s, retries 3, start-period 0s, start-interval 5s. Exit 0 means healthy and
  1 means unhealthy.
  - https://docs.docker.com/reference/compose-file/services/
  - https://docs.docker.com/reference/dockerfile/
- No curl in either variant, and no wget in slim **[checked]**. A check that works on both is
  a `python -c` one-liner using `urllib.request.urlopen(url, timeout=…)`. It raises on
  connection errors and on HTTP error statuses, and an uncaught exception exits with
  status 1. https://docs.python.org/3/library/urllib.request.html
- **[checked]** On `python:3.14-alpine` running as uid 1000, this check reported `healthy`
  (exit 0) against a running server:
  `--health-cmd 'python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(\"http://127.0.0.1:8000/\", timeout=3).status==200 else 1)"'`
- Each check starts a fresh Python interpreter, which costs more than a `wget` call. On
  alpine, BusyBox `wget` is an option. **[inference]**

### Other Compose hardening keys [docs]

All from https://docs.docker.com/reference/compose-file/services/:

- `read_only: true`.
- `tmpfs` (with a `uid` option), for writable `/tmp` or gunicorn's worker temp dir.
- `cap_drop: [ALL]`.
- `security_opt: [no-new-privileges:true]`.
- `init: true`, which forwards signals and reaps processes.
- `stop_grace_period`, default 10s.

**[inference]** Under `read_only`, every path the app writes must be a mount or a tmpfs:
the data dir, a pip `--target` dir, caches, and `/tmp`.

---

## Summary of options (no recommendation)

| Approach | Third-party code | Network at start | Works the same on alpine and slim | Main risk |
|---|---|---|---|---|
| Stdlib only (`http.server` or `wsgiref`) | none | no | yes | Python docs: "not recommended for production"; all web plumbing is hand-written |
| Vendored pure-Python packages | in repo | no | yes, if all pure | manual security updates; licence notices |
| `pip install --target` at start | not in repo | yes | yes (pip picks wheels) | PyPI or network outage blocks start; needs pins and hashes; writable deps dir |
| Committed wheels + `--no-index` | wheels in repo | no | only for pure wheels | binary blobs in git; per-platform wheels for compiled packages |

## Not confirmed from a primary source

- Docker's docs do not state how bind-mount UID/GID ownership maps. The behaviour above was
  observed directly, not read.
- Hypercorn's wheel tag and transitive dependencies were not checked.
- That BusyBox provides alpine's `wget` is inferred from the alpine image description. Its
  presence at `/usr/bin/wget` was checked.
