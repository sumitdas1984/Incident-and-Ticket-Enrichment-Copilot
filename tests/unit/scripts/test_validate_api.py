"""Tests for scripts/validate_api.py — the Newman orchestrator."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.validate_api import (
    build_newman_argv,
    main,
    run_newman,
    validate_one,
)


def test_build_newman_argv_includes_collection_and_env_vars() -> None:
    collection = Path("postman/chaining/Alarm-API-Chaining.postman_collection.json")
    report = Path("newman-report/chaining.html")
    argv = build_newman_argv(
        collection=collection,
        base_url="http://localhost:8123",
        token="demo-token",
        report_path=report,
    )
    # First arg is the resolved npx path (may be npx.cmd on Windows).
    assert argv[0].lower().endswith(("npx", "npx.cmd", "npx.exe"))
    assert argv[1] == "--no-install"
    assert argv[2] == "newman"
    assert argv[3] == "run"
    assert str(collection) in argv  # Path() stringifies with OS separator
    assert "baseUrl=http://localhost:8123" in argv
    assert "auth_token=demo-token" in argv
    assert "cli,htmlextra" in argv  # both reporters registered in one argv slot
    assert str(report) in argv


def test_build_newman_argv_raises_when_npx_missing(tmp_path: Path) -> None:
    """If Node.js + npx aren't installed, the error fires before any subprocess work."""
    with patch("scripts.validate_api.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="npx is not on PATH"):
            build_newman_argv(
                collection=tmp_path / "c.json",
                base_url="http://x",
                token="t",
                report_path=tmp_path / "r.html",
            )


def test_validate_one_passes_when_collection_missing(tmp_path: Path) -> None:
    """Missing collection → exit 2 (distinct from Newman's failure codes)."""
    rc = validate_one(
        collection=tmp_path / "does-not-exist.json",
        base_url="http://localhost:8000",
        token="demo-token",
        report_dir=tmp_path / "reports",
    )
    assert rc == 2


def test_run_newman_propagates_exit_code() -> None:
    """Whatever Newman exits with, we return — no special-casing of 0/1."""
    fake = type("C", (), {"returncode": 1})()
    with patch("scripts.validate_api.subprocess.run", return_value=fake):
        assert run_newman(["newman", "run", "x"]) == 1


def test_validate_one_returns_zero_on_newman_success(tmp_path: Path) -> None:
    """When Newman exits 0, validate_one returns 0 and creates the report dir."""
    coll = tmp_path / "c.json"
    coll.write_text("{}")
    with patch("scripts.validate_api.run_newman", return_value=0):
        rc = validate_one(coll, "http://x", "t", tmp_path / "reports")
    assert rc == 0
    # The report dir is created up-front; Newman writes the .html itself.
    assert (tmp_path / "reports").is_dir()


def test_validate_one_returns_newman_exit_code_on_failure(tmp_path: Path) -> None:
    """When Newman exits non-zero, we propagate it (don't mask)."""
    coll = tmp_path / "c.json"
    coll.write_text("{}")
    with patch("scripts.validate_api.run_newman", return_value=1):
        rc = validate_one(coll, "http://x", "t", tmp_path / "reports")
    assert rc == 1


def test_main_aggregates_failures_across_collections(tmp_path: Path) -> None:
    """The first failing collection's exit code wins; ok runs don't mask it."""
    coll_ok = tmp_path / "ok.json"
    coll_ok.write_text("{}")
    coll_bad = tmp_path / "bad.json"
    coll_bad.write_text("{}")

    with patch("scripts.validate_api.run_newman", side_effect=[0, 1]):
        rc = main(
            [
                "--collection",
                str(coll_ok),
                "--collection",
                str(coll_bad),
                "--base-url",
                "http://localhost:8000",
                "--token",
                "demo-token",
                "--report-dir",
                str(tmp_path / "reports"),
            ]
        )
    assert rc == 1


def test_main_returns_zero_when_all_pass(tmp_path: Path) -> None:
    coll = tmp_path / "ok.json"
    coll.write_text("{}")
    with patch("scripts.validate_api.run_newman", return_value=0):
        rc = main(
            [
                "--collection",
                str(coll),
                "--base-url",
                "http://localhost:8000",
                "--token",
                "demo-token",
                "--report-dir",
                str(tmp_path / "reports"),
            ]
        )
    assert rc == 0


def test_main_requires_at_least_one_collection() -> None:
    """Bare invocation → argparse error → exit 2."""
    with pytest.raises(SystemExit):
        main(
            [
                "--base-url",
                "http://localhost:8000",
                "--token",
                "demo-token",
            ]
        )
