# src/api/main.py

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from api.lifespan import lifespan
from api.routers import rag, upload

# Default /docs hardcodes the absolute path "/openapi.json", which breaks behind
# path-rewriting proxies (e.g. JupyterHub's /user/<id>/proxy/8090 prefix).
# We disable it and serve a custom /docs that loads the spec via a relative URL,
# which resolves correctly both on direct access and behind the proxy.
app = FastAPI(title="RFP RAG API", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(rag.router)
app.include_router(upload.router)


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="openapi.json", title=f"{app.title} - Swagger UI")
