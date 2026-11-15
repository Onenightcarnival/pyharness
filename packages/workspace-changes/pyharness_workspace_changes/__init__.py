"""
``ctx.workspaceChanges``: which files each turn changed, from git work-tree snapshots.

| moment             | work                                                                                   |
|--------------------|----------------------------------------------------------------------------------------|
| ``agent/turn-start`` | snapshot the session workspace's work tree into a private object directory (tree id) |
| ``agent/turn-end``   | second snapshot; ``diff-tree`` between the two → summary; ``turn.extras["changes"]``   |

| member                              | contract                                                                 |
|-------------------------------------|--------------------------------------------------------------------------|
| ``summaries(session_id)``           | summaries of the session's turns that changed files, oldest first (stored) |
| ``summary(session_id, run_id)``     | one summary or ``None``                                                  |
| ``diff(session_id, run_id, index)`` | hunks of the listed file; ``available: False`` after a restart (see below)  |

``available: False``: the process that recorded the diff is gone.

Summary: ``{run_id, session_id, seq, at, after, workspace, repo, files: [{path, display, status, added, deleted,
binary}], total, added, deleted}``. ``path`` is repository-relative, ``display`` is relative to the workspace root
(``../x`` above it). ``after`` is the number of session messages when the turn ended, where the Web UI places the
card.

Snapshots never touch the repository: a copy of its index and a private object directory (``GIT_OBJECT_DIRECTORY``)
with the repository's objects as a read-only alternate hold the trees; ``.gitignore`` applies, so ignored files are
not listed. Workspaces outside a git repository, and turns that changed nothing, produce no summary. Diffs live only
while this process runs; summaries persist in ``ctx.store``.

| module      | content                                                        |
|-------------|----------------------------------------------------------------|
| ``service`` | ``WorkspaceChangesService``, ``Config``, the store namespace   |
| ``git``     | ``Repo``, ``GitError``, ``parse_unified``                      |
"""

from __future__ import annotations

from .git import GitError, parse_unified
from .service import NAMESPACE, Config, WorkspaceChangesService

__all__ = ["NAMESPACE", "Config", "GitError", "WorkspaceChangesService", "parse_unified"]
