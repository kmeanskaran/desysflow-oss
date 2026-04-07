"""
DesysFlow — System Design AI Agent Backend.

FastAPI application entry point.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from services.conversation_store import get_conversation_store
from services.session_store import get_session_store

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DesysFlow — System Design AI Agent",
    description=(
        "A production-ready, multi-step AI agent backend that accepts system "
        "design requests and produces structured architecture recommendations "
        "through a LangGraph agent pipeline."
    ),
    version="1.0.0",
)

# CORS — allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(router)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("DesysFlow server starting up …")
    logger.info("Docs available at http://localhost:8000/docs")
    logger.info("Session store: %s", get_session_store().status())
    logger.info("Conversation store: %s", get_conversation_store().status())
