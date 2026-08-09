"""Custom CSS theme + small HTML helpers for the Streamlit GUI.

Goal: turn Streamlit's default look (essentially bootstrap-flavored
spacing on a stark white background) into a clean, modern
enterprise dashboard the brief's evaluators don't wince at.

The theme is light-on-light with a single accent colour. Every
component is built from plain HTML emitted via
``st.markdown(..., unsafe_allow_html=True)`` so the styling
remains deterministic and doesn't depend on the Streamlit
theme's CSS variables.

Public surface
--------------

* ``inject_theme()`` — call once at the top of ``main()`` to
  inject the global CSS.
* ``render_card(title, body_html, *, accent="neutral", icon=None)``
  — render a bordered card with a coloured title bar.
* ``render_pill(text, *, kind="neutral")`` — a small inline badge.
* ``render_kv(label, value)`` — a key/value pair row.
* ``render_section(title, icon=None)`` — a section header with a
  left accent bar.
* ``render_user_message(content, timestamp)`` / ``render_assistant_message(...)``
  — chat-message cards with sender-specific styling.

The HTML helpers return strings; the caller wraps each in
``st.markdown(..., unsafe_allow_html=True)``. This keeps the
markup composable (e.g. an assistant message can include a
citations card without re-escaping).
"""
from __future__ import annotations

import re
from html import escape
from typing import Final

# ---------------------------------------------------------------------------
# Colour tokens — clean light, professional
# ---------------------------------------------------------------------------

# Brand
PRIMARY: Final = "#1f6feb"  # accent (links, primary buttons)
PRIMARY_DARK: Final = "#1a5fcc"
PRIMARY_FG: Final = "#ffffff"

# Surfaces
PAGE_BG: Final = "#f6f8fa"  # app background
CARD_BG: Final = "#ffffff"  # primary card
CARD_BG_MUTED: Final = "#f9fafb"  # nested card / sub-panel
BORDER: Final = "#d0d7de"  # card border
BORDER_STRONG: Final = "#afb8c1"
DIVIDER: Final = "#e5e7eb"

# Text
TEXT: Final = "#1f2328"  # primary
TEXT_MUTED: Final = "#57606a"  # secondary
TEXT_FAINT: Final = "#8c959f"  # tertiary

# State
SUCCESS: Final = "#1a7f37"
SUCCESS_BG: Final = "#e6f4ea"
WARNING: Final = "#9a6700"
WARNING_BG: Final = "#fff8c5"
DANGER: Final = "#cf222e"
DANGER_BG: Final = "#ffebe9"
INFO: Final = "#0969da"
INFO_BG: Final = "#ddf4ff"

# Severity colours (used by the draft form and the incident panel)
SEVERITY_LOW: Final = "#1a7f37"
SEVERITY_MEDIUM: Final = "#9a6700"
SEVERITY_HIGH: Final = "#bc4c00"
SEVERITY_CRITICAL: Final = "#cf222e"

# User-message accent (subtle, blue)
USER_ACCENT: Final = "#1f6feb"
USER_BG: Final = "#f0f6ff"

# Assistant-message accent (subtle, purple)
ASSISTANT_ACCENT: Final = "#8250df"
ASSISTANT_BG: Final = "#faf5ff"

# ---------------------------------------------------------------------------
# Global CSS — injected once at app start
# ---------------------------------------------------------------------------

GLOBAL_CSS: Final = f"""
<style>
/* ---------- App-level resets ---------- */
.stApp {{
    background: {PAGE_BG};
    color: {TEXT};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter",
                 "Helvetica Neue", Arial, sans-serif;
}}
.stApp > header {{
    background: transparent;
}}
.block-container {{
    padding-top: 1.5rem;
    padding-bottom: 7rem;  /* leave room for the pinned chat input */
    max-width: 1400px;
}}

/* ---------- Chat column ---------- */
.msg-user {{
    background: {USER_BG};
    border-left: 3px solid {USER_ACCENT};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0 0.75rem 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}}
.msg-user .msg-meta {{
    color: {USER_ACCENT};
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 0.25rem;
}}
.msg-user .msg-content {{
    color: {TEXT};
    font-size: 0.95rem;
    line-height: 1.5;
}}

.msg-assistant {{
    background: {CARD_BG};
    border-left: 3px solid {ASSISTANT_ACCENT};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0 0.75rem 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}}
.msg-assistant .msg-meta {{
    color: {ASSISTANT_ACCENT};
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 0.25rem;
}}
.msg-assistant .msg-content {{
    color: {TEXT};
    font-size: 0.95rem;
    line-height: 1.55;
}}
.msg-assistant .msg-content p {{ margin: 0.25rem 0; }}
.msg-assistant .msg-content code {{
    background: {CARD_BG_MUTED};
    padding: 0.1rem 0.3rem;
    border-radius: 3px;
    font-size: 0.85rem;
}}

/* ---------- Pills / badges ---------- */
.pill {{
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    margin-right: 0.3rem;
    line-height: 1.4;
}}
.pill-neutral {{ background: {CARD_BG_MUTED}; color: {TEXT_MUTED}; border: 1px solid {BORDER}; }}
.pill-info    {{ background: {INFO_BG};    color: {INFO}; }}
.pill-success {{ background: {SUCCESS_BG}; color: {SUCCESS}; }}
.pill-warning {{ background: {WARNING_BG}; color: {WARNING}; }}
.pill-danger  {{ background: {DANGER_BG};  color: {DANGER}; }}
.pill-user    {{ background: {USER_ACCENT}; color: {PRIMARY_FG}; }}
.pill-bot     {{ background: {ASSISTANT_ACCENT}; color: {PRIMARY_FG}; }}

/* Severity badges — surface at the incident panel and on the draft form */
.pill-sev-low      {{ background: {SEVERITY_LOW};      color: {PRIMARY_FG}; }}
.pill-sev-medium   {{ background: {SEVERITY_MEDIUM};   color: {PRIMARY_FG}; }}
.pill-sev-high     {{ background: {SEVERITY_HIGH};     color: {PRIMARY_FG}; }}
.pill-sev-critical {{ background: {SEVERITY_CRITICAL}; color: {PRIMARY_FG}; }}

/* ---------- Cards ---------- */
.card {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 1rem 1.1rem;
    margin: 0.6rem 0 0.85rem 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}}
.card.card-accent-neutral {{ border-left: 4px solid {BORDER_STRONG}; }}
.card.card-accent-success {{ border-left: 4px solid {SUCCESS}; }}
.card.card-accent-warning {{ border-left: 4px solid {WARNING}; }}
.card.card-accent-danger  {{ border-left: 4px solid {DANGER}; }}
.card.card-accent-info    {{ border-left: 4px solid {INFO}; }}
.card.card-accent-primary {{ border-left: 4px solid {PRIMARY}; }}

.card-header {{
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.6rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid {DIVIDER};
}}
.card-header .card-title {{
    font-size: 0.95rem;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 0.01em;
}}
.card-header .card-icon {{
    font-size: 1.1rem;
    line-height: 1;
}}

.card-subcard {{
    background: {CARD_BG_MUTED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 0.55rem 0.7rem;
    margin: 0.4rem 0;
    font-size: 0.85rem;
    color: {TEXT};
}}

.section-header {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.4rem 0 0.3rem 0;
    padding-left: 0.55rem;
    border-left: 4px solid {PRIMARY};
    color: {TEXT};
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}}

.kv-row {{
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
    margin: 0.18rem 0;
    font-size: 0.88rem;
    color: {TEXT};
}}
.kv-row .kv-label {{
    color: {TEXT_MUTED};
    font-weight: 600;
    min-width: 5.5rem;
}}
.kv-row .kv-value {{
    color: {TEXT};
}}

.divider {{
    height: 1px;
    background: {DIVIDER};
    margin: 0.8rem 0;
}}

/* ---------- App bar ---------- */
.app-bar {{
    background: {CARD_BG};
    border-bottom: 1px solid {BORDER};
    padding: 0.75rem 1.25rem;
    margin: -1.5rem -1.5rem 1rem -1.5rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}}
.app-bar .app-bar-icon {{
    font-size: 1.6rem;
    line-height: 1;
    flex: 0 0 auto;
}}
.app-bar .app-bar-title {{
    flex: 1 1 auto;
    text-align: center;
    font-size: 1.05rem;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 0.01em;
}}
.app-bar .app-bar-meta {{
    color: {TEXT_MUTED};
    font-size: 0.78rem;
    font-family: ui-monospace, "SF Mono", "Cascadia Code", Menlo, monospace;
    flex: 0 0 auto;
}}

/* ---------- Empty state ---------- */
.empty-state {{
    background: {CARD_BG_MUTED};
    border: 1px dashed {BORDER_STRONG};
    border-radius: 10px;
    padding: 1.5rem 1rem;
    text-align: center;
    color: {TEXT_MUTED};
    margin: 0.8rem 0;
}}
.empty-state .empty-state-title {{
    color: {TEXT};
    font-weight: 700;
    margin-bottom: 0.3rem;
}}

/* ---------- Stacked chip row (e.g. incident metadata) ---------- */
.chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin: 0.5rem 0 0.4rem 0;
}}

/* ---------- Timeline (MCP trace) ---------- */
.timeline {{
    list-style: none;
    padding: 0;
    margin: 0.4rem 0 0 0;
}}
.timeline-item {{
    position: relative;
    padding: 0.45rem 0 0.45rem 1.5rem;
    border-left: 2px solid {BORDER};
    margin-left: 0.4rem;
}}
.timeline-item::before {{
    content: "";
    position: absolute;
    left: -7px; top: 0.7rem;
    width: 12px; height: 12px;
    border-radius: 50%;
    background: {PRIMARY};
    border: 2px solid {CARD_BG};
}}
.timeline-item.timeline-success::before   {{ background: {SUCCESS}; }}
.timeline-item.timeline-error::before     {{ background: {DANGER}; }}
.timeline-item.timeline-timeout::before   {{ background: {WARNING}; }}
.timeline-item .timeline-meta {{
    font-size: 0.72rem;
    color: {TEXT_FAINT};
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.timeline-item .timeline-title {{
    font-size: 0.9rem;
    color: {TEXT};
    font-weight: 600;
}}
.timeline-item .timeline-detail {{
    font-size: 0.82rem;
    color: {TEXT_MUTED};
}}

/* ---------- Pin the chat input to the bottom of the column ---------- */
.chat-input-pinned {{
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(to top, {PAGE_BG} 70%, rgba(246,248,250,0));
    padding: 1rem 0 0.5rem 0;
    z-index: 100;
}}
.chat-input-pinned .stChatInput {{ background: transparent; }}

</style>
"""


def inject_theme() -> None:
    """Inject the global CSS theme. Call once at the top of ``main()``."""
    import streamlit as st

    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

_SEVERITY_PILL: dict[str, str] = {
    "low": "pill-sev-low",
    "medium": "pill-sev-medium",
    "high": "pill-sev-high",
    "critical": "pill-sev-critical",
}


def severity_pill(severity: str) -> str:
    """Return a coloured severity badge. Falls back to neutral."""
    kind = _SEVERITY_PILL.get(severity.lower(), "pill-neutral")
    return f"<span class='pill {kind}'>{escape(severity.upper())}</span>"


def render_pill(text: str, *, kind: str = "neutral") -> str:
    """Return a small inline badge. ``kind`` is one of neutral/info/success/warning/danger."""
    return f"<span class='pill pill-{escape(kind)}'>{escape(text)}</span>"


def render_kv(label: str, value: str) -> str:
    """Render a key/value pair row."""
    return (
        f"<div class='kv-row'>"
        f"<span class='kv-label'>{escape(label)}</span>"
        f"<span class='kv-value'>{escape(value)}</span>"
        f"</div>"
    )


def render_section(title: str, *, icon: str | None = None) -> str:
    """Render a section header with a left accent bar."""
    icon_html = f"<span>{escape(icon)}</span>" if icon else ""
    return (
        f"<div class='section-header'>"
        f"{icon_html}"
        f"<span>{escape(title)}</span>"
        f"</div>"
    )


def render_card(
    title: str,
    body_html: str,
    *,
    accent: str = "neutral",
    icon: str | None = None,
) -> str:
    """Render a bordered card with a coloured title bar.

    ``accent`` is one of neutral/primary/success/warning/danger/info.
    """
    icon_html = f"<span class='card-icon'>{escape(icon)}</span>" if icon else ""
    return (
        f"<div class='card card-accent-{escape(accent)}'>"
        f"<div class='card-header'>"
        f"{icon_html}"
        f"<span class='card-title'>{escape(title)}</span>"
        f"</div>"
        f"<div>{body_html}</div>"
        f"</div>"
    )


def render_empty_state(title: str, body: str, *, icon: str = "💡") -> str:
    """Render a friendly empty-state panel with a dashed border."""
    return (
        f"<div class='empty-state'>"
        f"<div class='empty-state-title'>{escape(icon)} {escape(title)}</div>"
        f"<div>{escape(body)}</div>"
        f"</div>"
    )


def render_divider() -> str:
    return "<div class='divider'></div>"


def render_user_message(content: str, *, timestamp: str | None = None) -> str:
    """Render a user chat message as a left-bordered card."""
    meta = (
        f"<div class='msg-meta'>You · {escape(timestamp)}</div>"
        if timestamp
        else "<div class='msg-meta'>You</div>"
    )
    body_html = escape(content).replace("\n", "<br>")
    return (
        f"<div class='msg-user'>"
        f"{meta}"
        f"<div class='msg-content'>{body_html}</div>"
        f"</div>"
    )


def render_assistant_message(
    content: str,
    *,
    timestamp: str | None = None,
    intent: str | None = None,
    rag_confidence: str | None = None,
    citations_count: int = 0,
    trace_steps: int = 0,
) -> str:
    """Render an assistant chat message as a card with metadata pills."""
    meta_bits = ["Copilot"]
    if timestamp:
        meta_bits.append(escape(timestamp))
    if intent:
        meta_bits.append(f"<span class='pill pill-info'>{escape(intent)}</span>")
    if rag_confidence:
        meta_bits.append(rag_confidence_pill(rag_confidence))
    if citations_count:
        meta_bits.append(f"<span class='pill pill-neutral'>📚 {citations_count} citation{'s' if citations_count != 1 else ''}</span>")
    if trace_steps:
        meta_bits.append(f"<span class='pill pill-neutral'>🛠 {trace_steps} step{'s' if trace_steps != 1 else ''}</span>")
    meta = "<div class='msg-meta'>" + " · ".join(meta_bits) + "</div>"

    # Convert simple markdown to HTML so the assistant's ## / - / lists
    # render in the card. This is intentionally minimal — the backend
    # produces short structured answers, not essays.
    body_html = _simple_markdown(content)

    return (
        f"<div class='msg-assistant'>"
        f"{meta}"
        f"<div class='msg-content'>{body_html}</div>"
        f"</div>"
    )


_CONF_PILL: dict[str, str] = {
    "high": "pill-success",
    "medium": "pill-warning",
    "low": "pill-danger",
    "none": "pill-neutral",
}


def rag_confidence_pill(confidence: str) -> str:
    """Render a RAG-confidence badge."""
    kind = _CONF_PILL.get(confidence.lower(), "pill-neutral")
    return f"<span class='pill {kind}'>RAG · {escape(confidence)}</span>"


def render_app_bar(backend_url: str) -> str:
    """Render the top app bar with a centered title.

    Three-column flex layout: brand icon on the left, centered
    title in the middle (flex-grows to fill the available
    space), backend URL + pill on the right. The middle cell's
    ``text-align: center`` plus ``flex: 1 1 auto`` is what makes
    the title sit visually centered even when the side cells
    have different widths.
    """
    return (
        f"<div class='app-bar'>"
        f"<span class='app-bar-icon'>🚨</span>"
        f"<span class='app-bar-title'>Incident Copilot</span>"
        f"<span class='app-bar-meta'>"
        f"<span class='pill pill-info'>backend</span> "
        f"<code>{escape(backend_url)}</code>"
        f"</span>"
        f"</div>"
    )


def render_timeline(
    steps: list[dict[str, object]],
) -> str:
    """Render the MCP execution trace as a vertical timeline.

    Each step is a dict with server / tool / outcome / duration_ms /
    api_status_code / error fields.
    """
    if not steps:
        return "<div class='card-subcard'>No MCP tools invoked yet.</div>"

    items: list[str] = []
    for idx, step in enumerate(steps, start=1):
        server = str(step.get("server", "?"))
        tool = str(step.get("tool", "?"))
        outcome = str(step.get("outcome", "?"))
        duration = step.get("duration_ms", "?")
        api_status = step.get("api_status_code")
        error = step.get("error")

        # Outcome class for the bullet colour.
        if outcome == "success":
            klass = "timeline-success"
        elif outcome == "timeout":
            klass = "timeline-timeout"
        elif outcome == "error":
            klass = "timeline-error"
        else:
            klass = ""

        meta_bits = [
            f"<span class='timeline-meta'>step {idx} · {escape(outcome)}</span>",
        ]
        detail = f"<strong>{escape(server)}</strong> → <code>{escape(tool)}</code>"
        if api_status is not None:
            detail += f" <span class='pill pill-neutral'>HTTP {api_status}</span>"
        detail += f" <span class='pill pill-neutral'>{duration} ms</span>"
        if error:
            detail += f"<div class='timeline-detail'>⚠️ {escape(str(error))}</div>"

        items.append(
            f"<li class='timeline-item {klass}'>"
            f"{''.join(meta_bits)}"
            f"<div class='timeline-title'>{detail}</div>"
            f"</li>"
        )

    return f"<ul class='timeline'>{''.join(items)}</ul>"


def render_citation_card(idx: int, citation: dict[str, object]) -> str:
    """Render a single citation as a subcard."""
    doc_id = str(citation.get("doc_id", "<unknown doc>"))
    section = citation.get("section")
    page = citation.get("page")
    score = citation.get("score")
    excerpt = citation.get("excerpt")

    chips: list[str] = [f"<span class='pill pill-neutral'>{escape(doc_id)}</span>"]
    if section:
        chips.append(f"<span class='pill pill-neutral'>§ {escape(str(section))}</span>")
    if page is not None:
        chips.append(f"<span class='pill pill-neutral'>p. {escape(str(page))}</span>")
    if score is not None:
        chips.append(f"<span class='pill pill-info'>score {float(score):.3f}</span>")  # type: ignore[arg-type]

    header = f"<div class='chip-row'>{''.join(chips)}</div>"
    body = ""
    if excerpt:
        body = f"<div class='card-subcard'>{escape(str(excerpt))}</div>"
    return (
        f"<div class='card card-accent-neutral'>"
        f"<div class='card-header'>"
        f"<span class='card-icon'>📄</span>"
        f"<span class='card-title'>Citation #{idx}</span>"
        f"</div>"
        f"{header}{body}"
        f"</div>"
    )


def render_chat_skeleton() -> str:
    """Render a placeholder card for the loading state — a clean
    animated bar (Streamlit handles the animation when the rerun
    swaps it for the real content)."""
    return (
        "<div class='card card-accent-info'>"
        "<div class='card-header'>"
        "<span class='card-icon'>⏳</span>"
        "<span class='card-title'>Investigating…</span>"
        "</div>"
        "<div class='card-subcard'>Connecting to the copilot backend, "
        "running the chain, and assembling the evidence.</div>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Tiny inline markdown helper
# ---------------------------------------------------------------------------

def _simple_markdown(s: str) -> str:
    """Light-touch markdown → HTML for the assistant's short answers.

    Handles: ``**bold**``, ``*italic*``, `` `code` ``, ``- lists``,
    ``\n`` → ``<br>``. Intentionally minimal — the backend composes
    short structured answers, not essays. Anything not matched is
    escaped and passed through.
    """
    out = escape(s)
    # Order matters: code first (so we don't bold inside code).
    out = _MD_CODE_RE.sub(r"<code>\1</code>", out)
    out = _MD_BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _MD_ITALIC_RE.sub(r"<em>\1</em>", out)
    # Lists (line-level): a line starting with "- " becomes a list item.
    lines = out.split("\n")
    rendered: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- "):
            if not in_list:
                rendered.append("<ul>")
                in_list = True
            rendered.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            if stripped == "":
                rendered.append("<br>")
            else:
                rendered.append(line)
    if in_list:
        rendered.append("</ul>")
    return "".join(rendered)


_MD_BOLD_RE = re.compile(r"\*\*([^\*]+)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<![*\w])\*([^\*\n]+)\*(?!\w)")
_MD_CODE_RE = re.compile(r"`([^`\n]+)`")


__all__ = [
    "inject_theme",
    "render_pill",
    "render_kv",
    "render_section",
    "render_card",
    "render_empty_state",
    "render_divider",
    "render_user_message",
    "render_assistant_message",
    "severity_pill",
    "rag_confidence_pill",
    "render_app_bar",
    "render_timeline",
    "render_citation_card",
    "render_chat_skeleton",
]
