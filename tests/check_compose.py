#!/usr/bin/env python3
"""Check that compose.yaml still runs the Instance the way docs/self-hosting.md describes.

It reads compose.yaml line by line with regular expressions, so it needs no YAML
library. It confirms the image, that the repo is mounted read-only, the non-root
`user:`, that the port is published on loopback only, and the health check.

Usage:
    python3 tests/check_compose.py [path/to/compose.yaml]
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Each check: what it confirms, and a pattern that some line of compose.yaml must match.
REQUIRED = [
    ("the image is python:3.14-slim", r"image:\s*[\"']?python:3\.14-slim[\"']?"),
    ("the server runs as python -m server", r"command:\s*python -m server"),
    ("the working directory is /app", r"working_dir:\s*/app"),
    ("the repo is mounted read-only at /app", r"-\s*[\"']?\.:/app:ro[\"']?"),
    ("the Instance folder is mounted at /var/lib/rrtn",
     r"-\s*[\"']?\$\{RRTN_HOST_DIR:-\./instance\}:/var/lib/rrtn[\"']?"),
    ("the container runs as RRTN_UID:RRTN_GID, not root",
     r"user:\s*[\"']\$\{RRTN_UID:-1000\}:\$\{RRTN_GID:-1000\}[\"']"),
    ("settings come from .env", r"env_file:\s*\.env"),
    ("the port is published on 127.0.0.1 only",
     r"-\s*[\"']127\.0\.0\.1:\$\{RRTN_PORT:-8080\}:\$\{RRTN_PORT:-8080\}[\"']"),
    ("the health check calls /healthz on 127.0.0.1 with python -c and urllib",
     r"test:.*\bpython\b.*-c.*urllib.*http://127\.0\.0\.1:\$\{RRTN_PORT:-8080\}/healthz"),
    ("the health check runs every 30s", r"interval:\s*30s"),
    ("the health check times out after 5s", r"timeout:\s*5s"),
    ("the health check retries 3 times", r"retries:\s*3\b"),
    ("the health check starts after 10s", r"start_period:\s*10s"),
    ("the container restarts unless stopped", r"restart:\s*unless-stopped"),
]


def problems(text):
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    found = [f"no line says {what}" for what, pattern in REQUIRED
             if not any(re.search(pattern, line) for line in lines)]
    # Under ports:, every published port must name 127.0.0.1, never all addresses.
    in_ports = False
    for line in lines:
        if re.match(r"\s*ports:\s*$", line):
            in_ports, indent = True, len(line) - len(line.lstrip())
            continue
        if in_ports:
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                in_ports = False
            elif re.match(r"\s*-\s*", line) and "127.0.0.1:" not in line:
                found.append(f"a port is published on every address: {line.strip()}")
    if "healthcheck:" not in text:
        found.append("there is no healthcheck:")
    if not re.search(r"^services:\s*$", text, re.M) or not re.search(r"^  app:\s*$", text, re.M):
        found.append("there is no service named app")
    return found


def main(argv):
    path = pathlib.Path(argv[1]) if len(argv) > 1 else ROOT / "compose.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"can't read {path}: {e}")
        return 1
    found = problems(text)
    if found:
        print(f"{path.name} does not match docs/self-hosting.md:")
        for p in found:
            print("  -", p)
        return 1
    print(f"{path.name} is as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
