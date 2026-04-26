from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_ai_brain.middleware import MetricsMiddleware


def test_metrics_middleware_logging():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics_endpoint():
        return "metrics content"

    client = TestClient(app)

    with patch("local_ai_brain.middleware.logger") as mock_logger:
        # Test normal request logging
        response = client.get("/test")
        assert response.status_code == 200

        # Check that logger.info was called for /test
        # The log format is '{client_host} - "{method} {url_path} HTTP/{http_version}"'
        # followed by the status code.
        # TestClient uses 'testclient' as host usually, or it might be None
        mock_logger.info.assert_called()
        log_msg = mock_logger.info.call_args[0][0]
        assert '"GET /test HTTP/1.1" 200' in log_msg

        mock_logger.info.reset_mock()

        # Test /metrics request logging (should be skipped)
        response = client.get("/metrics")
        assert response.status_code == 200
        mock_logger.info.assert_not_called()


def test_metrics_middleware_sanitization():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    from fastapi import Request
    from starlette.types import Scope

    async def mock_call_next(request):
        return MagicMock(status_code=200)

    middleware = MetricsMiddleware(app)

    scope: Scope = {
        "type": "http",
        "method": "GET\n",
        "path": "/malicious\npath",
        "headers": [],
        "http_version": "1.1",
    }
    request = Request(scope)

    with patch("local_ai_brain.middleware.logger") as mock_logger:
        import asyncio

        asyncio.run(middleware.dispatch(request, mock_call_next))

        mock_logger.info.assert_called()
        log_msg = mock_logger.info.call_args[0][0]
        # Verify both method and path are sanitized
        assert "\\n" in log_msg
        assert "\n" not in log_msg


def test_metrics_middleware_fallback_host():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/")
    async def root():
        return {"ok": True}

    # We need to trigger a request where request.client is None
    # TestClient usually sets it. Let's mock the request object in dispatch.

    from fastapi import Request
    from starlette.types import Scope

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
        log_msg = mock_logger.info.call_args[0][0]
        assert log_msg.startswith("- -")
