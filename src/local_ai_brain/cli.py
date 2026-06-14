import argparse
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Dict, List, Optional

from loguru import logger

from local_ai_brain.logging import configure_logging

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
    for name, p in processes.items():
        if p.poll() is None:
            logger.info(f"Shutting down {name}...")
            p.terminate()
    for name, p in processes.items():
        try:
            p.wait(timeout=5)
        except Exception:
            logger.warning(f"Killing {name} (timed out during terminate)...")
            p.kill()


def get_active_client_pids(ports: Optional[list[int]] = None) -> dict[int, int]:
    """Returns a dict mapping client port to PID for local established connections.

    Args:
        ports (list): List of destination ports to filter by. Defaults to [8000, 8001, 8002, 8003].

    Returns:
        dict: Mapping of source port (int) to PID (int).
    """
    if ports is None:
        ports = [8000, 8001, 8002, 8003]
    client_pid_map = {}
    try:
        # lsof -iTCP:8000,8001,... -sTCP:ESTABLISHED -n -P
        port_spec = ",".join(map(str, ports))
        cmd = ["lsof", f"-iTCP:{port_spec}", "-sTCP:ESTABLISHED", "-n", "-P"]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 9 and "TCP" in line:
                try:
                    pid = int(parts[1])
                    name = parts[8]
                    # name looks like localhost:52345->localhost:8000
                    if "->" in name:
                        src, _ = name.split("->", 1)
                        src_port = int(src.split(":")[-1])
                        client_pid_map[src_port] = pid
                except (ValueError, IndexError):
                    continue
    except (subprocess.CalledProcessError, FileNotFoundError):
        # lsof might not be installed or might return non-zero if no matches
        pass
    except Exception as e:
        logger.debug(f"Error in get_active_client_pids: {e}")
    return client_pid_map


def trace():
    """Tails the local-ai-brain log file and maps incoming requests to client PIDs.

    Provides real-time visibility into which local processes are talking to the brain.
    Supports an interactive 'k' command to kill identified client processes.
    """
    print(f"{COLOR_SYSTEM}Starting real-time conversation trace...{COLOR_RESET}")
    print(f"{COLOR_SYSTEM}Press 'k' and enter to kill a process.{COLOR_RESET}")
    print(f"{COLOR_SYSTEM}Press Ctrl+C to exit.{COLOR_RESET}")

    log_path = os.path.expanduser(
        os.getenv("LOCAL_AI_BRAIN_LOG_PATH", "~/Library/Logs/local-ai-brain.log")
    )
    if not os.path.exists(log_path):
        print(f"{COLOR_ERROR}Log file not found: {log_path}{COLOR_RESET}")
        sys.exit(1)

    try:
        with open(log_path, "r") as f:
            # Seek to end
            f.seek(0, 2)
            pattern = re.compile(
                r"Incoming chat from (?:.+):(\d+) - (?:\"(.*)\"|\[PROMPT REDACTED\])"
            )

            while True:
                line = f.readline()
                if line:
                    match = pattern.search(line)
                    if match:
                        port = int(match.group(1))
                        msg = match.group(2) or "[PROMPT REDACTED]"

                        client_pids = get_active_client_pids()
                        pid = client_pids.get(port)

                        if pid:
                            try:
                                cmdline = (
                                    subprocess.check_output(
                                        ["ps", "-p", str(pid), "-o", "command="]
                                    )
                                    .decode()
                                    .strip()
                                )
                                print(
                                    f"{COLOR_PROMPT}[PID {pid}]{COLOR_RESET} "
                                    f"{COLOR_ASSISTANT}{cmdline}{COLOR_RESET}"
                                )
                            except subprocess.CalledProcessError:
                                print(f"{COLOR_PROMPT}[PID {pid} (Unknown)]{COLOR_RESET}")
                        else:
                            print(f"{COLOR_PROMPT}[Port {port}]{COLOR_RESET}")

                        print(f"{COLOR_USER}Says:{COLOR_RESET} {msg}\n")
                    else:
                        # Log completion/stats if needed, or ignore
                        pass
                else:
                    # Check for interactive kill command
                    i, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if i:
                        user_input = sys.stdin.readline().strip().lower()
                        if user_input == "":
                            # stdin closed/EOF — stop monitoring
                            break
                        if user_input == "k":
                            try:
                                pid_to_kill = input(
                                    f"{COLOR_SYSTEM}Enter PID to kill: {COLOR_RESET}"
                                )
                                pid_int = int(pid_to_kill)
                                if pid_int <= 0:
                                    raise ValueError("PID must be a positive integer")
                                os.kill(pid_int, signal.SIGKILL)
                                print(
                                    f"{COLOR_ASSISTANT}Successfully killed PID "
                                    f"{pid_int}{COLOR_RESET}\n"
                                )
                            except ValueError:
                                print(f"{COLOR_ERROR}Invalid PID{COLOR_RESET}\n")
                            except Exception as e:
                                print(f"{COLOR_ERROR}Failed to kill: {e}{COLOR_RESET}\n")
                    else:
                        time.sleep(0.05)
    except KeyboardInterrupt:
        print(f"\n{COLOR_SYSTEM}Exiting trace...{COLOR_RESET}")
        sys.exit(0)


def serve():
    import shutil
    import subprocess
    import time

    from local_ai_brain.config import settings

    # Configure logging for both file and console
    configure_logging(testing=settings.TESTING)
    logger.info("Starting Local AI Brain Microservices...")

    uv_bin = shutil.which("uv") or "uv"
    env_vars = dict(
        os.environ,
        PYTHONPATH="src",
        VLLM_API_KEY=settings.LOCAL_API_KEY,
        LOCAL_API_KEY=settings.LOCAL_API_KEY,
        OPENAI_API_KEY=settings.LOCAL_API_KEY,
    )

    # Crash log configuration
    crash_log_path = os.path.abspath(
        os.path.expanduser(
            os.getenv("LOCAL_AI_BRAIN_CRASH_LOG", "~/Library/Logs/local-ai-brain-crash.log")
        )
    )
    os.makedirs(os.path.dirname(crash_log_path), exist_ok=True)

    def start_subprocess(name, cmd, env):
        logger.info(f"Starting {name}...")
        # Open in append mode to preserve history
        with open(crash_log_path, "a") as log_file:
            log_file.write(f"\n--- Starting {name} at {time.ctime()} ---\n")
            log_file.flush()
            return subprocess.Popen(cmd, env=env, stderr=log_file, stdout=subprocess.DEVNULL)

    # Dictionary to track processes and their restart configurations
    service_configs = {
        "LLM Server": {
            "cmd": [
                uv_bin,
                "run",
                "python",
                "-m",
                "local_ai_brain.models.llm_server",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ],
            "env": env_vars,
        },
        "STT Server": {
            "cmd": [
                uv_bin,
                "run",
                "uvicorn",
                "local_ai_brain.models.stt_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8002",
            ],
            "env": env_vars,
        },
        "TTS Server": {
            "cmd": [
                uv_bin,
                "run",
                "uvicorn",
                "local_ai_brain.models.tts_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8003",
            ],
            "env": env_vars,
        },
        "API Gateway": {
            "cmd": [
                uv_bin,
                "run",
                "uvicorn",
                "local_ai_brain.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            "env": dict(
                env_vars,
                VLLM_URL="http://127.0.0.1:8001",
                STT_URL="http://127.0.0.1:8002",
                TTS_URL="http://127.0.0.1:8003",
            ),
        },
    }

    processes = {}
    for name, cfg in service_configs.items():
        processes[name] = start_subprocess(name, cfg["cmd"], cfg["env"])

    try:
        while True:
            for name, p in list(processes.items()):
                exit_code = p.poll()
                if exit_code is not None:
                    logger.error(
                        f"{name} exited unexpectedly (exit code {exit_code}). "
                        f"Check {crash_log_path} for details. Restarting in 5s..."
                    )
                    # Small delay before restart to prevent tight loops
                    time.sleep(5)
                    processes[name] = start_subprocess(
                        name, service_configs[name]["cmd"], service_configs[name]["env"]
                    )
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down servers (KeyboardInterrupt)...")
        shutdown_processes(processes)
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error in serve: {e}")
        shutdown_processes(processes)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Local AI Brain CLI")
    parser.add_argument("--help-cmd", action="store_true", help="Print help and exit")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the API servers")
    subparsers.add_parser("trace", help="Trace conversations in real time")

    args = parser.parse_args()

    if args.command == "serve":
        serve()
        return

    if args.command == "trace":
        trace()
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
