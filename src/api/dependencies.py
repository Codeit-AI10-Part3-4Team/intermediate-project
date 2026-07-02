# src/api/dependencies.py

from fastapi import Request
from rag_core.interfaces import Orchestrator, SuitabilityChecker


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def get_suitability_checker(request: Request) -> SuitabilityChecker:
    return request.app.state.suitability_checker
