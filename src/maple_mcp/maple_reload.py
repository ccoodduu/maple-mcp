"""Talking to a running Maple, over the in-JVM agent's TCP port.

Agent-only by design: the single requirement is the `-javaagent` line in
launch.ini. Driving the GUI with synthetic keystrokes was tried instead and
removed — it needed a second install and a specific window layout, and it hid
the real cause whenever it silently did nothing. Failures here name the
requirement rather than falling back to something flakier.
"""
AGENT_PORT = 19876

AGENT_MISSING = (
    "Maple's reload agent is not reachable on port 19876. Check that Maple is "
    "running and that launch.ini has: "
    "java_args=-javaagent:<PROJECT_DIR>/reload-agent.jar"
)


def get_open_document_path() -> str | None:
    """Path of the document currently open in Maple, or None."""
    result = _send_agent("getpath")
    if result and not result.startswith("error"):
        return result
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
    return _send_agent("save") == "ok"


def reload_in_maple(file_path: str) -> bool:
    return _send_agent(f"reload {file_path}") == "ok"


def open_in_maple(file_path: str) -> tuple[bool, str]:
    """Open a .mw in Maple. Returns (ok, detail)."""
    result = _send_agent(f"open {file_path}")
    if result is None:
        return False, AGENT_MISSING
    return result == "ok", result


def reload_in_maple_async(file_path: str):
    """Fire-and-forget reload - don't wait for completion."""
    import threading
    threading.Thread(
        target=reload_in_maple, args=(file_path,), daemon=True
    ).start()


def eval_new_in_maple(timeout: int = 120) -> str | None:
    """Ask the agent to run the executable groups that have no output yet (the
    just-written ones), wait for the kernel, and save. Returns the agent's
    response string, or None if the agent isn't reachable. Needs a long socket
    timeout because execution + save happen before the agent replies."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", AGENT_PORT))
        s.sendall(b"evalnew\n")
        resp = s.recv(4096).decode().strip()
        s.close()
        return resp
    except (ConnectionRefusedError, socket.timeout, OSError):
        return None
