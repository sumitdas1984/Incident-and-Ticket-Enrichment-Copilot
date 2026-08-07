"""Placeholder MCP server; real tools land in Epic 3."""
import os

from fastapi import FastAPI

app = FastAPI(title="alarm-management MCP server (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "alarm-management-mcp"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "9000")))