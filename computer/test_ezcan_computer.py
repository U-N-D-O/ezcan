import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from ezcan_computer import create_app


def test_intake_upload_and_archive(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    token = app.state.token
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post("/api/intakes", headers=headers, json={"note": "front has light whitening"})
    assert response.status_code == 200
    intake_id = response.json()["intakeId"]

    content = b"card-front-test"
    digest = hashlib.sha256(content).hexdigest()
    response = client.post(
        f"/api/intakes/{intake_id}/media",
        headers={
            **headers,
            "X-Ezcan-File-Name": "front.jpg",
            "X-Ezcan-Media-Type": "image",
            "X-Ezcan-SHA256": digest,
        },
        content=content,
    )
    assert response.status_code == 200

    response = client.post(f"/api/intakes/{intake_id}/complete", headers=headers, json={})
    assert response.status_code == 200
    archive_code = response.json()["archiveCode"]
    assert len(archive_code) == 4
    assert archive_code[0].isalpha() and archive_code[1].isdigit()
    assert archive_code[2].isalpha() and archive_code[3].isdigit()

    card_folder = tmp_path / "data" / "Cards" / archive_code
    assert card_folder.is_dir()
    manifest = json.loads((card_folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["archiveCode"] == archive_code
    assert (card_folder / "original" / "front.jpg").read_bytes() == content


def test_upload_retry_is_idempotent(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"same-file"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "back.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }

    first = client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content)
    second = client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
