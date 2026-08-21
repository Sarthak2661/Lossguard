from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from apps.scoring_api.model_service import ModelService
from lossguard.config import get_settings
from lossguard.schemas import ScoreResponse, TransactionEvent

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
service = ModelService(settings.model_bundle_path)

app = FastAPI(
    title="LossGuard Scoring API",
    description="Cost-sensitive approve / verify / decline recommendations",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_ready": service.is_model_ready,
        "model_version": service.model_version,
        "mode": "trained_model" if service.is_model_ready else "development_heuristic",
    }


@app.post("/score", response_model=ScoreResponse)
def score_transaction(event: TransactionEvent) -> ScoreResponse:
    try:
        return service.score(event)
    except Exception as exc:
        logging.exception("Scoring failed for transaction %s", event.transaction_id)
        raise HTTPException(status_code=500, detail="Transaction could not be scored") from exc


@app.post("/reload")
def reload_model() -> dict:
    service.reload()
    return health()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
