"""
``ctx.s3``: S3-compatible object storage browser (MinIO / OSS / COS / R2 / AWS).

| member | contract |
|---|---|
| ``store`` | :class:`ProfileStore`: bucket profiles (secret keys in the credential store), the agent-access setting |
| ``bucket(p)`` | :class:`Bucket` for a profile (boto3 client cached per profile) |
| ``sync()`` | register the ``s3_*`` tools and prompt section while agent access is on |

| config         | meaning                                                                  |
|----------------|--------------------------------------------------------------------------|
| ``path``       | profiles file (default ``<profile data>/toolkit/s3.json``)               |
| ``approval``   | approval gate for ``s3_delete`` (default none; the tool needs ``confirm=true``) |

A profile is one bucket (endpoint, region, keys, path-style flag, optional scope prefix); every key the tools and
routes see is relative to that prefix. Tools (shapes as dsh-s3): ``s3_buckets``, ``s3_list``, ``s3_stat``, ``s3_get``,
``s3_put``, ``s3_upload``, ``s3_download``, ``s3_copy``, ``s3_presign``, ``s3_mkdir``, ``s3_delete``. Routes under
``/api/s3`` serve the S3 page: profiles, settings, test, list, stat, object (download / inline preview), text, upload
(raw body), delete, folder, presign, copy.
"""

from __future__ import annotations

from .service import GUIDANCE, Config, S3Service

__all__ = ["GUIDANCE", "Config", "S3Service"]
