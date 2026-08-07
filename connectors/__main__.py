"""Placeholder ticket mock; real ticketing lands in Epic 6."""
import os

from fastapi import FastAPI

app = FastAPI(title="ticket-mock (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ticket-mock"}


if __name__ == "__main__":
    import uvicorn

    # Default to 8000 inside the container; docker-compose.yml maps
    # the host-side TICKETING_API_PORT (default 8003) onto this.
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
