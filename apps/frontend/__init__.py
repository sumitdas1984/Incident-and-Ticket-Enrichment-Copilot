"""Frontend package — the copilot GUI.

Public surface:

* :mod:`apps.frontend.chat_client` — typed HTTP client for
  ``POST /chat``.
* :mod:`apps.frontend.ui` — the Streamlit script that renders
  the chat surface.

``python -m apps.frontend`` launches Streamlit (see
:mod:`apps.frontend.__main__`).
"""
from __future__ import annotations
