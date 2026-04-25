import psutil
from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .metrics import http_requests_total, memory_rejections_total


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        http_requests_total.labels(
            endpoint=request.url.path, status=str(response.status_code)
        ).inc()
        return response


class MemoryGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Calculate current memory usage in GB
        vm = psutil.virtual_memory()
        used_gb = vm.used / (1024**3)

        projected_cost_gb = 0.0

        if request.url.path == "/v1/chat/completions" and request.method == "POST":
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    content_length_bytes = int(content_length)
                    if content_length_bytes < 0:
                        content_length_bytes = 0
                except ValueError:
                    content_length_bytes = 0
                projected_cost_gb = content_length_bytes * 0.0001

        total_projected_gb = used_gb + projected_cost_gb

        logger.info(
            f"Memory Check: {used_gb:.2f}GB used. Projected request cost: "
            f"{projected_cost_gb:.2f}GB. Total projected: {total_projected_gb:.2f}GB. "
            f"Limit: {settings.MEMORY_LIMIT_GB}GB"
        )

        if total_projected_gb > settings.MEMORY_LIMIT_GB:
            logger.warning(
                f"Request rejected. Memory limit {settings.MEMORY_LIMIT_GB}GB exceeded. "
                f"Total projected: {total_projected_gb:.2f}GB"
            )
            memory_rejections_total.inc()
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": (
                            f"Memory limit of {settings.MEMORY_LIMIT_GB}GB exceeded. "
                            "Please resubmit a smaller payload."
                        ),
                        "type": "memory_limit_exceeded",
                    }
                },
            )

        response = await call_next(request)

        vm_post = psutil.virtual_memory()
        used_post_gb = vm_post.used / (1024**3)
        logger.info(f"Post-Request Memory: {used_post_gb:.2f}GB used.")

        return response
