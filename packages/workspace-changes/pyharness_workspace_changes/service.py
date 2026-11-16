from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from pyharness import Service

from .git import GitError, Repo, _resolve_git_path, parse_unified

NAMESPACE = ("pyharness", "changes")


class Config(BaseModel):
    timeout_s: float = Field(
        30.0, description="Seconds one git command may run; a slower one abandons the turn's record."
    )
    max_files: int = Field(500, description="Files listed per summary; `total` still counts all of them.")
    context_lines: int = Field(3, description="Context lines around each hunk.")
    max_diff_bytes: int = Field(2_000_000, description="Largest unified diff served for one file.")


class WorkspaceChangesService(Service):
    """Per-turn changed-file summaries and diffs."""

    key = "workspaceChanges"
    name = "pyharness-workspace-changes"
    inject: ClassVar[list[str]] = ["agents", "workspace", "store"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self._repos: dict[str, Repo | None] = {}
        self._dirs: dict[str, Path] = {}  # session id -> private git directory
        self._turns: dict[str, dict[str, Any]] = {}  # run id -> {repo, base, session}
        self._trees: dict[tuple[str, str], tuple[Repo, str, str]] = {}  # (session, run) -> (repo, base, head)
        self._seq: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        self.ctx.on("agent/turn-start", self._on_start)
        self.ctx.on("agent/turn-end", self._on_end)

    async def stop(self) -> None:
        for path in self._dirs.values():
            shutil.rmtree(path, ignore_errors=True)
        self._dirs.clear()
        self._trees.clear()

    # ------------------------------------------------------------------ queries
    async def summaries(self, session_id: str) -> list[dict[str, Any]]:
        items = await self.ctx.store.asearch((*NAMESPACE, session_id), limit=1000)
        return sorted((dict(i.value) for i in items), key=lambda s: s.get("seq", 0))

    async def summary(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        item = await self.ctx.store.aget((*NAMESPACE, session_id), run_id)
        return dict(item.value) if item is not None else None

    async def diff(self, session_id: str, run_id: str, index: int) -> dict[str, Any]:
        summary = await self.summary(session_id, run_id)
        if summary is None:
            raise LookupError(f"no changes recorded for run {run_id!r}")
        if not 0 <= index < len(summary["files"]):
            raise LookupError(f"no file {index} in the summary")
        file = summary["files"][index]
        head = {"path": file["path"], "display": file["display"], "status": file["status"], "binary": file["binary"]}
        trees = self._trees.get((session_id, run_id))
        if trees is None:
            return {**head, "available": False, "hunks": []}
        if file["binary"]:
            return {**head, "available": True, "hunks": []}
        repo, base, after = trees
        out = await self._git(
            repo,
            "diff",
            f"-U{self.config.context_lines}",
            "--no-color",
            "--no-ext-diff",
            "--no-renames",
            base,
            after,
            "--",
            file["path"],
            env=self._env(session_id, repo),
            ok=(0, 1),
        )
        if len(out.encode("utf-8", "replace")) > self.config.max_diff_bytes:
            return {**head, "available": True, "oversized": True, "hunks": []}
        return {**head, "available": True, "hunks": parse_unified(out)}

    # ------------------------------------------------------------------ turns
    async def _on_start(self, turn: Any) -> None:
        try:
            record = await self.ctx.agents.get_session(turn.session_id)
            repo = await self._repo_for((record or {}).get("workspace"))
            if repo is None:
                return
            async with self._lock(turn.session_id):
                base = await self._snapshot(turn.session_id, repo)
            self._turns[turn.run_id] = {
                "repo": repo,
                "base": base,
                "session": turn.session_id,
                "workspace": self._workspace_root((record or {}).get("workspace")),
            }
        except Exception as exc:  # noqa: BLE001 - never break the turn
            self.ctx.logger.warning("workspace changes: baseline skipped for %s: %s", turn.session_id, exc)

    async def _on_end(self, turn: Any) -> None:
        info = self._turns.pop(turn.run_id, None)
        if info is None:
            return
        try:
            repo: Repo = info["repo"]
            async with self._lock(turn.session_id):
                head = await self._snapshot(turn.session_id, repo)
            if head == info["base"]:
                return
            files = await self._changed_files(turn.session_id, repo, info["base"], head, info["workspace"])
            if not files:
                return
            seq = self._seq.get(turn.session_id, len(await self.summaries(turn.session_id))) + 1
            self._seq[turn.session_id] = seq
            messages = await self.ctx.agents.messages(turn.session_id)
            summary = {
                "run_id": turn.run_id,
                "session_id": turn.session_id,
                "seq": seq,
                "at": time.time(),
                "after": len(messages),
                "workspace": str(info["workspace"]),
                "repo": str(repo.top),
                "files": files[: self.config.max_files],
                "total": len(files),
                "added": sum(f["added"] or 0 for f in files),
                "deleted": sum(f["deleted"] or 0 for f in files),
            }
            self._trees[(turn.session_id, turn.run_id)] = (repo, info["base"], head)
            await self.ctx.store.aput((*NAMESPACE, turn.session_id), turn.run_id, summary)
            turn.extras["changes"] = summary
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning("workspace changes: record skipped for %s: %s", turn.session_id, exc)

    # ------------------------------------------------------------------ git
    def _workspace_root(self, workspace: str | None) -> Path:
        return Path(self.ctx.workspace.open(workspace).root)

    async def _repo_for(self, workspace: str | None) -> Repo | None:
        root = self._workspace_root(workspace)
        key = str(root)
        if key not in self._repos:
            try:
                out = await self._run(
                    ["git", "rev-parse", "--show-toplevel", "--git-path", "objects", "--git-path", "index"],
                    cwd=root,
                    env=self._base_env(),
                )
                top, objects, index = (line.strip() for line in out.strip().splitlines()[:3])
                top_path = Path(top)
                self._repos[key] = Repo(
                    top_path, _resolve_git_path(top_path, objects), _resolve_git_path(top_path, index)
                )
            except Exception:  # noqa: BLE001 - not a repository, or no git
                self._repos[key] = None
        return self._repos[key]

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def _dir(self, session_id: str) -> Path:
        if session_id not in self._dirs:
            self._dirs[session_id] = Path(tempfile.mkdtemp(prefix="pyh-changes-"))
            (self._dirs[session_id] / "objects").mkdir()
        return self._dirs[session_id]

    def _base_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
        return env

    def _env(self, session_id: str, repo: Repo) -> dict[str, str]:
        private = self._dir(session_id)
        return {
            **self._base_env(),
            "GIT_INDEX_FILE": str(private / "index"),
            "GIT_OBJECT_DIRECTORY": str(private / "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(repo.objects),
        }

    async def _snapshot(self, session_id: str, repo: Repo) -> str:
        private = self._dir(session_id)
        if repo.index.exists():
            # With its timestamp: git re-reads a file modified in the second its index was written.
            shutil.copy2(repo.index, private / "index")
        else:
            (private / "index").unlink(missing_ok=True)
        env = self._env(session_id, repo)
        await self._git(repo, "add", "--all", "--ignore-errors", env=env, ok=(0, 1))
        return (await self._git(repo, "write-tree", env=env)).strip()

    async def _changed_files(
        self, session_id: str, repo: Repo, base: str, head: str, workspace: Path
    ) -> list[dict[str, Any]]:
        env = self._env(session_id, repo)
        numstat = await self._git(repo, "diff-tree", "-r", "--no-renames", "--numstat", "-z", base, head, env=env)
        status = await self._git(repo, "diff-tree", "-r", "--no-renames", "--name-status", "-z", base, head, env=env)
        statuses: dict[str, str] = {}
        parts = status.split("\0")
        for i in range(0, len(parts) - 1, 2):
            statuses[parts[i + 1]] = parts[i][:1]
        files = []
        for rec in numstat.split("\0"):
            if not rec:
                continue
            added, deleted, path = rec.split("\t", 2)
            binary = added == "-"
            display = os.path.relpath(repo.top / path, workspace)
            files.append(
                {
                    "path": path,
                    "display": display.replace(os.sep, "/"),
                    "status": statuses.get(path, "M"),
                    "added": None if binary else int(added),
                    "deleted": None if binary else int(deleted),
                    "binary": binary,
                }
            )
        files.sort(key=lambda f: f["display"])
        return files

    async def _git(self, repo: Repo, *args: str, env: dict[str, str], ok: tuple[int, ...] = (0,)) -> str:
        return await self._run(["git", *args], cwd=repo.top, env=env, ok=ok)

    async def _run(self, argv: list[str], *, cwd: Path, env: dict[str, str], ok: tuple[int, ...] = (0,)) -> str:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self.config.timeout_s)
        except TimeoutError:
            proc.kill()
            raise GitError(f"{' '.join(argv[:2])} timed out") from None
        if proc.returncode not in ok:
            raise GitError(err.decode("utf-8", "replace").strip() or f"{argv[1]} failed ({proc.returncode})")
        return out.decode("utf-8", "replace")
