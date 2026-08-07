"""Placeholder backend; real implementation lands in Epic 5."""
import os

from fastapi import FastAPI

app = FastAPI(title="copilot-backend (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "copilot-backend"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
