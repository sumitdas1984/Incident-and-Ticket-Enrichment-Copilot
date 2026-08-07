"""Placeholder Alarm Management API simulator; real implementation lands in Epic 2."""
import os

from fastapi import FastAPI

app = FastAPI(title="alarm-api (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "alarm-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
