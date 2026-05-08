import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from local_ai_brain.main import proxy_request


@pytest.fixture
def mock_app():
    app = FastAPI()
    app.state.client = AsyncMock(spec=httpx.AsyncClient)
    app.state.llm_semaphore = asyncio.Semaphore(1)
    return app


@pytest.fixture
def mock_request(mock_app):
    request = MagicMock(spec=Request)
    request.app = mock_app
    request.url.path = "/v1/chat/completions"
    request.url.query = ""
    request.method = "POST"
    request.headers = {"host": "localhost"}
    request.stream.return_value = AsyncMock()
    return request


@pytest.mark.anyio
async def test_proxy_request_semaphore_release_on_success(mock_request, mock_app):
    # Setup mock response
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "application/json"})
    mock_response.aiter_bytes.return_value = AsyncMock()
    mock_response.aiter_bytes.return_value.__aiter__.return_value = [b"chunk1", b"chunk2"]
    mock_app.state.client.send.return_value = mock_response

    # Verify semaphore is initially free
    assert not mock_app.state.llm_semaphore.locked()

    # Call proxy_request with semaphore
    response = await proxy_request(mock_request, "http://backend", use_semaphore=True)
    assert isinstance(response, StreamingResponse)

    # Semaphore should be acquired because streaming hasn't finished
    assert mock_app.state.llm_semaphore.locked()

    # Consume the stream to trigger release
    async for _ in response.body_iterator:
        pass

    # Semaphore should be released
    assert not mock_app.state.llm_semaphore.locked()
    mock_response.aclose.assert_called_once()


@pytest.mark.anyio
async def test_proxy_request_semaphore_release_on_send_failure(mock_request, mock_app):
    # Setup mock client to raise error
    mock_app.state.client.send.side_effect = httpx.RequestError("Failed")

    assert not mock_app.state.llm_semaphore.locked()

    with pytest.raises(HTTPException) as exc:
        await proxy_request(mock_request, "http://backend", use_semaphore=True)
    assert exc.value.status_code == 502

    # Semaphore should be released on failure
    assert not mock_app.state.llm_semaphore.locked()


@pytest.mark.anyio
async def test_proxy_request_response_closed_on_header_failure(mock_request, mock_app):
    # Setup mock response that exists but headers processing fails
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    # Simulate a failure by making headers processing raise an error
    mock_response.headers = MagicMock()
    # Mock both since proxy_request tries multi_items first
    mock_response.headers.items.side_effect = Exception("Header Failure")
    mock_response.headers.multi_items.side_effect = Exception("Header Failure")
    mock_app.state.client.send.return_value = mock_response

    assert not mock_app.state.llm_semaphore.locked()

    with pytest.raises(Exception, match="Header Failure"):
        await proxy_request(mock_request, "http://backend", use_semaphore=True)

    # Response should be closed and semaphore released
    mock_response.aclose.assert_called_once()
    assert not mock_app.state.llm_semaphore.locked()


@pytest.mark.anyio
async def test_proxy_request_cancellation_hardening(mock_request, mock_app):
    # Setup mock client to simulate cancellation during send
    mock_app.state.client.send.side_effect = asyncio.CancelledError()

    assert not mock_app.state.llm_semaphore.locked()

    with pytest.raises(asyncio.CancelledError):
        await proxy_request(mock_request, "http://backend", use_semaphore=True)

    # Semaphore MUST be released even on CancelledError
    assert not mock_app.state.llm_semaphore.locked()
