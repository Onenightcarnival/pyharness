"""S3 operations on a boto3 client; keys are relative to the profile prefix at this boundary."""

from __future__ import annotations

import datetime as dt
import mimetypes
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig

from pyharness import package_toml

MAX_PAGE = 1000
MAX_TEXT_BYTES = 2 * 1024 * 1024
PRESIGN_MAX = 604800
DELETE_BATCH = 1000
PART_SIZE = 8 * 1024 * 1024

MIME: dict[str, str] = package_toml(__file__)["engine"]["mime"]  # file extension -> media type
PREVIEWABLE = re.compile(r"^(image/(png|jpeg|gif|webp|bmp|avif)|application/pdf|video/|audio/)")


class S3Error(RuntimeError):
    pass


def guess_mime(key: str) -> str:
    ext = os.path.splitext(key.lower())[1]
    return MIME.get(ext) or mimetypes.guess_type(key)[0] or "application/octet-stream"


def clean_key(key: str) -> str:
    k = (key or "").replace("\\", "/").lstrip("/")
    if any(part == ".." for part in k.split("/")):
        raise S3Error('key must not contain ".." segments')
    return k


def error_text(exc: BaseException) -> str:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict) and resp.get("Error"):
        err = resp["Error"]
        return f"{err.get('Code', type(exc).__name__)}: {err.get('Message', '')}".strip()
    name = type(exc).__name__
    return f"{name}: {exc}" if name not in ("Exception", "RuntimeError", "S3Error") else str(exc)


def looks_like_text(buf: bytes) -> bool:
    head = buf[:8192]
    if b"\0" in head:
        return False
    if not head:
        return True
    control = sum(1 for b in head if b < 32 and b not in (9, 10, 13, 12, 27, 8))
    return control / len(head) < 0.1


def human(n: int | float) -> str:
    v = float(n)
    if v < 1024:
        return f"{int(v)} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        v /= 1024
        if v < 1024 or unit == "TiB":
            return f"{v:.0f} {unit}" if v >= 100 else f"{v:.1f} {unit}"
    return f"{v:.1f} TiB"


def make_client(profile: dict[str, Any], secret: str) -> Any:
    kwargs: dict[str, Any] = {
        "s3": {"addressing_style": "path" if profile.get("pathStyle") else "virtual"},
        "retries": {"max_attempts": 3},
        "connect_timeout": 10,
        "read_timeout": 60,
    }
    try:
        cfg = BotoConfig(
            request_checksum_calculation="when_required", response_checksum_validation="when_required", **kwargs
        )
    except TypeError:  # older botocore
        cfg = BotoConfig(**kwargs)
    return boto3.client(
        "s3",
        region_name=profile.get("region") or "us-east-1",
        endpoint_url=profile.get("endpoint") or None,
        aws_access_key_id=profile["accessKeyId"],
        aws_secret_access_key=secret,
        config=cfg,
    )


def _iso(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return str(value) if value else ""


class Bucket:
    """One profile's bucket through a boto3 client, with prefix scoping."""

    def __init__(self, client: Any, profile: dict[str, Any]) -> None:
        self.client = client
        self.bucket = profile["bucket"]
        self.prefix = profile.get("prefix") or ""

    def full(self, key: str) -> str:
        return self.prefix + clean_key(key)

    def rel(self, key: str) -> str:
        return key[len(self.prefix) :] if self.prefix and key.startswith(self.prefix) else key

    # ------------------------------------------------------------------ reads
    def test(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            res = self.client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix, MaxKeys=5)
            sample = [self.rel(p["Prefix"]) for p in res.get("CommonPrefixes", [])] + [
                self.rel(o["Key"]) for o in res.get("Contents", [])
            ]
            return {
                "ok": True,
                "latencyMs": int((time.perf_counter() - started) * 1000),
                "sample": [s for s in sample if s],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "latencyMs": int((time.perf_counter() - started) * 1000), "error": error_text(exc)}

    def list(self, prefix: str = "", token: str | None = None, max_keys: int = MAX_PAGE) -> dict[str, Any]:
        rel_prefix = clean_key(prefix) if prefix else ""
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Prefix": self.prefix + rel_prefix,
            "Delimiter": "/",
            "MaxKeys": max(1, min(MAX_PAGE, max_keys)),
        }
        if token:
            kwargs["ContinuationToken"] = token
        res = self.client.list_objects_v2(**kwargs)
        full_prefix = self.prefix + rel_prefix
        folders = [f for f in (self.rel(p["Prefix"]) for p in res.get("CommonPrefixes", [])) if f]
        objects = []
        for o in res.get("Contents", []):
            if o["Key"] == "" or o["Key"] == full_prefix:
                continue
            item = {
                "key": self.rel(o["Key"]),
                "size": int(o.get("Size") or 0),
                "lastModified": _iso(o.get("LastModified")),
            }
            if o.get("ETag"):
                item["etag"] = o["ETag"]
            if o.get("StorageClass"):
                item["storageClass"] = o["StorageClass"]
            objects.append(item)
        out: dict[str, Any] = {
            "prefix": rel_prefix,
            "folders": folders,
            "objects": objects,
            "truncated": bool(res.get("IsTruncated")),
        }
        if res.get("NextContinuationToken"):
            out["nextToken"] = res["NextContinuationToken"]
        return out

    def walk(self, prefix: str = "") -> Iterator[dict[str, Any]]:
        rel_prefix = clean_key(prefix) if prefix else ""
        token = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": self.prefix + rel_prefix, "MaxKeys": MAX_PAGE}
            if token:
                kwargs["ContinuationToken"] = token
            res = self.client.list_objects_v2(**kwargs)
            for o in res.get("Contents", []):
                yield {
                    "key": self.rel(o["Key"]),
                    "size": int(o.get("Size") or 0),
                    "lastModified": _iso(o.get("LastModified")),
                }
            token = res.get("NextContinuationToken") if res.get("IsTruncated") else None
            if not token:
                return

    def stat(self, key: str) -> dict[str, Any]:
        res = self.client.head_object(Bucket=self.bucket, Key=self.full(key))
        out: dict[str, Any] = {
            "key": clean_key(key),
            "size": int(res.get("ContentLength") or 0),
            "metadata": dict(res.get("Metadata") or {}),
        }
        for src, dst in (("ContentType", "contentType"), ("ETag", "etag"), ("StorageClass", "storageClass")):
            if res.get(src):
                out[dst] = res[src]
        if res.get("LastModified"):
            out["lastModified"] = _iso(res["LastModified"])
        return out

    def open(self, key: str) -> dict[str, Any]:
        res = self.client.get_object(Bucket=self.bucket, Key=self.full(key))
        body = res.get("Body")
        if body is None:
            raise S3Error("empty response body")
        return {
            "body": body,
            "contentType": res.get("ContentType") or guess_mime(key),
            "size": res.get("ContentLength"),
            "lastModified": res.get("LastModified"),
        }

    def get_text(self, key: str, max_bytes: int = MAX_TEXT_BYTES) -> dict[str, Any]:
        limit = max(1, min(MAX_TEXT_BYTES, int(max_bytes)))
        res = self.client.get_object(Bucket=self.bucket, Key=self.full(key), Range=f"bytes=0-{limit}")
        buf = res["Body"].read(limit + 1)
        if not looks_like_text(buf):
            raise S3Error("object is binary; download it instead of reading it as text")
        total = None
        m = re.search(r"/(\d+)$", str(res.get("ContentRange") or ""))
        if m:
            total = int(m.group(1))
        elif res.get("ContentLength") is not None:
            total = int(res["ContentLength"])
        if total is None:
            total = len(buf)
        return {
            "text": buf[:limit].decode("utf-8", "replace"),
            "size": total,
            "contentType": res.get("ContentType") or guess_mime(key),
            "truncated": len(buf) > limit or total > limit,
        }

    # ------------------------------------------------------------------ writes
    def put(self, key: str, body: bytes, content_type: str | None = None) -> dict[str, Any]:
        res = self.client.put_object(
            Bucket=self.bucket,
            Key=self.full(key),
            Body=body,
            ContentType=content_type or guess_mime(key),
            ContentLength=len(body),
        )
        out: dict[str, Any] = {"size": len(body)}
        if res.get("ETag"):
            out["etag"] = res["ETag"]
        return out

    def upload_stream(self, key: str, stream: Any, content_type: str | None = None) -> None:
        self.client.upload_fileobj(
            stream,
            self.bucket,
            self.full(key),
            ExtraArgs={"ContentType": content_type or guess_mime(key)},
            Config=TransferConfig(multipart_chunksize=PART_SIZE, max_concurrency=3),
        )

    def upload_file(self, local_path: str, key: str) -> dict[str, Any]:
        size = os.stat(local_path).st_size
        with open(local_path, "rb") as f:
            self.upload_stream(key, f, guess_mime(local_path))
        return {"size": size}

    def download_file(self, key: str, local_path: str) -> dict[str, Any]:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        opened = self.open(key)
        with open(local_path, "wb") as f:
            for chunk in opened["body"].iter_chunks():
                f.write(chunk)
        return {"size": os.stat(local_path).st_size}

    def mkdir(self, key: str) -> None:
        marker = clean_key(key).rstrip("/") + "/"
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + marker, Body=b"", ContentLength=0)

    def delete(self, keys: list[str]) -> dict[str, Any]:
        targets: list[str] = []
        for key in keys:
            k = clean_key(key)
            if not k:
                continue
            if k.endswith("/"):
                targets += [self.prefix + o["key"] for o in self.walk(k)]
                targets.append(self.prefix + k)
            else:
                targets.append(self.prefix + k)
        seen: set[str] = set()
        unique = [t for t in targets if not (t in seen or seen.add(t))]
        deleted = 0
        errors: list[dict[str, str]] = []
        for i in range(0, len(unique), DELETE_BATCH):
            batch = unique[i : i + DELETE_BATCH]
            try:
                res = self.client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True}
                )
                errs = res.get("Errors") or []
                deleted += len(batch) - len(errs)
                errors += [
                    {"key": self.rel(e.get("Key", "")), "error": f"{e.get('Code', '')} {e.get('Message', '')}".strip()}
                    for e in errs
                ]
            except Exception as first:  # noqa: BLE001
                for k in batch:
                    try:
                        self.client.delete_object(Bucket=self.bucket, Key=k)
                        deleted += 1
                    except Exception as inner:  # noqa: BLE001
                        errors.append(
                            {
                                "key": self.rel(k),
                                "error": f"{error_text(inner)} (batch delete failed: {error_text(first)})",
                            }
                        )
        return {"deleted": deleted, "errors": errors}

    def copy(self, source: str, target: str, move: bool = False) -> None:
        src, dst = self.full(source), self.full(target)
        if src == dst:
            raise S3Error("source and target are the same key")
        self.client.copy_object(
            Bucket=self.bucket, Key=dst, CopySource={"Bucket": self.bucket, "Key": src}, MetadataDirective="COPY"
        )
        if move:
            self.client.delete_object(Bucket=self.bucket, Key=src)

    def presign(self, key: str, expires_in: int = 3600, method: str = "GET") -> dict[str, Any]:
        seconds = max(1, min(PRESIGN_MAX, int(expires_in)))
        url = self.client.generate_presigned_url(
            "put_object" if method == "PUT" else "get_object",
            Params={"Bucket": self.bucket, "Key": self.full(key)},
            ExpiresIn=seconds,
        )
        return {
            "url": url,
            "expiresAt": (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
        }
