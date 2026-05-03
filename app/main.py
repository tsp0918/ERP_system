"""FastAPI application entrypoint."""
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import create_all_tables
from app.core.auth_router import router as auth_router
from app.core.exceptions import ERPException
from app.modules.mdm.router import get_mdm_routers
from app.modules.sd.router import get_sd_routers
from app.modules.pp.router import get_pp_routers
from app.modules.pp.execution_router import get_pp_execution_routers
from app.modules.mm.router import get_mm_routers
from app.modules.fi.router import get_fi_routers
from app.modules.hr.router import get_hr_routers
from app.modules.gts.router import get_gts_routers


# ==================================================================
# Logging
# ==================================================================
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("erp")


# ==================================================================
# App
# ==================================================================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Minimal global ERP for AI_TradeManagement integration testing.\n\n"
        "**Modules**: MDM (Master Data) / SD (Sales) / PP (Production) / "
        "MM (Procurement) / FI (Accounting) / HR (Human Resources) / "
        "GTS (Trade Compliance)\n\n"
        f"**AI_TradeManagement mode**: "
        f"{'MOCK' if settings.AI_TM_MOCK_MODE else 'LIVE @ ' + settings.AI_TM_BASE_URL}"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================================
# Request logging middleware
# ==================================================================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Tag every request with a correlation id and log timing."""
    request_id = str(uuid.uuid4())[:8]
    start = time.time()
    logger.info("→ %s %s %s", request_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("✗ %s unhandled exception", request_id)
        raise
    duration_ms = (time.time() - start) * 1000
    logger.info(
        "← %s %s %s [%d, %.1fms]",
        request_id, request.method, request.url.path,
        response.status_code, duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


# ==================================================================
# Exception handlers
# ==================================================================
@app.exception_handler(ERPException)
async def erp_exception_handler(request: Request, exc: ERPException):
    logger.warning("ERPException at %s: %s", request.url.path, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": type(exc).__name__},
        headers=exc.headers or {},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError,
):
    logger.warning("Validation error at %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "type": "ValidationError"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all. Logs the full traceback, returns a generic message."""
    logger.exception("Unhandled exception at %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ==================================================================
# Startup
# ==================================================================
@app.on_event("startup")
def on_startup():
    if settings.is_sqlite:
        create_all_tables()
    logger.info("ERP started (%s, AI_TM=%s)",
                settings.ENVIRONMENT,
                "MOCK" if settings.AI_TM_MOCK_MODE else settings.AI_TM_BASE_URL)


# ==================================================================
# Health
# ==================================================================
@app.get("/", tags=["Health"])
def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "ai_tm_mode": "MOCK" if settings.AI_TM_MOCK_MODE else "LIVE",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


# ==================================================================
# Mount routers
# ==================================================================
app.include_router(auth_router)
for r in get_mdm_routers():
    app.include_router(r)
for r in get_sd_routers():
    app.include_router(r)
for r in get_pp_routers():
    app.include_router(r)
for r in get_pp_execution_routers():
    app.include_router(r)
for r in get_mm_routers():
    app.include_router(r)
for r in get_fi_routers():
    app.include_router(r)
for r in get_hr_routers():
    app.include_router(r)
for r in get_gts_routers():
    app.include_router(r)
