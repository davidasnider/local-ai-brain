import argparse
import json
import os
import sys
import urllib.request
import uuid
from typing import Dict, List

# Maximum audio file size accepted by the STT upload (25 MB)
MAX_STT_FILE_SIZE = 25 * 1024 * 1024

# Chunk size used when streaming TTS audio to disk (8 KB)
_TTS_CHUNK_SIZE = 8 * 1024

# ANSI escape codes for colors
COLOR_RESET = "\033[0m"
COLOR_USER = "\033[94m"  # Blue
COLOR_ASSISTANT = "\033[92m"  # Green
COLOR_SYSTEM = "\033[93m"  # Yellow
COLOR_ERROR = "\033[91m"  # Red
COLOR_PROMPT = "\033[1;36m"  # Cyan bold


def get_api_key() -> str:
    key = os.environ.get("LOCAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        print(
            f"{COLOR_ERROR}Error: neither LOCAL_API_KEY nor OPENAI_API_KEY "
            f"environment variable is set.{COLOR_RESET}"
        )
        sys.exit(1)
    return key


def get_base_url() -> str:
    return os.environ.get("OPENAI_API_BASE", "http://localhost:8000/v1")


def tts(text: str, base_url: str, api_key: str):
    url = f"{base_url.rstrip('/')}/audio/speech"
    data: Dict = {"input": text, "voice": "af_heart"}
    tts_model = os.environ.get("LOCAL_BRAIN_TTS_MODEL")
    if tts_model:
        data["model"] = tts_model
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )

    try:
        print(f"{COLOR_SYSTEM}Generating audio...{COLOR_RESET}")
        with urllib.request.urlopen(req, timeout=60) as response:
            output_file = "speech.wav"
            with open(output_file, "wb") as f:
                while True:
                    chunk = response.read(_TTS_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
            print(f"{COLOR_SYSTEM}Saved TTS output to {output_file}{COLOR_RESET}")
    except Exception as e:
        print(f"{COLOR_ERROR}TTS Error: {e}{COLOR_RESET}")


def stt(filepath: str, base_url: str, api_key: str):
    if not os.path.exists(filepath):
        print(f"{COLOR_ERROR}Error: File not found: {filepath}{COLOR_RESET}")
        return

    file_size = os.path.getsize(filepath)
    if file_size > MAX_STT_FILE_SIZE:
        print(
            f"{COLOR_ERROR}Error: File too large "
            f"({file_size / 1024 / 1024:.1f} MB). "
            f"Maximum allowed is {MAX_STT_FILE_SIZE // (1024 * 1024)} MB.{COLOR_RESET}"
        )
        return

    url = f"{base_url.rstrip('/')}/audio/transcriptions"

    # Simple multipart/form-data creation
    boundary = uuid.uuid4().hex

    with open(filepath, "rb") as f:
        file_content = f.read()

    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    filename = os.path.basename(filepath)
    content_disp = f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
    body.extend(content_disp.encode("utf-8"))
    body.extend(b"Content-Type: audio/wav\r\n\r\n")
    body.extend(file_content)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        print(f"{COLOR_SYSTEM}Transcribing...{COLOR_RESET}")
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            print(f"{COLOR_ASSISTANT}Transcription: {result.get('text', '')}{COLOR_RESET}")
    except Exception as e:
        print(f"{COLOR_ERROR}STT Error: {e}{COLOR_RESET}")


def chat(messages: List[Dict[str, str]], base_url: str, api_key: str):
    url = f"{base_url.rstrip('/')}/chat/completions"
    data: Dict = {"messages": messages, "stream": True}
    chat_model = os.environ.get("LOCAL_BRAIN_CHAT_MODEL")
    if chat_model:
        data["model"] = chat_model

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )

    try:
        print(f"{COLOR_ASSISTANT}Assistant: {COLOR_RESET}", end="", flush=True)
        with urllib.request.urlopen(req, timeout=60) as response:
            full_response = ""
            for line in response:
                line = line.decode("utf-8").strip()
                if line == "data: [DONE]":
                    break
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        if chunk["choices"] and chunk["choices"][0].get("delta", {}).get("content"):
                            content = chunk["choices"][0]["delta"]["content"]
                            print(f"{COLOR_ASSISTANT}{content}{COLOR_RESET}", end="", flush=True)
                            full_response += content
                    except json.JSONDecodeError:
                        pass
            print()
            return full_response
    except Exception as e:
        print(f"\n{COLOR_ERROR}Chat Error: {e}{COLOR_RESET}")
        return None


def print_help():
    print(f"{COLOR_SYSTEM}Local AI Brain CLI{COLOR_RESET}")
    print("Type your message to chat, or use one of the following commands:")
    print("  /tts <text>     - Synthesize speech to speech.wav")
    print("  /stt <filepath> - Transcribe an audio file")
    print("  /clear          - Clear chat history")
    print("  /help           - Show this help message")
    print("  /exit or quit   - Exit the application")


def main():
    parser = argparse.ArgumentParser(description="Local AI Brain CLI")
    parser.add_argument("--help-cmd", action="store_true", help="Print help and exit")
    args = parser.parse_args()

    if args.help_cmd:
        print_help()
        sys.exit(0)

    api_key = get_api_key()
    base_url = get_base_url()

    print(f"{COLOR_SYSTEM}Welcome to Local AI Brain CLI. Type /help for commands.{COLOR_RESET}")
    print(f"{COLOR_SYSTEM}Using Base URL: {base_url}{COLOR_RESET}")

    messages = []

    while True:
        try:
            user_input = input(f"\n{COLOR_PROMPT}❯ {COLOR_RESET}")
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not user_input.strip():
            continue

        user_input_stripped = user_input.strip()

        if user_input_stripped.lower() in ("/exit", "quit", "exit"):
            break

        if user_input_stripped.lower() == "/help":
            print_help()
            continue

        if user_input_stripped.lower() == "/clear":
            messages = []
            print(f"{COLOR_SYSTEM}Chat history cleared.{COLOR_RESET}")
            continue

        if user_input_stripped.startswith("/tts"):
            text = user_input_stripped[4:].strip()
            if text:
                tts(text, base_url, api_key)
            else:
                print(f"{COLOR_ERROR}Usage: /tts <text>{COLOR_RESET}")
            continue

        if user_input_stripped.startswith("/stt"):
            filepath = user_input_stripped[4:].strip()
            if filepath:
                stt(filepath, base_url, api_key)
            else:
                print(f"{COLOR_ERROR}Usage: /stt <filepath>{COLOR_RESET}")
            continue

        if user_input_stripped.startswith("/"):
            print(f"{COLOR_ERROR}Unknown command. Type /help for available commands.{COLOR_RESET}")
            continue

        # Standard chat message
        messages.append({"role": "user", "content": user_input})
        response = chat(messages, base_url, api_key)
        if response:
            messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
