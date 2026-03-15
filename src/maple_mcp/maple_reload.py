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
    """Get the file path of the currently open Maple document from the window title."""
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
        # Title format: "C:\path\to\file.mw - [Server N] - Maple 2025"
        match = re.match(r'(.+\.mw)', title)
        if match:
            return match.group(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        tmp.unlink(missing_ok=True)
    return None


def save_in_maple() -> bool:
    return _run_ahk("save")


def reload_in_maple(file_path: str) -> bool:
    return _run_ahk("reload", file_path)
