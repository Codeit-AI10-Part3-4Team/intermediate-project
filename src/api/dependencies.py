# src/api/dependencies.py

from fastapi import Request
from rag_core.interfaces import Orchestrator


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator
