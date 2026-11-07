"""``ctx.terminal``: a persistent shell per session for the agent, background jobs, and PTY terminals for the Web UI.

- ``bash``: tool; one bash process per agent session (thread id), started in the workspace root; working directory
  and environment persist between calls; stdin is ``/dev/null``; a timeout kills and restarts the shell.
- jobs: ``run_in_background`` starts ``bash -c`` with its output in a log file; ``job_output`` / ``job_list`` /
  ``job_kill``; ``GET /jobs``, ``GET /jobs/{id}``, ``DELETE /jobs/{id}``.
- terminals: PTY sessions for the right-sidebar terminal tab: ``POST /terminals``, ``GET /terminals``,
  ``DELETE /terminals/{id}``, WebSocket ``/terminals/{id}/ws`` (binary frames: bytes; text frames: JSON control).

The shell tools carry the ``shell`` tag: the agent loop leaves them out in read-only mode. ``bash`` and
``run_in_background`` are gated by ``approval`` (approval prompts in workspace-write mode; none in full access).
PTY terminals need ``pty`` (POSIX); elsewhere the terminal tab reports itself unavailable.
"""

from .jobs import Job, JobRegistry
from .pty import Terminal, pty_available
from .service import Config, TerminalService
from .shell import ShellSession, clip

__all__ = ["Config", "Job", "JobRegistry", "ShellSession", "Terminal", "TerminalService", "clip", "pty_available"]
