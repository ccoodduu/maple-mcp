import subprocess
import time
from pathlib import Path

AHK_SCRIPT = Path(__file__).resolve().parent.parent.parent / "maple_reload.ahk"
AHK_EXE = Path.home() / "AppData/Local/Programs/AutoHotkey/v2/AutoHotkey64.exe"


def _run_ahk(action: str, file_path: str = "") -> bool:
    if not AHK_EXE.exists() or not AHK_SCRIPT.exists():
        return False
    args = [str(AHK_EXE), str(AHK_SCRIPT), action]
    if file_path:
        args.append(file_path)
    try:
        subprocess.run(args, timeout=15)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_open_document_path() -> str | None:
    """Get the file path of the currently open Maple document."""
    result = _send_agent("getpath")
    if result and not result.startswith("error"):
        return result

    # Fallback: AHK window title
    if not AHK_EXE.exists() or not AHK_SCRIPT.exists():
        return None

    import re
    script = (
        '#SingleInstance Force\n'
        'SetTitleMatchMode 2\n'
        'if WinExist("Maple ahk_class AutoHotkeyGUI") {\n'
        '    title := WinGetTitle()\n'
        '    FileAppend title, "*"\n'
        '}\n'
        'ExitApp\n'
    )
    tmp = AHK_SCRIPT.parent / "maple_title_tmp.ahk"
    tmp.write_text(script)
    try:
        result = subprocess.run(
            [str(AHK_EXE), str(tmp)],
            timeout=5, capture_output=True, text=True
        )
        tmp.unlink(missing_ok=True)
        title = result.stdout.strip()
        match = re.match(r'(.+\.mw)', title)
        if match:
            return match.group(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        tmp.unlink(missing_ok=True)
    return None


def _send_agent(cmd: str) -> str | None:
    """Send command to Java Agent via TCP. Returns response or None if agent not running."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", AGENT_PORT))
        s.sendall(f"{cmd}\n".encode())
        response = s.recv(4096).decode().strip()
        s.close()
        return response
    except (ConnectionRefusedError, socket.timeout, OSError):
        return None


def save_in_maple() -> bool:
    result = _send_agent("save")
    if result is not None:
        return result == "ok"
    return _run_ahk("save")


AGENT_PORT = 19876


def reload_in_maple(file_path: str) -> bool:
    result = _send_agent(f"reload {file_path}")
    if result is not None:
        return result == "ok"
    return _run_ahk("reload", file_path)


def reload_in_maple_async(file_path: str):
    """Fire-and-forget reload - don't wait for completion."""
    import threading
    threading.Thread(
        target=reload_in_maple, args=(file_path,), daemon=True
    ).start()
