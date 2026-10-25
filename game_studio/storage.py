"""Private content-addressed original and derivative storage.

Only immutable keys belong in release manifests. Web/API authorization decides
which keys may be served; this module does not generate public bucket URLs.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


MAX_OBJECT_BYTES = 64 * 1024 * 1024
_KEY = re.compile(r"objects/([a-f0-9]{2})/([a-f0-9]{64})\.(png|webp|jpg|jpeg|wav|ogg|m4a|mp3|flac|bin)\Z")
_EXTENSIONS = {"png", "webp", "jpg", "jpeg", "wav", "ogg", "m4a", "mp3", "flac", "bin"}


class StorageError(ValueError):
    """An object key, configuration or stored object is invalid."""


def _validate_key(key: str) -> tuple[str, str]:
    match = _KEY.fullmatch(key) if isinstance(key, str) else None
    if not match or match[1] != match[2][:2]:
        raise StorageError("Invalid immutable object key")
    return match[2], match[3]


class ContentStore:
    """Local durable volume for development, or a private S3-compatible bucket."""

    def __init__(self, root: str | Path | None = None):
        self.client = None
        self.bucket = None
        # An explicit local root is useful for isolated tests and backup restore.
        bucket = os.environ.get("STUDIO_S3_BUCKET") if root is None else None
        if bucket:
            endpoint = os.environ.get("STUDIO_S3_ENDPOINT", "")
            access = os.environ.get("STUDIO_S3_ACCESS_KEY", "")
            secret = os.environ.get("STUDIO_S3_SECRET_KEY", "")
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or not access or not secret):
                raise StorageError("Configure a private HTTPS S3 endpoint and explicit credentials")
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise StorageError("S3 storage requires boto3") from exc
            addressing_style = os.environ.get("STUDIO_S3_ADDRESSING_STYLE", "virtual")
            if addressing_style not in ("path", "virtual"):
                raise StorageError("S3 addressing style must be path or virtual")
            self.client = boto3.client("s3", endpoint_url=endpoint,
                                       aws_access_key_id=access, aws_secret_access_key=secret,
                                       region_name=os.environ.get("STUDIO_S3_REGION", "auto"),
                                       config=Config(signature_version="s3v4", connect_timeout=5,
                                                     read_timeout=30, retries={"max_attempts": 2},
                                                     s3={"addressing_style": addressing_style}))
            self.bucket = bucket
            self.root = None
        else:
            if root is None and any(os.environ.get(name) for name in
                                    ("STUDIO_S3_ENDPOINT", "STUDIO_S3_ACCESS_KEY", "STUDIO_S3_SECRET_KEY")):
                raise StorageError("S3 settings are incomplete; STUDIO_S3_BUCKET is required")
            self.root = Path(root or os.environ.get("STUDIO_MEDIA_ROOT", "var/studio-media")).resolve()
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        _validate_key(key)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("Object path escapes the configured media root")
        return path

    def exists(self, key: str) -> bool:
        _validate_key(key)
        if self.client is None:
            return self._path(key).is_file()
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if str(code) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise StorageError("Private object storage is unavailable") from exc

    def get(self, key: str) -> bytes:
        expected, _ = _validate_key(key)
        if self.client is None:
            path = self._path(key)
            try:
                if path.stat().st_size > MAX_OBJECT_BYTES:
                    raise StorageError("Stored object exceeds the size limit")
                with path.open("rb") as source:
                    data = source.read(MAX_OBJECT_BYTES + 1)
            except OSError as exc:
                raise StorageError("Private object could not be read") from exc
        else:
            try:
                result = self.client.get_object(Bucket=self.bucket, Key=key)
                stream = result["Body"]
                try:
                    if result.get("ContentLength", 0) > MAX_OBJECT_BYTES:
                        raise StorageError("Stored object exceeds the size limit")
                    data = stream.read(MAX_OBJECT_BYTES + 1)
                finally:
                    stream.close()
            except StorageError:
                raise
            except Exception as exc:
                raise StorageError("Private object could not be read") from exc
        if len(data) > MAX_OBJECT_BYTES or sha256(data).hexdigest() != expected:
            raise StorageError("Stored object failed its SHA-256 integrity check")
        return data

    def put(self, data: bytes, extension: str) -> dict:
        if not isinstance(data, bytes) or not data or len(data) > MAX_OBJECT_BYTES:
            raise StorageError("Object must contain between 1 byte and 64 MiB")
        if not isinstance(extension, str) or extension.lower() not in _EXTENSIONS:
            raise StorageError("Unsupported object extension")
        extension = extension.lower()
        digest = sha256(data).hexdigest()
        key = f"objects/{digest[:2]}/{digest}.{extension}"
        if self.exists(key):
            if self.get(key) != data:
                raise StorageError("An immutable object cannot be overwritten")
            return {"key": key, "sha256": digest, "size": len(data)}
        if self.client is None:
            target = self._path(key)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Re-check after mkdir in case an operator changed a directory link.
            target = self._path(key)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, target)  # Atomic create; never replace an object.
                    if hasattr(os, "O_DIRECTORY"):
                        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                except FileExistsError:
                    if self.get(key) != data:
                        raise StorageError("An immutable object cannot be overwritten")
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        else:
            try:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=data,
                                       ContentType="application/octet-stream", IfNoneMatch="*",
                                       Metadata={"sha256": digest}, CacheControl="private, max-age=0")
            except Exception as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                if str(code) in {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}:
                    if self.get(key) != data:
                        raise StorageError("An immutable object cannot be overwritten") from exc
                else:
                    raise StorageError("Private object could not be stored") from exc
        return {"key": key, "sha256": digest, "size": len(data)}
