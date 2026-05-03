from local_ai_brain.schemas import (
    ChatCompletionRequest,
    ChatMessage,
    SpeechRequest,
    TranscriptionResponse,
)


def test_speech_request():
    req = SpeechRequest(input="hello", voice="af_heart")
    assert req.input == "hello"
    assert req.voice == "af_heart"
    assert req.response_format == "wav"


def test_transcription_response():
    resp = TranscriptionResponse(text="test")
    assert resp.text == "test"


def test_chat_schemas():
    msg = ChatMessage(role="user", content="hello")
    req = ChatCompletionRequest(messages=[msg])
    assert req.messages[0].content == "hello"
    assert req.stream is False
