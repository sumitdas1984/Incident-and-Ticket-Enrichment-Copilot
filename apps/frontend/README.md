# apps/frontend/

Placeholder. The actual GUI is implemented in **Epic 7 — User Experience**, which adds:

- `apps/frontend/src/main.pyx` (Streamlit / Gradio) or `apps/frontend/src/index.tsx` (React) — entrypoint
- Chat surface, incident workspace, citations panel, MCP trace panel, ticket confirmation modal

Until then, the docker-compose service is a stub that exposes a `/health` endpoint.