"""Provider-agnostic object storage.

`S3Storage` speaks the S3 API, so R2, S3, MinIO and GCS (via its S3-interoperable
endpoint with HMAC keys) are all a matter of config. `LocalStorage` keeps files on disk
for tests and offline hacking.

All methods are synchronous (boto3 is); call them via asyncio.to_thread from async code
when they do network I/O. URL signing is local computation and safe to call inline.
"""

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings


class Storage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def put_file(self, key: str, path: str | Path, content_type: str | None = None) -> None: ...
    def download_file(self, key: str, path: str | Path) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def presign_put(self, key: str, content_type: str | None = None, expires_s: int | None = None) -> str: ...
    def url_for(self, key: str, expires_s: int | None = None) -> str: ...
    def ping(self) -> None: ...


class S3Storage:
    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        self.settings = settings
        self.bucket = settings.s3_bucket
        cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"})
        common = dict(
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=cfg,
        )
        self._client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, **common)
        # Presigned URLs embed the host in the signature, so sign with the endpoint clients will use.
        if settings.signing_endpoint_url != settings.s3_endpoint_url:
            self._signer = boto3.client("s3", endpoint_url=settings.signing_endpoint_url, **common)
        else:
            self._signer = self._client

    def put_bytes(self, key, data, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def put_file(self, key, path, content_type=None):
        extra = {"ExtraArgs": {"ContentType": content_type}} if content_type else {}
        self._client.upload_file(str(path), self.bucket, key, **extra)

    def download_file(self, key, path):
        self._client.download_file(self.bucket, key, str(path))

    def get_bytes(self, key):
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete_prefix(self, prefix):
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True})
                deleted += len(keys)
        return deleted

    def presign_put(self, key, content_type=None, expires_s=None):
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return self._signer.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_s or self.settings.presign_put_expires_s
        )

    def url_for(self, key, expires_s=None):
        if self.settings.storage_public_base_url:
            return f"{self.settings.storage_public_base_url.rstrip('/')}/{key}"
        return self._signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_s or self.settings.presign_get_expires_s,
        )

    def ping(self):
        self._client.head_bucket(Bucket=self.bucket)

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)


class LocalStorage:
    def __init__(self, root: str | Path, public_base_url: str | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError(f"key escapes storage root: {key}")
        return p

    def put_bytes(self, key, data, content_type=None):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def put_file(self, key, path, content_type=None):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, p)

    def download_file(self, key, path):
        shutil.copyfile(self._path(key), path)

    def get_bytes(self, key):
        return self._path(key).read_bytes()

    def exists(self, key):
        return self._path(key).is_file()

    def delete_prefix(self, prefix):
        files = [p for p in self.root.glob(f"{prefix}**/*") if p.is_file()]
        for p in files:
            p.unlink()
        return len(files)

    def presign_put(self, key, content_type=None, expires_s=None):
        return f"file://{self._path(key)}"

    def url_for(self, key, expires_s=None):
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key}"
        return f"file://{self._path(key)}"

    def ping(self):
        return None


def make_storage(settings: Settings | None = None) -> Storage:
    settings = settings or get_settings()
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir, settings.storage_public_base_url)
    return S3Storage(settings)


@lru_cache
def get_storage() -> Storage:
    return make_storage()
