from pathlib import Path

from fastapi.testclient import TestClient

import app


client = TestClient(app.app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_requires_access_token() -> None:
    response = client.post("/api/upload", files={"upload_file": ("note.txt", b"hello")})
    assert response.status_code == 401


def test_upload_saves_file_and_avoids_collisions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(app, "RECEIVED_DIR", tmp_path)
    token = app.ACCESS_TOKEN
    first = client.post(
        "/api/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload_file": ("note.txt", b"hello")},
    )
    second = client.post(
        "/api/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload_file": ("note.txt", b"again")},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert (tmp_path / "note.txt").read_bytes() == b"hello"
    assert (tmp_path / "note (1).txt").read_bytes() == b"again"
