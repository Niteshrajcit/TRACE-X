import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.action.handlers import register_action_handlers
from app.action.mock_router import router as mock_router
from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging, get_logger
from app.health.router import router as health_router
from app.modules.audit.router import router as audit_router
from app.modules.complaints.router import router as complaints_router
from app.graph.handlers import (
    register_corridor_prediction_handlers,
    register_exit_scoring_handlers,
    register_explainer_handlers,
    register_ring_detection_handlers,
    register_risk_field_handlers,
)
from app.modules.deployments.router import router as deployments_router
from app.modules.jurisdictions.router import router as jurisdictions_router
from app.modules.transactions.router import router as transactions_router
from app.ws.handlers import register_ws_event_handlers
from app.ws.router import router as ws_router

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(
    title="TRACE-X API",
    description="Predictive Cybercrime Cash-Withdrawal Intelligence Platform - Phase 0/1 foundation",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """docs/API_CONTRACT.md §8's consistent error shape."""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.__class__.__name__.upper(),
                "message": exc.detail,
                "request_id": request_id,
            }
        },
    )


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(complaints_router)
app.include_router(transactions_router)
app.include_router(jurisdictions_router)
app.include_router(deployments_router)
app.include_router(audit_router)
app.include_router(mock_router)
app.include_router(ws_router)


@app.on_event("startup")
async def on_startup() -> None:
    register_ws_event_handlers()
    register_ring_detection_handlers()
    register_corridor_prediction_handlers()
    register_exit_scoring_handlers()
    register_risk_field_handlers()
    register_explainer_handlers()
    # Must run after register_ws_event_handlers() - see
    # app/action/handlers.py::register_action_handlers's own docstring.
    register_action_handlers()
    logger.info("app.startup", extra={"extra_fields": {"environment": settings.environment}})
