import hashlib
from pathlib import Path
from typing import TypedDict


class FileFingerprint(TypedDict):
    sha256: str
    size_bytes: int


def fingerprint_file(path: Path, *, chunk_size: int = 1024 * 1024) -> FileFingerprint:
    """Return a stable content identity without loading the whole file into memory."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}
