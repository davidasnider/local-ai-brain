import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Dict, List

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
    data = {"input": text, "voice": "af_heart"}

    model = os.environ.get("LOCAL_BRAIN_TTS_MODEL")
    if model:
        data["model"] = model

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
                while chunk := response.read(8192):
                    f.write(chunk)
            print(f"{COLOR_SYSTEM}Saved TTS output to {output_file}{COLOR_RESET}")
    except urllib.error.HTTPError as e:
        error_msg = e.reason
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            if "detail" in err_data:
                error_msg = err_data["detail"]
        except Exception:
            pass
        print(f"{COLOR_ERROR}TTS HTTP Error: {e.code} - {error_msg}{COLOR_RESET}")
    except Exception as e:
        print(f"{COLOR_ERROR}TTS Error: {e}{COLOR_RESET}")


def stt(filepath: str, base_url: str, api_key: str):
    if not os.path.exists(filepath):
        print(f"{COLOR_ERROR}Error: File not found: {filepath}{COLOR_RESET}")
        return

    # Enforce 25MB limit
    if os.path.getsize(filepath) > 25 * 1024 * 1024:
        print(f"{COLOR_ERROR}Error: File too large (> 25MB): {filepath}{COLOR_RESET}")
        return

    url = f"{base_url.rstrip('/')}/audio/transcriptions"
    boundary = uuid.uuid4().hex

    def body_generator():
        yield f"--{boundary}\r\n".encode("utf-8")
        filename = os.path.basename(filepath)
        yield (f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n').encode(
            "utf-8"
        )
        yield b"Content-Type: audio/wav\r\n\r\n"
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                yield chunk
        yield f"\r\n--{boundary}--\r\n".encode("utf-8")

    class StreamingBody:
        def __init__(self, gen):
            self.gen = gen
            self.current_chunk = b""

        def read(self, size=-1):
            try:
                if size < 0:
                    res = bytearray(self.current_chunk)
                    self.current_chunk = b""
                    for chunk in self.gen:
                        res.extend(chunk)
                    return bytes(res)

                if not self.current_chunk:
                    self.current_chunk = next(self.gen)

                chunk = self.current_chunk[:size]
                self.current_chunk = self.current_chunk[size:]
                return chunk
            except StopIteration:
                return b""

    # urllib.request.urlopen can take an iterable/file-like object for data
    # but it needs a __len__ or it won't set Content-Length, which might be okay
    # or it might require a file-like object with read().

    # Calculate Content-Length for the multipart body
    filename = os.path.basename(filepath)
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    content_length = len(header) + os.path.getsize(filepath) + len(footer)

    req = urllib.request.Request(
        url,
        data=StreamingBody(body_generator()),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}",
            "Content-Length": str(content_length),
        },
    )

    try:
        print(f"{COLOR_SYSTEM}Transcribing...{COLOR_RESET}")
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            print(f"{COLOR_ASSISTANT}Transcription: {result.get('text', '')}{COLOR_RESET}")
    except urllib.error.HTTPError as e:
        error_msg = e.reason
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            if "detail" in err_data:
                error_msg = err_data["detail"]
        except Exception:
            pass
        print(f"{COLOR_ERROR}STT HTTP Error: {e.code} - {error_msg}{COLOR_RESET}")
    except Exception as e:
        print(f"{COLOR_ERROR}STT Error: {e}{COLOR_RESET}")


def chat(messages: List[Dict[str, str]], base_url: str, api_key: str):
    url = f"{base_url.rstrip('/')}/chat/completions"
    data = {"messages": messages, "stream": True}

    model = os.environ.get("LOCAL_BRAIN_CHAT_MODEL")
    if model:
        data["model"] = model

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
    except urllib.error.HTTPError as e:
        error_msg = e.reason
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            if "detail" in err_data:
                error_msg = err_data["detail"]
        except Exception:
            pass
        print(f"\n{COLOR_ERROR}Chat HTTP Error: {e.code} - {error_msg}{COLOR_RESET}")
        return None
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


def shutdown_processes(processes):
    """Gracefully terminate and then kill subprocesses."""
    for p in processes:
        if p.poll() is None:
            p.terminate()
    for p in processes:
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()


def serve():
    import shutil
    import subprocess
    import time

    print(f"{COLOR_SYSTEM}Starting Local AI Brain Microservices...{COLOR_RESET}")

    uv_bin = shutil.which("uv") or "uv"

    processes = []
    try:
        env_vars = dict(os.environ, PYTHONPATH="src")

        from local_ai_brain.config import settings

        print(f"{COLOR_SYSTEM}Starting vLLM engine on port 8001...{COLOR_RESET}")
        vllm_cmd = [
            uv_bin,
            "run",
            "python",
            "-m",
            "local_ai_brain.models.llm_server",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
            "--model",
            settings.QWEN_MODEL_PATH,
            "--api-key",
            settings.LOCAL_API_KEY,
            "--reasoning-parser",
            "qwen3",
            "--continuous-batching",
            "--max-kv-size",
            str(settings.LLM_MAX_KV_SIZE),
            "--prefill-step-size",
            str(settings.LLM_PREFILL_STEP_SIZE),
            "--max-num-seqs",
            str(settings.LLM_MAX_NUM_SEQS),
        ]

        if settings.LLM_SPECPREFILL_ENABLED:
            vllm_cmd.extend(["--speculative-draft-model", settings.LLM_SPECPREFILL_DRAFT_MODEL])

        if settings.LLM_KV_CACHE_QUANTIZATION:
            vllm_cmd.extend(["--kv-cache-bits", str(settings.LLM_KV_CACHE_BITS)])

        p_vllm = subprocess.Popen(vllm_cmd, env=env_vars)
        processes.append(p_vllm)

        print(f"{COLOR_SYSTEM}Starting STT Server on port 8002...{COLOR_RESET}")
        p_stt = subprocess.Popen(
            [
                uv_bin,
                "run",
                "uvicorn",
                "local_ai_brain.models.stt_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8002",
            ],
            env=env_vars,
        )
        processes.append(p_stt)

        print(f"{COLOR_SYSTEM}Starting TTS Server on port 8003...{COLOR_RESET}")
        p_tts = subprocess.Popen(
            [
                uv_bin,
                "run",
                "uvicorn",
                "local_ai_brain.models.tts_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8003",
            ],
            env=env_vars,
        )
        processes.append(p_tts)

        print(f"{COLOR_SYSTEM}Starting API Gateway (Proxy) on port 8000...{COLOR_RESET}")
        proxy_env = dict(
            env_vars,
            VLLM_URL="http://127.0.0.1:8001",
            STT_URL="http://127.0.0.1:8002",
            TTS_URL="http://127.0.0.1:8003",
        )
        p_proxy = subprocess.Popen(
            [
                uv_bin,
                "run",
                "uvicorn",
                "local_ai_brain.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            env=proxy_env,
        )
        processes.append(p_proxy)

        while True:
            for p in processes:
                if p.poll() is not None:
                    print(
                        f"{COLOR_ERROR}A subprocess exited unexpectedly "
                        f"(exit code {p.returncode}). Shutting down...{COLOR_RESET}"
                    )
                    shutdown_processes(processes)
                    sys.exit(1)
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"{COLOR_SYSTEM}Shutting down servers...{COLOR_RESET}")
        shutdown_processes(processes)
        # Normal exit on Ctrl+C
        sys.exit(0)
    except Exception as e:
        print(f"{COLOR_ERROR}Fatal error in serve: {e}{COLOR_RESET}")
        shutdown_processes(processes)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Local AI Brain CLI")
    parser.add_argument("--help-cmd", action="store_true", help="Print help and exit")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the API servers")

    args = parser.parse_args()

    if args.command == "serve":
        serve()
        return

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
