import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Set environment variables BEFORE any imports from the app
os.environ["TESTING"] = "1"
os.environ["LOCAL_API_KEY"] = "test-secret-key"

# Mock heavy ML modules to prevent them from being imported/loaded at all
mock_vllm = MagicMock()
mock_batched = MagicMock()
mock_batched_instance = MagicMock()


async def dummy_async():
    pass


mock_batched_instance.start = dummy_async
mock_batched_instance.stop = dummy_async


# Mock for engine.chat
class MockOutput:
    def __init__(self):
        self.text = "Hello from mock!"
        self.prompt_tokens = 10
        self.completion_tokens = 20
        self.finish_reason = "stop"


async def mock_chat(*args, **kwargs):
    return MockOutput()


# Mock for engine.stream_chat
class MockChunk:
    def __init__(self, text, reason=None):
        self.new_text = text
        self.finish_reason = reason


async def mock_stream_chat(*args, **kwargs):
    yield MockChunk("Hello")
    yield MockChunk(" world", "stop")


mock_batched_instance.chat = mock_chat
mock_batched_instance.stream_chat = mock_stream_chat
mock_batched.return_value = mock_batched_instance

mock_vllm.engine.batched.BatchedEngine = mock_batched
sys.modules["vllm_mlx"] = mock_vllm
sys.modules["vllm_mlx.engine"] = MagicMock()
sys.modules["vllm_mlx.engine.batched"] = MagicMock()
sys.modules["vllm_mlx.engine.batched"].BatchedEngine = mock_batched

# Mock vllm_mlx.scheduler with a real SchedulerConfig stub
mock_scheduler_module = MagicMock()


class MockSchedulerConfig:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


mock_scheduler_module.SchedulerConfig = MockSchedulerConfig
sys.modules["vllm_mlx.scheduler"] = mock_scheduler_module

mock_whisper = MagicMock()
mock_whisper.transcribe.return_value = {"text": "Hello from mock Whisper!"}
sys.modules["mlx_whisper"] = mock_whisper


# Kokoro TTS mock
class MockKokoro:
    def __init__(self, *args, **kwargs):
        pass

    def create(self, text, voice, speed=1.0):
        import numpy as np

        return np.zeros(24000), 24000


sys.modules["kokoro_onnx"] = MagicMock()
sys.modules["kokoro_onnx"].Kokoro = MockKokoro

mock_hf = MagicMock()
mock_hf.hf_hub_download.return_value = "/tmp/mock_model"
sys.modules["huggingface_hub"] = mock_hf
sys.modules["huggingface_hub.utils"] = MagicMock()

from local_ai_brain.main import app  # noqa: E402


def test_sampling_params_passed_to_chat():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}

        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "stop": ["STOP_HERE", "AND_HERE"],
            "presence_penalty": 0.5,
            "repetition_penalty": 1.2,
            "min_p": 0.05,
            "top_k": 40,
            "seed": 42,
            "temperature": 0.8,
            "top_p": 0.95,
            "tools": [{"type": "function", "function": {"name": "test"}}],
            "tool_choice": "auto",
            "response_format": {"type": "json_object"},
        }

        with patch.object(mock_batched_instance, "chat", side_effect=mock_chat) as mock_chat_call:
            response = client.post("/v1/chat/completions", json=payload, headers=headers)
            assert response.status_code == 200

            kwargs = mock_chat_call.call_args.kwargs
            assert kwargs["stop"] == ["STOP_HERE", "AND_HERE"]
            assert kwargs["presence_penalty"] == 0.5
            assert kwargs["repetition_penalty"] == 1.2
            assert kwargs["min_p"] == 0.05
            assert kwargs["top_k"] == 40
            assert kwargs["seed"] == 42
            assert kwargs["temperature"] == 0.8
            assert kwargs["top_p"] == 0.95
            assert kwargs["tools"] == [{"type": "function", "function": {"name": "test"}}]
            assert kwargs["tool_choice"] == "auto"
            assert kwargs["response_format"] == {"type": "json_object"}


def test_sampling_params_passed_to_stream_chat():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}

        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stop": "SINGLE_STOP",
            "presence_penalty": -0.1,
            "repetition_penalty": 1.5,
            "min_p": 0.1,
            "top_k": 10,
        }

        with patch.object(
            mock_batched_instance, "stream_chat", side_effect=mock_stream_chat
        ) as mock_stream_call:
            response = client.post("/v1/chat/completions", json=payload, headers=headers)
            assert response.status_code == 200
            # Exhaust the stream
            list(response.iter_lines())

            kwargs = mock_stream_call.call_args.kwargs
            assert kwargs["stop"] == ["SINGLE_STOP"]  # Normalized to list
            assert kwargs["presence_penalty"] == -0.1
            assert kwargs["repetition_penalty"] == 1.5
            assert kwargs["min_p"] == 0.1
            assert kwargs["top_k"] == 10
