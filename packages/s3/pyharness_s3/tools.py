"""The ``s3_*`` LangChain tools (shapes as dsh-s3); every result is text for the model."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from pyharness import package_prompts

from .engine import Bucket, error_text, human
from .store import ProfileStore


class Host(Protocol):
    """The service, as the tools use it."""

    store: ProfileStore | None

    async def run(self, id_or_name: str, fn: Any) -> Any: ...


PROMPTS = package_prompts(__file__)
TOOL_LIST_MAX = 500
TOOL_LIST_DEFAULT = 200
PROFILE_DOC = "Bucket profile name (or id) from s3_buckets."


class CopyArgs(BaseModel):
    """``s3_copy`` arguments; ``from`` (dsh's name) is a Python keyword, so the field is ``from_`` with that alias."""

    model_config = ConfigDict(populate_by_name=True)
    profile: str = Field(description=PROFILE_DOC)
    from_: str = Field(alias="from", description="Source key.")
    to: str = Field(description="Destination key.")
    move: bool | None = Field(None, description="Delete the source after copying (rename).")


def build_tools(service: Host) -> list[Any]:
    """The eleven ``s3_*`` tools bound to a service."""

    @tool(
        "s3_buckets",
        description=PROMPTS["tools"]["s3_buckets"],
    )
    def s3_buckets() -> str:
        assert service.store is not None
        profiles = [service.store.summary(p) for p in service.store.profiles()]
        if not profiles:
            return "no bucket profiles configured (the user adds them in the S3 panel)"
        lines = ["name | bucket | endpoint | region | prefix", "--- | --- | --- | --- | ---"]
        lines += [
            f"{p['name']} | {p['bucket']} | {p['endpoint'] or '(aws)'} | {p['region']} | {p['prefix'] or '/'}"
            for p in profiles
        ]
        return "\n".join(lines)

    @tool(
        "s3_list",
        description=PROMPTS["tools"]["s3_list"],
    )
    async def s3_list(
        profile: str = Field(description=PROFILE_DOC),
        prefix: str | None = Field(
            None, description='Key prefix to list under, e.g. "logs/2026/" (empty = root of the profile).'
        ),
        token: str | None = Field(None, description="Continuation token from a previous truncated page."),
        max: int | None = Field(None, description="Max entries to return (default 200, cap 500)."),  # noqa: A002 — tool argument name (dsh-s3 shape)
        recursive: bool | None = Field(None, description="Walk all objects under the prefix (no folder grouping)."),
    ) -> str:
        cap = min(TOOL_LIST_MAX, max or TOOL_LIST_DEFAULT) if max is None or max > 0 else 1
        try:

            def go(b: Bucket) -> dict[str, Any]:
                if recursive:
                    objects: list[dict[str, Any]] = []
                    truncated = False
                    for o in b.walk(prefix or ""):
                        if len(objects) >= cap:
                            truncated = True
                            break
                        objects.append(o)
                    return {"prefix": prefix or "", "folders": [], "objects": objects, "truncated": truncated}
                return b.list(prefix or "", token, cap)

            page = await service.run(profile, go)
        except Exception as exc:  # noqa: BLE001
            return f"list failed: {error_text(exc) or 'unknown error'}"
        lines = [f"prefix: {page['prefix'] or '/'}"]
        lines += [f"[dir]  {f}" for f in page["folders"]]
        lines += [
            f"{human(o['size']).rjust(10)}  {o['lastModified'][:19].replace('T', ' ')}  {o['key']}"
            for o in page["objects"]
        ]
        if not page["folders"] and not page["objects"]:
            lines.append("(empty)")
        if page["truncated"]:
            lines.append(
                f"… truncated; continue with token={page['nextToken']}"
                if page.get("nextToken")
                else "… truncated at max; raise max or narrow the prefix"
            )
        return "\n".join(lines)

    @tool(
        "s3_stat",
        description=PROMPTS["tools"]["s3_stat"],
    )
    async def s3_stat(
        profile: str = Field(description=PROFILE_DOC),
        key: str = Field(description="Object key (relative to the profile prefix)."),
    ) -> str:
        try:
            s = await service.run(profile, lambda b: b.stat(key))
        except Exception as exc:  # noqa: BLE001
            return f"stat failed: {error_text(exc) or 'unknown error'}"
        lines = [
            f"key: {s['key']}",
            f"size: {human(s['size'])} ({s['size']} bytes)",
            f"content-type: {s.get('contentType') or '-'}",
            f"last-modified: {s.get('lastModified') or '-'}",
            f"etag: {s.get('etag') or '-'}",
            f"storage-class: {s.get('storageClass') or 'STANDARD'}",
        ]
        lines.append(
            "metadata:\n" + "\n".join(f"  {k}: {v}" for k, v in s["metadata"].items())
            if s["metadata"]
            else "metadata: (none)"
        )
        return "\n".join(lines)

    @tool(
        "s3_get",
        description=PROMPTS["tools"]["s3_get"],
    )
    async def s3_get(
        profile: str = Field(description=PROFILE_DOC),
        key: str = Field(description="Object key (relative to the profile prefix)."),
        maxBytes: int | None = Field(None, description="Read at most this many bytes."),
    ) -> str:
        try:
            r = await service.run(profile, lambda b: b.get_text(key, maxBytes or 200 * 1024))
        except Exception as exc:  # noqa: BLE001
            return f"read failed: {error_text(exc) or 'unknown error'}"
        return r["text"] + (
            f"\n[truncated: showing the first part of {r['size']} bytes; raise maxBytes or s3_download the object]"
            if r["truncated"]
            else ""
        )

    @tool(
        "s3_put",
        description=PROMPTS["tools"]["s3_put"],
    )
    async def s3_put(
        profile: str = Field(description=PROFILE_DOC),
        key: str = Field(description="Destination key (relative to the profile prefix)."),
        content: str = Field(description="UTF-8 text content."),
        contentType: str | None = Field(None, description="MIME type (default: guessed from the key extension)."),
    ) -> str:
        try:
            r = await service.run(profile, lambda b: b.put(key, content.encode("utf-8"), contentType))
        except Exception as exc:  # noqa: BLE001
            return f"write failed: {error_text(exc) or 'unknown error'}"
        return f"wrote {key} ({r['size']} bytes)"

    @tool(
        "s3_upload",
        description=PROMPTS["tools"]["s3_upload"],
    )
    async def s3_upload(
        profile: str = Field(description=PROFILE_DOC),
        localPath: str = Field(description="Absolute path of the source file on THIS machine."),
        key: str = Field(description="Destination key (relative to the profile prefix)."),
    ) -> str:
        try:
            r = await service.run(profile, lambda b: b.upload_file(localPath, key))
        except Exception as exc:  # noqa: BLE001
            return f"upload failed: {error_text(exc) or 'unknown error'}"
        return f"uploaded {localPath} → {key} ({human(r['size'])})"

    @tool(
        "s3_download",
        description=PROMPTS["tools"]["s3_download"],
    )
    async def s3_download(
        profile: str = Field(description=PROFILE_DOC),
        key: str = Field(description="Object key (relative to the profile prefix)."),
        localPath: str = Field(description="Absolute destination path on THIS machine."),
    ) -> str:
        try:
            r = await service.run(profile, lambda b: b.download_file(key, localPath))
        except Exception as exc:  # noqa: BLE001
            return f"download failed: {error_text(exc) or 'unknown error'}"
        return f"downloaded {key} → {localPath} ({human(r['size'])})"

    @tool(
        "s3_copy",
        description=PROMPTS["tools"]["s3_copy"],
        args_schema=CopyArgs,
    )
    async def s3_copy(profile: str, from_: str, to: str, move: bool | None = None) -> str:
        try:
            await service.run(profile, lambda b: b.copy(from_, to, bool(move)))
        except Exception as exc:  # noqa: BLE001
            return f"copy failed: {error_text(exc) or 'unknown error'}"
        return f"{'moved' if move else 'copied'} {from_} → {to}"

    @tool(
        "s3_presign",
        description=PROMPTS["tools"]["s3_presign"],
    )
    async def s3_presign(
        profile: str = Field(description=PROFILE_DOC),
        key: str = Field(description="Object key."),
        expiresIn: int | None = Field(None, description="Validity in seconds (default 3600, max 604800)."),
        method: str | None = Field(None, description="GET (default) or PUT."),
    ) -> str:
        try:
            r = await service.run(
                profile, lambda b: b.presign(key, expiresIn or 3600, "PUT" if method == "PUT" else "GET")
            )
        except Exception as exc:  # noqa: BLE001
            return f"presign failed: {error_text(exc) or 'unknown error'}"
        return f"{r['url']}\n(expires {r['expiresAt']})"

    @tool(
        "s3_mkdir",
        description=PROMPTS["tools"]["s3_mkdir"],
    )
    async def s3_mkdir(
        profile: str = Field(description=PROFILE_DOC),
        key: str = Field(description='Folder key, e.g. "backups/2026/".'),
    ) -> str:
        try:
            await service.run(profile, lambda b: b.mkdir(key))
        except Exception as exc:  # noqa: BLE001
            return f"mkdir failed: {error_text(exc) or 'unknown error'}"
        return f"created folder {key}"

    @tool(
        "s3_delete",
        description=PROMPTS["tools"]["s3_delete"],
    )
    async def s3_delete(
        profile: str = Field(description=PROFILE_DOC),
        keys: list[str] = Field(
            description='Object keys (or prefixes ending in "/") to delete, relative to the profile prefix.'
        ),
        confirm: bool = Field(
            description="Must be true; set it only after the user explicitly confirmed this exact deletion."
        ),
    ) -> str:
        if confirm is not True:
            return "delete failed: refused: confirm must be true (ask the user first)"
        try:
            r = await service.run(profile, lambda b: b.delete(keys))
        except Exception as exc:  # noqa: BLE001
            return f"delete failed: {error_text(exc) or 'unknown error'}"
        return "\n".join(
            [f"deleted {r['deleted']} object(s)"] + [f"  failed: {e['key']} — {e['error']}" for e in r["errors"]]
        )

    return [
        s3_buckets,
        s3_list,
        s3_stat,
        s3_get,
        s3_put,
        s3_upload,
        s3_download,
        s3_copy,
        s3_presign,
        s3_mkdir,
        s3_delete,
    ]
