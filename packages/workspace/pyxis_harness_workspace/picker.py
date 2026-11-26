from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

# How a dialog's process runs. Windows: its output is UTF-8, and it opens no console window of its own.
PROCESS: dict[str, Any] = (
    {"encoding": "utf-8", "errors": "replace", "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if sys.platform == "win32"
    else {}
)

# The owner is a topmost form: the dialog opens in front of the browser instead of behind it. An error stops the
# script with a non-zero exit code; the path is written as UTF-8 without a byte-order mark.
POWERSHELL = dedent(
    """
    $ErrorActionPreference = 'Stop';
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false;
    Add-Type -AssemblyName System.Windows.Forms;
    [System.Windows.Forms.Application]::EnableVisualStyles();
    $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false };
    $d = New-Object System.Windows.Forms.FolderBrowserDialog;
    $d.Description = '__PROMPT__'; $d.ShowNewFolderButton = $true;
    if ($d.ShowDialog($owner) -eq 'OK') { Write-Output $d.SelectedPath };
    $owner.Dispose()
    """
).strip()

# The interpreter's own Tk dialog: no PowerShell, no execution policy.
TK = dedent(
    """
    import sys, tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    chosen = filedialog.askdirectory(parent=root, title=sys.argv[1], mustexist=True)
    root.destroy()
    sys.stdout.reconfigure(encoding="utf-8")
    print(chosen or "")
    """
).strip()


@dataclass(frozen=True)
class Dialog:
    """
    One way to open a folder dialog: a command that prints the chosen directory.

    | exit code | output | outcome                                                    |
    |-----------|--------|------------------------------------------------------------|
    | 0         | a path | chosen                                                     |
    | 0         | empty  | cancelled                                                  |
    | other     |        | cancelled when it matches ``cancelled``; otherwise failed  |
    """

    name: str
    command: list[str]
    cancel_codes: tuple[int, ...] = ()  # exit codes of a cancelled dialog
    cancel_text: str = ""  # text in the error output of a cancelled dialog; empty: the exit code decides

    def cancelled(self, code: int, error: str) -> bool:
        return code in self.cancel_codes and self.cancel_text in error

    def outcome(self, code: int, output: str, error: str) -> tuple[str, str]:
        """``("chosen", path)``, ``("cancelled", "")`` or ``("failed", reason)``."""
        path = output.strip().lstrip("﻿")
        if code == 0:
            return ("chosen", path.rstrip("/") or "/") if path else ("cancelled", "")
        if self.cancelled(code, error):
            return "cancelled", ""
        lines = [line.strip() for line in error.splitlines() if line.strip()]
        return "failed", (lines[-1] if lines else f"exit code {code}")[:300]


def dialogs(prompt: str, command: list[str] | None = None) -> list[Dialog]:
    """
    Folder dialogs of this machine, in the order they are tried; ``command`` replaces them.

    | platform | dialogs                                                     |
    |----------|-------------------------------------------------------------|
    | macOS    | ``osascript``                                               |
    | Windows  | PowerShell (``powershell``, else ``pwsh``), then Tk         |
    | Linux    | ``zenity``, then ``kdialog``; with a display                |
    """
    if command:
        return [Dialog("command", list(command))]
    prompt = prompt.replace('"', "").replace("'", "")
    found: list[Dialog] = []
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = f'POSIX path of (choose folder with prompt "{prompt}")'
        found.append(Dialog("osascript", ["osascript", "-e", script], cancel_codes=(1,), cancel_text="-128"))
    elif sys.platform == "win32":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell:
            script = POWERSHELL.replace("__PROMPT__", prompt)
            found.append(
                Dialog("powershell", [shell, "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script])
            )
        found.append(Dialog("tk", [sys.executable, "-c", TK, prompt]))
    elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("zenity"):
            found.append(
                Dialog("zenity", ["zenity", "--file-selection", "--directory", f"--title={prompt}"], cancel_codes=(1,))
            )
        if shutil.which("kdialog"):
            command = ["kdialog", "--getexistingdirectory", str(Path.home()), "--title", prompt]
            found.append(Dialog("kdialog", command, cancel_codes=(1,)))
    return found


def run(dialog: Dialog, timeout: float) -> tuple[str, str]:
    """Open ``dialog`` and wait; its outcome. ``subprocess.TimeoutExpired`` when nobody answers in ``timeout``."""
    proc = subprocess.run(dialog.command, capture_output=True, text=True, timeout=timeout, check=False, **PROCESS)
    return dialog.outcome(proc.returncode, proc.stdout or "", proc.stderr or "")
