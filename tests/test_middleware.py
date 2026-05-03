import os
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import Scope

# Set environment variables BEFORE any imports from the app
os.environ["TESTING"] = "1"
os.environ["LOCAL_API_KEY"] = "test-api-key"

from local_ai_brain.middleware import MetricsMiddleware  # noqa: E402


def test_metrics_middleware_logging():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics_endpoint():
        return "metrics content"

    with TestClient(app) as client:
        with patch("local_ai_brain.middleware.logger") as mock_logger:
            # Test normal request logging
            response = client.get("/test")
            assert response.status_code == 200

            # Check that logger.info was called for /test
            # The log format is '{} - "{}" {} HTTP/{}" {}'
            mock_logger.info.assert_called()
            args = mock_logger.info.call_args[0]
            assert args[0] == '{} - "{} {} HTTP/{}" {}'
            # args[1]: host, [2]: method, [3]: path, [4]: version, [5]: status
            assert args[2] == "GET"
            assert args[3] == "/test"
            assert args[5] == "200"

            mock_logger.info.reset_mock()

            # Test /metrics request logging (should be skipped)
            response = client.get("/metrics")
            assert response.status_code == 200
            mock_logger.info.assert_not_called()


def test_metrics_middleware_sanitization():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    async def mock_call_next(request):
        return MagicMock(status_code=200)

    middleware = MetricsMiddleware(app)

    scope: Scope = {
        "type": "http",
        "method": "GET\n",
        "path": "/malicious\rpath",
        "headers": [],
        "http_version": "1.1",
    }
    request = Request(scope)

    with patch("local_ai_brain.middleware.logger") as mock_logger:
        import asyncio

        asyncio.run(middleware.dispatch(request, mock_call_next))

        mock_logger.info.assert_called()
        args = mock_logger.info.call_args[0]
        # Verify both method and path are sanitized in the arguments passed to logger
        assert "\\n" in args[2]
        assert "\n" not in args[2]
        # If \r survives, it should be escaped. If it's stripped, we just ensure no \r.
        assert "\\r" in args[3] or "\r" not in args[3]


def test_metrics_middleware_fallback_host():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/")
    async def root():
        return {"ok": True}

    # We need to trigger a request where request.client is None
    # TestClient usually sets it. Let's mock the request object in dispatch.

    async def mock_call_next(request):
        return MagicMock(status_code=200)

    middleware = MetricsMiddleware(app)

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "http_version": "1.1",
    }
    # request.client will be None because we don't provide 'client' in scope
    request = Request(scope)

    with patch("local_ai_brain.middleware.logger") as mock_logger:
        import asyncio

        asyncio.run(middleware.dispatch(request, mock_call_next))

        mock_logger.info.assert_called()
        args = mock_logger.info.call_args[0]
        # args[1] is the client host
        assert args[1] == "-"
