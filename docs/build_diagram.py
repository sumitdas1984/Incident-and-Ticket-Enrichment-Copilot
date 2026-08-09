"""Render ``docs/architecture-diagram.png``.

Two paths to regenerate:

1. **Mermaid (preferred, when ``npx`` is available).** The
   source ``docs/architecture-diagram.mmd`` is the canonical
   version. Render with::

       npx -y @mermaid-js/mermaid-cli -i docs/architecture-diagram.mmd \\
         -o docs/architecture-diagram.png -b transparent

2. **Pillow (this script — no external download required).**
   Used when the CI runner doesn't have ``npx``. Renders a clean
   labelled PNG via Pillow primitives. Run with::

       uv run python docs/build_diagram.py

The Pillow output is committed to the repo so reviewers always
have a PNG to look at; the Mermaid source is committed alongside
so a future CI with the Mermaid CLI installed can render the
authoritative version.

The two outputs cover the same content (the 12 layers + the MCP
and RAG paths). The Pillow version is a "good enough" fallback;
the Mermaid version is the source of truth.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Layout constants — kept generous so the boxes don't crowd.
W, H = 1600, 1100

# Colours.
BG = (255, 255, 255)
FG = (15, 23, 42)
SUB = (71, 85, 105)
BLUE = (37, 99, 235)
GREEN = (5, 150, 105)
AMBER = (217, 119, 6)
PURPLE = (124, 58, 237)
PINK = (157, 23, 77)
GRAY = (148, 163, 184)


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Pick the first available system font, fall back to Pillow's default."""
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    color: tuple[int, int, int],
    sub: str | None = None,
) -> None:
    """Draw a labelled rounded rectangle."""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=color)
    draw.text((x + 12, y + 10), label, fill=(255, 255, 255), font=_font(15))
    if sub:
        draw.text((x + 12, y + 32), sub, fill=(255, 255, 255), font=_font(11))


def _arrow(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int] = SUB,
    dashed: bool = False,
) -> None:
    """Draw a straight arrow with an arrowhead at (x2, y2)."""
    import math

    if dashed:
        # Hand-rolled dashed segment — Pillow's ``dash`` parameter is
        # not portable across Pillow versions.
        dash = 8
        cur_x, cur_y = x1, y1
        dx, dy = x2 - x1, y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        if dist == 0:
            return
        ux, uy = dx / dist, dy / dist
        traveled = 0.0
        while traveled < dist - 4:
            sx = cur_x + ux * dash
            sy = cur_y + uy * dash
            draw.line([cur_x, cur_y, sx, sy], fill=color, width=2)
            cur_x = sx + ux * dash
            cur_y = sy + uy * dash
            traveled += dash * 2
    else:
        draw.line([x1, y1, x2, y2], fill=color, width=2)

    ang = math.atan2(y2 - y1, x2 - x1)
    sz = 6
    draw.polygon(
        [
            (x2, y2),
            (x2 - sz * math.cos(ang - 0.4), y2 - sz * math.sin(ang - 0.4)),
            (x2 - sz * math.cos(ang + 0.4), y2 - sz * math.sin(ang + 0.4)),
        ],
        fill=color,
    )


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Title strip.
    d.text(
        (30, 18),
        "Incident-and-Ticket-Enrichment-Copilot — Architecture",
        fill=FG,
        font=_font(24),
    )
    d.text(
        (30, 52),
        "MCP path (top) + RAG path (bottom) + 12 mandated layers",
        fill=SUB,
        font=_font(13),
    )

    # Column headers.
    col_x = [40, 280, 520, 760, 1000, 1240]
    col_w = 220
    headers = [
        ("Operator", FG),
        ("GUI", BLUE),
        ("Orchestrator", PURPLE),
        ("MCP servers", PINK),
        ("Connectors", AMBER),
        ("RAG + Persistence", GREEN),
    ]
    for x, (lbl, col) in zip(col_x, headers, strict=False):
        d.text((x, 90), lbl, fill=col, font=_font(15))
        d.line([x, 110, x + col_w, 110], fill=col, width=2)

    # Boxes: (x, y, label, sub, color).
    boxes = [
        (40, 130, "Operator", "natural-language\nincident request", FG),
        (40, 290, "Streamlit UI", "chat + workspace", BLUE),
        (280, 130, "Streamlit script", "ui.py — main()", BLUE),
        (280, 210, "ChatClient", "POST /chat\n+ trace", BLUE),
        (280, 290, "TicketClient", "POST /tickets/preview\nPOST /tickets/draft", BLUE),
        (520, 130, "FastAPI routes", "/chat /tickets/preview\n/tickets/draft", PURPLE),
        (520, 230, "Planner", "MockPlanner\nLLMPlanner", PURPLE),
        (520, 310, "ChainRunner", "sequential v1\nwave-aware", PURPLE),
        (520, 400, "MCPClient (alarm)", "Streamable HTTP\n+ retry layer", PURPLE),
        (520, 480, "MCPClient (ticket)", "Streamable HTTP", PURPLE),
        (520, 560, "RagStepExecutor", "service.retrieve()", PURPLE),
        (520, 640, "ConversationStore", "in-memory dict", PURPLE),
        (760, 130, "alarm-management MCP", "5 tools, port 9000", PINK),
        (760, 270, "ticketing MCP", "2 tools, port 9001", PINK),
        (1000, 130, "alarm_api (sim)", "8 endpoints\nbearer + X-Trace-Id", AMBER),
        (1000, 270, "ticket_mock", "search / draft / audit\napproval gate", AMBER),
        (1240, 130, "Retrieval service", "filter + injection\n+ cosine + bands", GREEN),
        (1240, 280, "var/index/v1.pkl", "persisted RAG index", GREEN),
        (1240, 380, "ConversationStore\n(in-memory)", "audit trail", GREEN),
        (1240, 460, "Config / Logging /\nDomain", "core/config.py\ncore/logging.py", SUB),
    ]
    for x, y, label, sub, col in boxes:
        _box(d, x, y, col_w, 60, label, col, sub)

    # MCP-path arrows (Operator → UI → Orchestrator → MCP → Connector).
    _arrow(d, 140, 190, 280, 160)
    _arrow(d, 140, 350, 280, 240)
    _arrow(d, 400, 240, 520, 160)
    _arrow(d, 640, 430, 760, 160)  # alarm MCP client → alarm MCP
    _arrow(d, 640, 510, 760, 300)  # ticket MCP client → ticket MCP
    _arrow(d, 880, 190, 1000, 160)  # alarm MCP → alarm_api
    _arrow(d, 880, 330, 1000, 300)  # ticket MCP → ticket_mock

    # RAG-path arrows (Orchestrator → Retrieval → Index).
    _arrow(d, 640, 590, 1240, 160)
    _arrow(d, 1240, 190, 1240, 310)

    # Bottom legend with hard constraints.
    d.text(
        (30, H - 60),
        "Hard constraints: (1) MCP-only alarm path  (3) explicit ticket approval  (4) citations + trace on every answer",
        fill=SUB,
        font=_font(11),
    )
    d.text(
        (30, H - 40),
        "(6) prompt-injection defence  (7) synthetic data only  (8) general planner, no scripted answers",
        fill=SUB,
        font=_font(11),
    )
    d.text(
        (30, H - 20),
        "Generated by docs/build_diagram.py — also see architecture-diagram.mmd for the Mermaid source.",
        fill=GRAY,
        font=_font(10),
    )

    out = Path(__file__).resolve().parent / "architecture-diagram.png"
    img.save(out)
    print(f"wrote {out} ({out.stat().st_size} bytes, {img.size})")


if __name__ == "__main__":
    main()
