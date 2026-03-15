import asyncio
import json
import uuid
from pathlib import Path


BRIDGE_DIR = Path("C:/Users/willi/mcp-servers/maple-mcp/.bridge")


class LiveConnection:
    def __init__(self):
        self._bridge_dir = BRIDGE_DIR
        self._req_file = self._bridge_dir / "request"
        self._resp_file = self._bridge_dir / "response"
        self._ready_file = self._bridge_dir / "ready"
        self._connected = False

    async def connect(self) -> str:
        if not self._ready_file.exists():
            self._connected = False
            raise ConnectionError(
                "Maple bridge is not running. "
                "Start it in Maple with: MapleMCP:-Start();"
            )

        if await self.ping():
            self._connected = True
            return "Connected to Maple bridge"

        self._connected = False
        raise ConnectionError(
            "Maple bridge ready file found but not responding to ping."
        )

    async def send_command(
        self, command: str, params: dict | None = None, timeout: float = 30.0
    ) -> dict:
        request = {
            "id": str(uuid.uuid4()),
            "command": command,
            "params": params or {},
        }

        # Clean up any stale files
        for f in [self._resp_file, self._req_file]:
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                await asyncio.sleep(0.1)
                try:
                    f.unlink()
                except OSError:
                    pass

        # Write request atomically (write to temp, then rename)
        tmp = self._req_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(request), encoding="utf-8")
        tmp.rename(self._req_file)

        # Poll for response
        elapsed = 0.0
        poll_interval = 0.05
        while elapsed < timeout:
            if self._resp_file.exists():
                try:
                    text = self._resp_file.read_text(encoding="utf-8")
                    self._resp_file.unlink()
                    return json.loads(text)
                except (json.JSONDecodeError, OSError):
                    # File might be partially written, retry
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    continue
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Maple bridge did not respond within {timeout}s")

    async def execute(self, statement: str) -> str:
        resp = await self.send_command("execute", {"statement": statement})
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def insert_input(self, content: str) -> str:
        resp = await self.send_command("insert_input", {"content": content})
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def execute_and_insert(self, statement: str) -> str:
        resp = await self.send_command("execute_and_insert", {"statement": statement})
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def get_variables(self) -> str:
        resp = await self.send_command("get_variables")
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def save_document(self) -> str:
        resp = await self.send_command("save_document")
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def get_worksheet_path(self) -> str:
        resp = await self.send_command("get_worksheet_path")
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def insert_text(self, text: str) -> str:
        resp = await self.send_command("insert_text", {"text": text})
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def display_file(self, path: str) -> str:
        resp = await self.send_command("display_file", {"path": path})
        if resp.get("status") == "error":
            return f"Error: {resp.get('error', 'unknown error')}"
        return resp.get("result", "")

    async def ping(self) -> bool:
        try:
            resp = await self.send_command("ping", timeout=3.0)
            return resp.get("status") == "ok" and resp.get("result") == "pong"
        except (ConnectionError, TimeoutError, OSError):
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self):
        self._connected = False
