"""Frontend package — the copilot GUI.

Public surface:

* :mod:`apps.frontend.chat_client` — typed HTTP client for
  ``POST /chat``.
* :mod:`apps.frontend.ticket_client` — typed HTTP client for
  ``POST /tickets/preview`` and ``POST /tickets/draft``.
* :mod:`apps.frontend.ui` — the Streamlit script that renders
  the chat surface, the workspace column, and the ticket
  confirmation modal.

``python -m apps.frontend`` launches Streamlit (see
:mod:`apps.frontend.__main__`).
"""
from __future__ import annotations
