"""Frontend entry point — boots the Streamlit GUI.

Feature 7.1 — the docker-compose ``frontend`` service runs
``python -m apps.frontend`` (via the ``MODULE_PATH`` build arg
and the image's CMD shim — see ``Dockerfile``). To preserve that
contract without depending on Streamlit's CLI handling being
called directly, this launcher execs ``streamlit run`` against
``apps/frontend/ui.py``.

Why a launcher, not a programmatic Streamlit bootstrap
------------------------------------------------------

* Keeps the existing ``MODULE_PATH=apps.frontend`` docker-compose
  contract unchanged.
* Lets operators run ``uv run streamlit run apps/frontend/ui.py``
  directly during local development — the same script and the
  same flags work in both paths.
* Streamlit's programmatic ``bootstrap.run`` exists but loses
  CLI niceties (auto-reload, telemetry, browser opening) we
  don't want to reimplement.

The launcher reads ``core.config.get_settings().frontend_port``
(no ``os.getenv`` here — CLAUDE.md) and forwards the standard
Streamlit server flags so the docker-compose healthcheck can
reach ``http://localhost:5173/_stcore/health``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="frontend")


def _ui_script_path() -> Path:
    """Absolute path to ``apps/frontend/ui.py``.

    The launcher lives next to ``ui.py`` so a sibling lookup is
    the simplest correct resolution; absolute paths survive
    working-directory changes (Streamlit re-execs the script
    against the cwd it was launched with).
    """
    return Path(__file__).resolve().parent / "ui.py"


def main() -> None:
    """Run Streamlit as a subprocess and wait for it to exit."""
    port = settings.frontend_port
    ui_path = _ui_script_path()
    if not ui_path.exists():
        log.error("ui.missing", path=str(ui_path))
        raise SystemExit(f"Streamlit UI script not found at {ui_path}")

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ui_path),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        # Streamlit defaults to 0.0.0.0 when ``--server.address`` is
        # not set, but we pin it explicitly so a future Streamlit
        # default flip doesn't accidentally bind to localhost-only.
        "--server.address",
        "0.0.0.0",
        # Disable the file-watcher: the GUI is a thin client and
        # operator changes to the script can be picked up by
        # restarting the container. Auto-reload inside docker
        # causes confusing restart loops during dev.
        "--server.fileWatcherType",
        "none",
    ]
    log.info(
        "frontend.starting",
        component="frontend",
        port=port,
        backend=settings.copilot_backend_url,
        script=str(ui_path),
    )
    # ``exec`` semantics would replace the launcher process —
    # prefer subprocess so the launcher's structured log line is
    # the last thing emitted on graceful shutdown.
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
