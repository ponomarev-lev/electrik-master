from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
RUNTIME_DIR = ROOT_DIR / ".run"
STATE_FILE = RUNTIME_DIR / "server_state.json"
LOG_FILE = RUNTIME_DIR / "server.log"
REQUIREMENTS_HASH_FILE = RUNTIME_DIR / "requirements.sha256"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT_START = 8000
DEFAULT_PORT_END = 8100
CHECK_TIMEOUT_SECONDS = 30.0


def _venv_python_path() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    python3_path = VENV_DIR / "bin" / "python3"
    if python3_path.exists():
        return python3_path
    return VENV_DIR / "bin" / "python"


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, cwd=str(ROOT_DIR), check=True)


def _ensure_virtualenv() -> Path:
    python_path = _venv_python_path()
    if not python_path.exists():
        _run_checked([sys.executable, "-m", "venv", str(VENV_DIR)])
    return _venv_python_path()


def _ensure_dependencies(python_path: Path) -> None:
    requirements_file = ROOT_DIR / "requirements.txt"
    requirements_hash = hashlib.sha256(requirements_file.read_bytes()).hexdigest()
    current_hash = (
        REQUIREMENTS_HASH_FILE.read_text(encoding="utf-8").strip()
        if REQUIREMENTS_HASH_FILE.exists()
        else ""
    )
    if current_hash == requirements_hash:
        return
    _run_checked([str(python_path), "-m", "pip", "install", "-r", str(requirements_file)])
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    REQUIREMENTS_HASH_FILE.write_text(requirements_hash, encoding="utf-8")


def _run_migrations(python_path: Path) -> None:
    alembic_config = ROOT_DIR / "alembic.ini"
    if alembic_config.exists():
        _run_checked([str(python_path), "-m", "alembic", "upgrade", "head"])


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            cwd=str(ROOT_DIR),
            check=False,
            capture_output=True,
            text=True,
        )
        output = result.stdout.strip()
        return bool(output) and not output.startswith("INFO:")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _load_state() -> dict[str, object] | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_state(state: dict[str, object]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def _find_free_port(start: int = DEFAULT_PORT_START, end: int = DEFAULT_PORT_END) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((DEFAULT_HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free ports found in range {start}-{end}.")


def _server_is_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=1):
            return True
    except URLError:
        return False


def _wait_until_ready(url: str, timeout_seconds: float = CHECK_TIMEOUT_SECONDS) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _server_is_ready(url):
            return True
        time.sleep(0.3)
    return False


def _terminate_process(pid: int) -> None:
    if not _is_process_running(pid):
        return

    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], cwd=str(ROOT_DIR), check=False)
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 6
    while time.time() < deadline:
        if not _is_process_running(pid):
            return
        time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)


def _start() -> int:
    state = _load_state()
    if state is not None:
        pid = int(state.get("pid", 0))
        if _is_process_running(pid):
            url = str(state.get("url", f"http://{DEFAULT_HOST}:{state.get('port', DEFAULT_PORT_START)}/employees"))
            print(f"Server already running: {url}")
            webbrowser.open(url)
            return 0
        _clear_state()

    python_path = _ensure_virtualenv()
    _ensure_dependencies(python_path)
    _run_migrations(python_path)

    port = _find_free_port()
    app_url = f"http://{DEFAULT_HOST}:{port}/employees"

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log_handle:
        popen_kwargs: dict[str, object] = {
            "cwd": str(ROOT_DIR),
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(
            [str(python_path), "-m", "uvicorn", "app.main:app", "--host", DEFAULT_HOST, "--port", str(port)],
            **popen_kwargs,
        )

    if not _wait_until_ready(app_url):
        _terminate_process(process.pid)
        raise RuntimeError(f"Server failed to start. Check log: {LOG_FILE}")

    _save_state(
        {
            "pid": process.pid,
            "port": port,
            "url": app_url,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log_file": str(LOG_FILE),
        }
    )
    webbrowser.open(app_url)
    print(f"Server started: {app_url}")
    print(f"Log file: {LOG_FILE}")
    return 0


def _stop() -> int:
    state = _load_state()
    if state is None:
        print("Server is not running.")
        return 0

    pid = int(state.get("pid", 0))
    if _is_process_running(pid):
        _terminate_process(pid)
        print("Server stopped.")
    else:
        print("Server process was not running.")
    _clear_state()
    return 0


def _status() -> int:
    state = _load_state()
    if state is None:
        print("Server is not running.")
        return 0

    pid = int(state.get("pid", 0))
    if _is_process_running(pid):
        print(f"Server is running: {state.get('url')}")
        print(f"PID: {pid}")
        print(f"Log file: {state.get('log_file', str(LOG_FILE))}")
        return 0

    print("Server state exists, but process is not running.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="start", choices=["start", "stop", "status"])
    args = parser.parse_args()

    if args.command == "start":
        return _start()
    if args.command == "stop":
        return _stop()
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
