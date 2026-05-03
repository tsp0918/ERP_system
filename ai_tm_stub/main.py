"""AI_TradeManagement Stub - FastAPI entrypoint.

A stand-alone FastAPI application that mimics the relevant subset of
AI_TradeManagement's HTTP interface, so the ERP can be tested with
`AI_TM_MOCK_MODE=false` against a real HTTP service running locally.

Run on a different port than the ERP:
    uvicorn ai_tm_stub.main:app --reload --port 5001

Endpoints provided (all under base URL):
    POST /hs/classify
    POST /gaihi/judge
    POST /gaihi/judge-bom
    POST /screening/denied-party
    POST /export/precheck
    POST /workflows/reassess-bom   (AI_TM pulls ERP data, judges, writes back)
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_tm_stub.routers import get_all_routers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


app = FastAPI(
    title="AI_TradeManagement Stub",
    version="0.1.0",
    description=(
        "Standalone HTTP stub that mimics the AI_TradeManagement service "
        "for ERP integration testing.\n\n"
        "Run me on a different port than the ERP, e.g. `--port 5001`, "
        "and configure the ERP's `.env` with:\n"
        "  AI_TM_MOCK_MODE=false\n"
        "  AI_TM_BASE_URL=http://localhost:5001"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "AI_TradeManagement Stub",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


for r in get_all_routers():
    app.include_router(r)
