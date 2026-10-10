import sqlite3
from pathlib import Path

import pytest

from backend.app.ingestion_tools import fingerprint_file
from backend.app.storage import Repository


def _record(experiment_id: str, file_hash: str) -> dict:
    return {
        "id": experiment_id,
        "name": experiment_id,
        "description": "test",
        "filename": "source.csv",
        "file_path": "/tmp/source.csv",
        "file_hash": file_hash,
        "status": "READY",
        "profile": {"row_count": 1},
        "table_sample": {"rows": []},
        "schema": {"experiment_type": "test"},
        "created_at": "2026-07-18T00:00:00Z",
    }


def test_fingerprint_uses_file_content(tmp_path: Path):
    first = tmp_path / "first.csv"
    second = tmp_path / "renamed.csv"
    different = tmp_path / "different.csv"
    first.write_text("x,y\n1,2\n", encoding="utf-8")
    second.write_text("x,y\n1,2\n", encoding="utf-8")
    different.write_text("x,y\n1,3\n", encoding="utf-8")

    assert fingerprint_file(first)["sha256"] == fingerprint_file(second)["sha256"]
    assert fingerprint_file(first)["sha256"] != fingerprint_file(different)["sha256"]
    assert fingerprint_file(first)["size_bytes"] == first.stat().st_size


def test_repository_finds_and_rejects_duplicate_hash(tmp_path: Path):
    repository = Repository(tmp_path / "test.db")
    repository.create_experiment(_record("exp-1", "same-hash"))

    existing = repository.get_experiment_by_file_hash("same-hash")
    assert existing is not None
    assert existing["id"] == "exp-1"
    with pytest.raises(sqlite3.IntegrityError):
        repository.create_experiment(_record("exp-2", "same-hash"))
