# src/api/main.py

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from api.errors import register_exception_handlers
from api.lifespan import lifespan
from api.middleware import RequestContextMiddleware
from api.routers import rag, upload

# Default /docs hardcodes the absolute path "/openapi.json", which breaks behind
# path-rewriting proxies (e.g. JupyterHub's /user/<id>/proxy/8090 prefix).
# We disable it and serve a custom /docs that loads the spec via a relative URL,
# which resolves correctly both on direct access and behind the proxy.
app = FastAPI(title="RFP RAG API", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(rag.router)
app.include_router(upload.router)

# Custom Swagger page (instead of fastapi.openapi.docs.get_swagger_ui_html):
# - url is relative ('openapi.json') so the spec resolves under the proxy prefix.
# - requestInterceptor: JupyterHub 5 enforces XSRF on POSTs passing through
#   jupyter-server-proxy ("'_xsrf' argument missing from POST" 403). The browser
#   already holds the _xsrf cookie, so we echo it as the X-XSRFToken header.
#   On direct access (no cookie) the interceptor is a no-op.
_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>RFP RAG API - Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: 'openapi.json',
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis],
      requestInterceptor: (req) => {
        const m = document.cookie.match(/(?:^|;\\s*)_xsrf=([^;]+)/);
        if (m) { req.headers['X-XSRFToken'] = decodeURIComponent(m[1]); }
        return req;
      },
    });
  </script>
</body>
</html>"""


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return HTMLResponse(_SWAGGER_UI_HTML)
