# Feature 7.1 — Copilot Interface

> **Context.** Feature 6.2 (ticket approval gate, issue #55) just landed.
> `apps/frontend/` is still the placeholder FastAPI app with a `/health`
> endpoint; it never accepted a chat message. The brief (`Assignment_Use_Case.md`
> § 4 GUI expectations, § 5 GUI requirements) requires a usable chat surface
> that calls the backend's `POST /chat` and renders the structured response.
> Hard constraint #5 says no hard-coded URLs — every URL/key must come from
> environment variables. Issue #24 (Feature 7.1) and its two sub-issues
> (#56 chat interface, #57 connect frontend with backend) are open and
> blocking Feature 7.2 (#25, incident workspace), Story 9.2.2 (demo
> screenshots), Story 9.2.3 (demo video), and Story 9.2.1 (Docker
> deployment smoke).
>
> **Outcome.** A runnable Streamlit chat UI on port 5173 that POSTs to
> `POST /chat` (the backend's existing endpoint at
> `apps/backend/routes.py:46`), renders the structured response (answer +
> citations + trace + incident), surfaces loading / empty / error states,
> and is wired through `docker compose up --build` with a real healthcheck.

---

## Approach: Streamlit (python-only) replacing the FastAPI stub

**Why Streamlit, not React / Angular / Vue.**

* The brief's GUI list permits it explicitly ("React / Angular / Vue /
  Streamlit / Gradio / equivalent").
* The existing Docker image is Python-only — adding Streamlit keeps the
  image lean (no Node, no bundler, no separate build stage).
* Streamlit ships `st.chat_message` / `st.chat_input` primitives, which
  are exactly what Story 7.1.1 needs (chat input + message list + send).
* Loading / empty / error states are trivial (`st.spinner`, `st.empty`,
  `st.error`).
* Env-driven config is the default: `os.environ.get("COPILOT_BACKEND_URL")`
  read at module load, no build-time substitution.
* Story 7.2's workspace panel (citations + trace + draft + confirm modal)
  can be added as additional Streamlit panels in the same app — no
  framework swap needed.

**Trade-off accepted.** Streamlit's reactivity is server-driven (page
re-renders on each interaction). For a chat surface that's fine. If 7.2
needs SPA-grade interactivity we revisit in that story.

---

## Architecture

```
┌─────────────────┐  HTTP   ┌─────────────────┐  MCP / RAG  ┌────────────┐
│  frontend       │ ──────▶ │  copilot-backend │ ──────────▶ │ MCP / RAG  │
│  (Streamlit)    │ ◀────── │  (FastAPI)        │ ◀────────── │            │
│  port 5173      │  JSON   │  port 8000        │             └────────────┘
└─────────────────┘         └─────────────────┘
```

* Browser → `http://localhost:5173` → Streamlit runs as the ASGI app
  inside a single container.
* Streamlit script POSTs `{"message": "...", "conversation_id": <id>}`
  to `COPILOT_BACKEND_URL` (default `http://localhost:8000`; in the
  Docker network this is overridden to `http://copilot-backend:8000`).
* The backend's existing `POST /chat` (`apps/backend/routes.py:46`) is
  the only API surface the GUI talks to. The `/tickets/draft` endpoint
  is a separate Story (7.2.1/7.2.3) and is **not** invoked from 7.1.
* `x-trace-id` header is forwarded on every chat request so the
  backend's log entries chain with the GUI's request.

---

## File-by-file plan

### 1. New module: `apps/frontend/chat_client.py`

Typed HTTP client for the copilot backend. Mirrors the existing
backend request/response shapes (`ChatRequest` / `ChatResponse`) but
as a separate non-FastAPI module (Streamlit doesn't share FastAPI
models). Purpose: **one** place to construct the URL, marshal JSON,
forward headers, and translate httpx errors into a typed `ChatError`
exception the Streamlit script can render.

```
class ChatError(Exception):
    """Raised when the backend is unreachable or returns a non-2xx."""

class ChatClient:
    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None: ...
    def send(self, *, message: str, conversation_id: str | None,
             trace_id: str | None) -> ChatResponse: ...
```

* Uses `httpx.Client` (synchronous — Streamlit is sync).
* `base_url` from `os.environ.get("COPILOT_BACKEND_URL",
  "http://localhost:8000")` at construction time.
* On `httpx.HTTPStatusError`: read the JSON `detail` body, raise
  `ChatError(code=..., message=...)`.
* On `httpx.RequestError` (connection refused, DNS failure, timeout):
  raise `ChatError(code="backend_unreachable", message=str(exc))`.

### 2. New module: `apps/frontend/ui.py`

The Streamlit UI. Single function `main()` that the entrypoint calls.

```
def main() -> None:
    st.set_page_config(page_title="Incident Copilot", page_icon="🚨")
    settings = get_settings()
    client = ChatClient(base_url=settings.copilot_backend_url)
    _render_history(client)
    _render_input(client)
```

* `_render_history(client)`: replays `st.session_state.messages`
  with `st.chat_message(role)`. Each assistant message renders:
  - The answer body (`st.markdown(answer)`)
  - An expander "Citations (N)" listing each citation's
    `doc_id` + `section` + `score`
  - An expander "MCP trace (N steps)" listing each step's
    `server` + `tool` + `outcome` + `duration_ms`
  - An expander "Incident" with the structured fields (asset, severity,
    recommended_actions, similar_tickets) — read-only here; the
    editable draft panel is Story 7.2.1's deliverable.
* `_render_input(client)`: `st.chat_input(...)` at the bottom. On
  submit: append user turn, `with st.spinner("Investigating…")`, call
  `client.send(...)`, append assistant turn, `st.rerun()`.
* `st.session_state.messages`: `list[dict[str, Any]]` — append-only,
  carries `{"role", "content", "trace", "citations", "incident",
  "conversation_id"}` per assistant turn.
* Loading state: `st.spinner` during the in-flight POST.
* Empty state: when `st.session_state.messages` is empty, show
  "Try: *Investigate recurring high-severity alarms on boiler B-101
  in the last 90 days.*" as a `st.info` callout.
* Error state: when `ChatError` is raised, show
  `st.error(f"[{code}] {message}")` and leave the user turn in
  history so the user can retry.

### 3. Modify: `apps/frontend/__main__.py`

Replace the FastAPI stub with the Streamlit runner. Streamlit is
typically launched via `streamlit run <script>`, but we need to play
nicely with `python -m apps.frontend` (the docker-compose
`MODULE_PATH` pattern). Two options; pick the cleanest:

* **Option A (preferred):** `python -m apps.frontend` invokes
  `subprocess.run([sys.executable, "-m", "streamlit", "run",
  "<ui.py>", "--server.port", str(port), "--server.headless",
  "true", "--server.address", "0.0.0.0"])`. The entrypoint becomes a
  thin launcher that execs Streamlit. Keeps the existing
  `MODULE_PATH` docker-compose contract unchanged.
* **Option B:** Use Streamlit's `AppTest` / programmatic API to run
  inside the same process — works but loses the standard Streamlit
  CLI behaviour (auto-reload, browser open, telemetry). Reject.

The launcher logs `"frontend.starting" component="frontend" port=5173
backend=<url>` then execs. The Docker healthcheck curls
`http://localhost:5173/_stcore/health` — Streamlit's documented
unauthenticated liveness endpoint (the existing
`http://localhost:5173/health` is **not** served by Streamlit, so the
docker-compose healthcheck needs updating — see step 5).

### 4. New module: `apps/frontend/__init__.py`

Stays a single-line docstring. The package's public surface is the
`ui` module + `chat_client` module; `__main__` imports them.

### 5. Modify: `docker-compose.yml`

* `frontend` healthcheck: change target from
  `http://localhost:5173/health` to `http://localhost:5173/_stcore/health`
  (Streamlit's built-in healthcheck endpoint).
* `frontend` env: add `COPILOT_BACKEND_URL: http://copilot-backend:8000`
  so the in-container Streamlit reaches the backend over the
  docker network.

### 6. Modify: `core/config.py`

Add `copilot_backend_url: str = "http://localhost:8000"` to the
`Settings` model. Frontend reads this through `get_settings()` —
**no** new `os.getenv` call (CLAUDE.md "no os.getenv outside core/").
Streamlit reads `settings.copilot_backend_url` at module import.

### 7. Modify: `pyproject.toml`

Add `streamlit>=1.39` to `[project.dependencies]`. Streamlit is
Python-only and CPU-cheap; pin to a major version known to ship
`st.chat_input` (1.27+).

### 8. Modify: `Dockerfile`

The current `CMD ["sh", "-c", "exec uv run python -m ${MODULE_PATH}.__main__"]`
already supports `MODULE_PATH=apps.frontend`. No Dockerfile changes
needed for the launcher path. Verify the existing image already has
curl (it does — line 26) so the healthcheck probe works.

### 9. Modify: `.env.example`

Add a documented entry `COPILOT_BACKEND_URL=http://localhost:8000`.
Docker overrides this to `http://copilot-backend:8000` via
`docker-compose.yml`.

---

## Tests

### Unit (`tests/unit/frontend/` — new directory)

* `test_chat_client.py` — exercises the HTTP client against
  `respx` (already in the dev deps tree) or against
  `fastapi.testclient.TestClient` wrapping a stub
  `FakeChatApp`. Cases:
  - Happy path: 200 + valid `ChatResponse` envelope → returned as-is.
  - 4xx: `detail={"code": "planner_error", ...}` → `ChatError` with
    code/message preserved.
  - 5xx: same shape, different code.
  - Connection refused: `httpx.ConnectError` →
    `ChatError(code="backend_unreachable")`.
  - Timeout: same.
  - `x-trace-id` header round-trips when supplied.
  - `conversation_id` is sent when supplied; omitted otherwise.
* `test_ui_smoke.py` — uses Streamlit's `AppTest` (built-in
  headless test runner, no browser) to assert:
  - App boots without raising.
  - Empty-state info callout is present on first load.
  - Submitting a message via `app.test_input_widget(key=...)` adds
    an assistant message after the spinner resolves.

### Integration (`tests/integration/frontend/` — new directory)

* `test_chat_flow.py` — boots the real backend
  (`apps/backend.create_app()`) on the in-process TestClient,
  boots Streamlit's AppTest pointed at it, and verifies one full
  round-trip: user message → assistant answer → citation list
  rendered. Skipped when `var/index/v1.pkl` is missing (existing
  `_require_rag_index` pattern from
  `tests/integration/test_orchestrator_ticket_e2e.py:41`).

### Existing test surface

* No existing frontend tests → nothing to delete.
* `tests/unit/core/test_settings.py` may exist; if it does, add a
  case for `copilot_backend_url`'s default.

---

## Verification

1. **Static gates (matches prior features):**
   ```
   uv run ruff check .
   uv run mypy --explicit-package-bases apps rag connectors core
   uv run pytest -ra
   ```
2. **In-process smoke:** with `var/index/v1.pkl` built, run
   `uv run streamlit run apps/frontend/ui.py --server.port 5173`,
   open the browser, type *"Investigate boiler 101 high temp in the
   last 30 days"*, confirm:
   - Assistant answer renders.
   - Citations expander lists ≥1 entry.
   - MCP trace expander lists the alarm-management MCP tools.
   - "Backend unreachable" error renders if backend is stopped.
3. **Docker stack smoke:** from a clean clone, run
   `docker compose up --build`, wait for `frontend`'s healthcheck to
   go `healthy`, then `curl -s http://localhost:5173/_stcore/health`
   returns `ok`. Open the browser and confirm a chat round-trip.
4. **PR:** open against `developer`. CI runs ruff + mypy + pytest
   + smoke (existing workflow covers it; no workflow changes needed).

---

## Out of scope (deferred to later stories)

* Editable ticket draft panel (Story 7.2.1).
* Citations panel as a top-level layout (Story 7.2.2 — 7.1 renders
  citations inline inside each assistant message).
* MCP trace panel as a top-level layout (Story 7.2.2 — same).
* Ticket confirmation modal (Story 7.2.3, depends on 7.1).
* Authenticated user identity in the GUI (the `APPROVAL_USER`
  default "operator" stays; SSO/JWT is future work).

---

## Files to be modified / created

| Action | Path | Purpose |
|---|---|---|
| **new** | `apps/frontend/chat_client.py` | Typed HTTP client for `POST /chat`. |
| **new** | `apps/frontend/ui.py` | Streamlit UI script. |
| **modify** | `apps/frontend/__main__.py` | Replace FastAPI stub with Streamlit launcher. |
| **modify** | `core/config.py` | Add `copilot_backend_url`. |
| **modify** | `pyproject.toml` | Add `streamlit>=1.39` dep. |
| **modify** | `docker-compose.yml` | Healthcheck path + env override. |
| **modify** | `.env.example` | Document `COPILOT_BACKEND_URL`. |
| **new** | `tests/unit/frontend/__init__.py` | Package marker. |
| **new** | `tests/unit/frontend/test_chat_client.py` | HTTP client unit tests. |
| **new** | `tests/unit/frontend/test_ui_smoke.py` | AppTest smoke. |
| **new** | `tests/integration/frontend/__init__.py` | Package marker. |
| **new** | `tests/integration/frontend/test_chat_flow.py` | In-process backend + AppTest. |
| **modify** | `docs/architecture.md` | Update the GUI layer description. (Optional — defer if not strictly needed.) |

---

## Rollback

Delete the new files, revert the modified files to their previous
versions, drop `streamlit` from `pyproject.toml`, drop
`copilot_backend_url` from `core/config.py`. The Docker healthcheck
reverts to the FastAPI stub's `/health` path.