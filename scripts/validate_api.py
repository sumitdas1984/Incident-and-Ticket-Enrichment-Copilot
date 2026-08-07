"""Run Postman collections against a running Alarm API simulator via Newman.

This is the executable half of Story 2.2.1 (`make validate-api`). It is
intentionally a thin orchestrator: parsing flags, spawning Newman for
each collection, propagating the exit code, and writing HTML reports.
The Makefile handles simulator lifecycle and health-waiting; we just
talk to whatever is listening on --base-url.

Why Python (not bash / JS): the rest of the repo's tooling is Python,
we get cross-platform behaviour for free, and unit tests can patch
run_newman() to inspect argv without touching the real CLI.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def build_newman_argv(
    collection: Path,
    base_url: str,
    token: str,
    report_path: Path,
) -> list[str]:
    """Build the argv list for a single Newman invocation.

    Exposed so unit tests can assert what we'd actually call without
    spawning a process. `npx --no-install` keeps the local
    node_modules/.bin on PATH; if Newman isn't installed it fails
    loudly instead of silently installing.

    On Windows the first element is rewritten to the resolved
    `npx.cmd` (or `npx`) because Python's subprocess does not honour
    PATHEXT for `.cmd` / `.bat` shims, which is what npm installs by
    default on Windows.
    """
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError(
            "npx is not on PATH. Install Node.js (>=18) before running validate-api."
        )
    return [
        npx,
        "--no-install",
        "newman",
        "run",
        str(collection),
        "--env-var",
        f"baseUrl={base_url}",
        "--env-var",
        f"auth_token={token}",
        "--reporters",
        "cli,htmlextra",
        "--reporter-htmlextra-export",
        str(report_path),
    ]


def run_newman(argv: Sequence[str]) -> int:
    """Run a single Newman invocation, streaming stdout/stderr. Returns the exit code."""
    print(f"\n--> {' '.join(argv[:6])} ...\n", flush=True)
    # On Windows, .cmd / .bat shims require either shell=True or a
    # proper cmd.exe subprocess. shell=True with a list is unsafe (the
    # arg-joining rules vary), so we route through cmd.exe explicitly.
    if sys.platform == "win32" and argv[0].lower().endswith((".cmd", ".bat")):
        completed = subprocess.run(
            [str(x) for x in argv],
            check=False,
            shell=True,
        )
    else:
        completed = subprocess.run([str(x) for x in argv], check=False)
    return completed.returncode


def validate_one(
    collection: Path,
    base_url: str,
    token: str,
    report_dir: Path,
) -> int:
    """Run one collection through Newman. Returns 0 on success, non-zero on failure."""
    if not collection.exists():
        print(f"FAIL: collection not found: {collection}", file=sys.stderr)
        return 2

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{collection.stem}.html"
    argv = build_newman_argv(collection, base_url, token, report_path)
    exit_code = run_newman(argv)

    if exit_code == 0:
        print(f"\nPASS: {collection.name} ({report_path.name})")
    else:
        print(
            f"\nFAIL: {collection.name} -- Newman exit {exit_code}. Report: {report_path}",
            file=sys.stderr,
        )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Alarm API simulator via Postman/Newman")
    parser.add_argument(
        "--collection",
        type=Path,
        action="append",
        required=True,
        help="Path to a Postman collection JSON. Repeat for multiple collections.",
    )
    parser.add_argument("--base-url", required=True, help="e.g. http://localhost:8000")
    parser.add_argument("--token", required=True, help="bearer token the simulator expects")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("newman-report"),
        help="directory for HTML reports (gitignored, default: ./newman-report)",
    )
    args = parser.parse_args(argv)

    overall = 0
    for collection in args.collection:
        rc = validate_one(collection, args.base_url, args.token, args.report_dir)
        overall = rc if rc != 0 else overall

    if overall == 0:
        print("\nPASS: All collections passed.")
    else:
        print(f"\nFAIL: Validation failed (exit {overall}).", file=sys.stderr)
    return overall


if __name__ == "__main__":
    sys.exit(main())
