"""Workspace provider: ``ctx.workspace`` (the workspace registry) and ``ctx.backend`` (the default deepagents backend).

| config           | backend               | agent file tools                                                     |
|------------------|-----------------------|----------------------------------------------------------------------|
| ``shell: false`` | ``FilesystemBackend`` | ``ls``, ``read_file``, ``write_file`` … on the workspace root        |
| ``shell: true``  | ``LocalShellBackend`` | the same plus ``execute``; approval unless ``shell_approval: false`` |

``virtual_mode``: agent paths start at ``/`` = root and stay inside it.

| member                       | contract                                                                  |
|------------------------------|---------------------------------------------------------------------------|
| ``default``                  | the configured workspace (``config.root``); ``root``, ``resolve`` … delegate to it |
| ``open(path)``               | a validated :class:`Workspace` for ``path``; ``None`` is the default       |
| ``backend_for(path, shell)`` | cached backend for a workspace; ``shell=False`` gives a filesystem-only one |
| ``recent()`` / ``remember`` / ``forget`` | workspaces used by sessions, kept in ``ctx.store``                |
| ``rename(path, name)``       | display name of a workspace (``None`` restores the directory name)       |
| ``browse(path)``             | one directory level: subdirectories only, for the in-app picker          |
| ``picker()``                 | ``native`` (an OS folder dialog on this machine) or ``browse``            |
| ``pick(prompt)``             | opens the OS folder dialog; the chosen absolute path, or ``None``        |

| platform | native dialog                                   |
|----------|-------------------------------------------------|
| macOS    | ``osascript`` ``choose folder``                 |
| Windows  | PowerShell ``FolderBrowserDialog``              |
| Linux    | ``zenity`` or ``kdialog`` when a display exists |

| harness home vs root     | effect                                         |
|--------------------------|------------------------------------------------|
| home inside root         | file tools denied on the home (read and write) |
| root inside home         | refused                                        |

| module        | content                                                   |
|---------------|-----------------------------------------------------------|
| ``config``    | ``Config``                                                |
| ``plugin``    | ``apply``                                                 |
| ``workspace`` | ``Workspace``, ``WorkspaceError``                         |
| ``registry``  | ``Workspaces``: open, backends, recent, picker, browse    |
"""

from __future__ import annotations

from .config import Config
from .plugin import apply, inject, name
from .registry import Workspaces
from .workspace import Workspace, WorkspaceError

__all__ = ["Config", "Workspace", "WorkspaceError", "Workspaces", "apply", "inject", "name"]
