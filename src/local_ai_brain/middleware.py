from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking HTTP request metrics and logging access requests."""

    async def dispatch(self, request: Request, call_next):
        """Dispatches the request and records metrics and access logs."""
        from .metrics import http_requests_total

        status_code = "500"
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        except Exception:
            raise
        finally:
            client_host = request.client.host if request.client else "-"
            method = request.method.replace("\n", "\\n").replace("\r", "\\r")
            url_path = request.url.path.replace("\n", "\\n").replace("\r", "\\r")
            http_version = request.scope.get("http_version", "1.1")

            if url_path != "/metrics":
                logger.info(
                    '{} - "{} {} HTTP/{}" {}',
                    client_host,
                    method,
                    url_path,
                    http_version,
                    status_code,
                )

            http_requests_total.add(1, {"endpoint": url_path, "status": status_code})
