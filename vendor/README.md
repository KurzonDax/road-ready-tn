# Vendored packages

The server uses the Python standard library plus the packages in this folder. They are committed here so an Instance starts with no `pip install` and no network. `python -m server` puts this folder on `sys.path` at start.

## waitress

- Version: **3.0.2**
- What it is: the WSGI server that `python -m server` runs. Pure Python, no dependencies.
- License: Zope Public License 2.1, in `waitress/LICENSE.txt`, with `waitress/COPYRIGHT.txt`.
- Source: the sdist `waitress-3.0.2.tar.gz` from PyPI, SHA-256 `682aaaf2af0c44ada4abfb70ded36393f0e307f4ab9456a215ce0020baefc31f`.
- Only `src/waitress/` from the sdist is copied, unchanged, plus the license and copyright files.

### Re-vendoring

Run these from the repo root, in a new empty folder for the download:

```sh
mkdir -p /tmp/waitress-dl && cd /tmp/waitress-dl
pip download --no-deps --no-binary :all: 'waitress>=3,<4'
sha256sum waitress-*.tar.gz          # record this below
tar xzf waitress-*.tar.gz
cd -
rm -rf vendor/waitress
cp -r /tmp/waitress-dl/waitress-*/src/waitress vendor/
cp /tmp/waitress-dl/waitress-*/LICENSE.txt /tmp/waitress-dl/waitress-*/COPYRIGHT.txt vendor/waitress/
python3 -m unittest tests/test_server.py
```

Then update the version and SHA-256 above, read the waitress changelog for changes to `trusted_proxy` and `trusted_proxy_headers`, and restart the Instance.
