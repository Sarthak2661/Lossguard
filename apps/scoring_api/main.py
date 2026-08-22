from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from apps.scoring_api.model_service import ModelService
from lossguard.config import get_settings
from lossguard.database import TransactionRepository
from lossguard.schemas import ScoreResponse, TransactionEvent

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
metric_repository = TransactionRepository(settings.database_url)
service = ModelService(settings.model_bundle_path, metric_repository.record_metric)

app = FastAPI(
    title="LossGuard Scoring API",
    description="Cost-sensitive approve / verify / decline recommendations",
    version="0.1.0",
)


def _require_key(candidate: str | None, expected: str) -> None:
    if candidate is None or not secrets.compare_digest(candidate, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def require_scoring_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    _require_key(x_api_key, get_settings().scoring_api_key)


def require_admin_key(
    x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
) -> None:
    _require_key(x_admin_key, get_settings().admin_api_key)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_ready": service.is_model_ready,
        "model_version": service.model_version,
        "artifact_verified": service.artifact_sha256 is not None,
        "artifact_sha256": service.artifact_sha256,
        "mode": "trained_model" if service.is_model_ready else "development_heuristic",
    }


@app.post(
    "/score",
    response_model=ScoreResponse,
    dependencies=[Depends(require_scoring_key)],
)
def score_transaction(event: TransactionEvent) -> ScoreResponse:
    try:
        return service.score(event)
    except Exception as exc:
        logging.exception("Scoring failed for transaction %s", event.transaction_id)
        raise HTTPException(status_code=500, detail="Transaction could not be scored") from exc


# Administrative endpoint: X-Admin-Key authentication is enforced before model reload.
@app.post("/reload", dependencies=[Depends(require_admin_key)])
def reload_model() -> dict:
    try:
        service.reload(raise_on_error=True)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Model artifact validation failed") from exc
    return health()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
