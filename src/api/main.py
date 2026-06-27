# src/api/main.py

from fastapi import FastAPI
from api.lifespan import lifespan
from api.routers import rag

app = FastAPI(title="RFP RAG API", lifespan=lifespan)
app.include_router(rag.router)
