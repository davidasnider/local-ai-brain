"""Interactive CLI for Local AI Brain."""

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("OPENAI_API_BASE", "http://localhost:8000/v1")
API_KEY = os.environ.get("LOCAL_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
TTS_VOICE = os.environ.get("LOCAL_BRAIN_VOICE", "af_heart")

HELP_TEXT = """\
Available commands:
  /help           Show this help message.
  /clear          Clear the current chat history.
  /tts <text>     Generate speech from <text> and save to speech.wav.
  /stt <file>     Transcribe <file> using Speech-to-Text.
  /exit | quit    Exit the CLI.
Any other input is sent as a chat message to the LLM.\
"""


def _request_json(path: str, data: dict) -> dict:
    """POST a JSON payload and return the parsed JSON response."""
    url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    payload = json.dumps(data).encode()
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _request_multipart(path: str, filename: str, file_bytes: bytes, content_type: str) -> dict:
    """POST a multipart/form-data payload (single file field named 'file')."""
    url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    boundary = "----LocalBrainBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _request_audio(path: str, data: dict) -> bytes:
    """POST a JSON payload and return raw bytes (audio)."""
    url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    payload = json.dumps(data).encode()
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def _chat(messages: list[dict]) -> str:
    response = _request_json(
        "/chat/completions",
        {"messages": messages},
    )
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected API response format: {response}") from exc


def _tts(text: str) -> None:
    audio_data = _request_audio("/audio/speech", {"input": text, "voice": TTS_VOICE})
    with open("speech.wav", "wb") as f:
        f.write(audio_data)
    print("Audio saved to speech.wav")


def _stt(filepath: str) -> str:
    if not os.path.isfile(filepath):
        return f"File not found: {filepath}"
    with open(filepath, "rb") as f:
        content = f.read()
    filename = os.path.basename(filepath)
    content_type = mimetypes.guess_type(filename)[0] or "audio/wav"
    result = _request_multipart("/audio/transcriptions", filename, content, content_type)
    return result.get("text", "(no transcription returned)")


def main() -> None:
    if not API_KEY:
        print("Error: LOCAL_API_KEY or OPENAI_API_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    print("Local AI Brain CLI. Type /help for commands.", file=sys.stderr)
    messages: list[dict] = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.", file=sys.stderr)
            break

        if not user_input:
            continue

        parts = user_input.split(None, 1)
        cmd = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/exit", "quit"):
            print("Goodbye!")
            break
        elif cmd == "/help":
            print(HELP_TEXT)
        elif cmd == "/clear":
            messages.clear()
            print("Chat history cleared.")
        elif cmd == "/tts":
            if not arg:
                print("Usage: /tts <text>")
            else:
                try:
                    _tts(arg)
                except urllib.error.URLError as exc:
                    print(f"TTS error: {exc}")
        elif cmd == "/stt":
            if not arg:
                print("Usage: /stt <filepath>")
            else:
                try:
                    print(_stt(arg))
                except urllib.error.URLError as exc:
                    print(f"STT error: {exc}")
        else:
            messages.append({"role": "user", "content": user_input})
            try:
                reply = _chat(messages)
                messages.append({"role": "assistant", "content": reply})
                print(f"Assistant: {reply}")
            except (urllib.error.URLError, ValueError) as exc:
                print(f"Chat error: {exc}")
                messages.pop()  # remove the failed message


if __name__ == "__main__":
    main()
