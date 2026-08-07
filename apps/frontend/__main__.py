"""Placeholder frontend; real GUI lands in Epic 7."""
import os

from fastapi import FastAPI

app = FastAPI(title="frontend (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "frontend"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5173")))
