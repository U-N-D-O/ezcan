import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ebay import open_picture_search
from ebay_account import EbayAccountManager
from ezcan_computer import Store, card_action_availability, create_app, default_data_root, increment_archive_code, program_directory
from image_processor import find_back_image, prepare_search_image
from pricing import recommend_price


def test_ebay_account_profile_stores_state_without_credentials(tmp_path: Path) -> None:
    manager = EbayAccountManager(tmp_path / "Ezcan")
    assert manager.state()["status"] == "not_connected"

    manager._browser_executable = lambda: None
    launch = manager.begin_sign_in(opener=lambda _url: True)

    assert launch.persistent is False
    assert launch.profile_path == tmp_path / "Ezcan" / "browser-profile"
    assert manager.state()["status"] == "login_required"
    metadata = manager.metadata_path.read_text(encoding="utf-8")
    assert "password" not in metadata.lower()
    assert "username" not in metadata.lower()

    manager.mark_connected()
    assert manager.state()["status"] == "connected"
    manager.remove_profile()
    assert manager.state()["status"] == "not_connected"
    assert not manager.profile_path.exists()


def test_card_action_availability_follows_workflow_state() -> None:
    assert card_action_availability(None, False) == {
        "search": False,
        "match": False,
        "identity": False,
        "pricing": False,
        "make_draft": False,
        "review_draft": False,
    }
    assert card_action_availability("received", False)["search"] is True
    assert card_action_availability("received", False)["match"] is False
    assert card_action_availability("searching", False)["match"] is True
    assert card_action_availability("searching", False)["pricing"] is False
    assert card_action_availability("identified", False)["make_draft"] is True
    assert card_action_availability("identified", False)["pricing"] is True
    assert card_action_availability("identified", True)["review_draft"] is True
    assert card_action_availability("identified", True)["make_draft"] is False
    assert card_action_availability("recovery_required", False)["search"] is False


def test_default_archive_is_next_to_program() -> None:
    assert default_data_root() == program_directory() / "Archive"


def test_legacy_database_is_backed_up_before_schema_upgrade(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    database_path = root / "ezcan.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE cards (internal_id TEXT PRIMARY KEY, archive_code TEXT NOT NULL UNIQUE, "
            "folder_path TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )

    Store(root)

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(cards)")}
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert {"grade_company", "grade"}.issubset(columns)
    intake_columns = {row[1] for row in connection.execute("PRAGMA table_info(intakes)")}
    assert "details_json" in intake_columns
    assert version == "3"
    assert len(list((root / "Backups").glob("ezcan-before-migration-*.sqlite3"))) == 1


def test_interrupted_finalization_rebuilds_moved_card(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    store = Store(root)
    intake_id, temporary_path, archive_code = store.create_intake(None)
    image_path = temporary_path / "original" / "front.jpg"
    image_path.write_bytes(b"recovery-card")
    store.add_media(intake_id, "front.jpg", image_path, "image", hashlib.sha256(b"recovery-card").hexdigest(), 13)
    internal_id = "recovery-internal-id"
    details = {"language": "english", "condition": "excellent", "gradeCompany": "none", "grade": ""}
    with store.connection() as connection:
        connection.execute(
            "UPDATE intakes SET status = 'finalizing', internal_id = ?, details_json = ? WHERE intake_id = ?",
            (internal_id, json.dumps(details), intake_id),
        )
    final_path = store.cards / archive_code
    temporary_path.rename(final_path)

    recovered = Store(root)

    intake = recovered.intake(intake_id)
    card = recovered.card_by_archive_code(archive_code)
    assert intake["status"] == "finalized"
    assert card["internal_id"] == internal_id
    assert card["language"] == "english"
    assert (final_path / "manifest.json").is_file()
    assert recovered.create_intake(None)[2] == increment_archive_code(archive_code)


def test_interrupted_finalization_before_move_returns_to_uploading(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    store = Store(root)
    intake_id, _temporary_path, _archive_code = store.create_intake(None)
    with store.connection() as connection:
        connection.execute(
            "UPDATE intakes SET status = 'finalizing', internal_id = ?, details_json = ? WHERE intake_id = ?",
            ("not-moved", "{}", intake_id),
        )

    recovered = Store(root)

    assert recovered.intake(intake_id)["status"] == "uploading"


def test_recovery_required_intake_is_visible_in_recent_activity(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    store = Store(root)
    intake_id, _temporary_path, archive_code = store.create_intake(None)
    with store.connection() as connection:
        connection.execute(
            "UPDATE intakes SET status = 'recovery_required' WHERE intake_id = ?",
            (intake_id,),
        )

    activity = Store(root).recent_cards()

    recovery = next(item for item in activity if item["archive_code"] == archive_code)
    assert recovery["status"] == "recovery_required"
    assert recovery["folder_path"].endswith(f"uploading-{intake_id}")


def test_archive_codes_increment_in_storage_order() -> None:
    assert increment_archive_code("A0A0") == "A0A1"
    assert increment_archive_code("A0A9") == "A0B0"
    assert increment_archive_code("A0Z9") == "A1A0"
    assert increment_archive_code("A9Z9") == "B0A0"


def test_new_intakes_reserve_sequential_archive_codes(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}

    codes = [
        client.post("/api/intakes", headers=headers, json={}).json()["suggestedArchiveCode"]
        for _ in range(11)
    ]

    assert codes[:10] == [f"A0A{index}" for index in range(10)]
    assert codes[10] == "A0B0"


def test_manual_archive_code_becomes_next_sequence_value(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"manual-code-card"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "front.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }
    assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200
    response = client.post(
        f"/api/intakes/{intake_id}/complete",
        headers=headers,
        json={"archiveCode": "C4D9"},
    )
    assert response.status_code == 200

    next_intake = client.post("/api/intakes", headers=headers, json={}).json()
    assert next_intake["suggestedArchiveCode"] == "C4E0"


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
    assert manifest["listingDetails"] == {
        "language": "japanese",
        "condition": "near_mint",
        "gradeCompany": "none",
        "grade": "",
        "authenticityStatus": "authenticated",
    }
    assert (card_folder / "original" / "front.jpg").read_bytes() == content


def test_listing_details_are_saved_and_authenticity_is_defaulted(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"english-graded-card"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "front.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }
    assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200

    response = client.post(
        f"/api/intakes/{intake_id}/complete",
        headers=headers,
        json={
            "listingDetails": {
                "language": "english",
                "condition": "graded",
                "gradeCompany": "psa",
                "grade": "9",
            }
        },
    )

    assert response.status_code == 200
    archive_code = response.json()["archiveCode"]
    manifest = json.loads((tmp_path / "data" / "Cards" / archive_code / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["listingDetails"] == {
        "language": "english",
        "condition": "graded",
        "gradeCompany": "psa",
        "grade": "9",
        "authenticityStatus": "authenticated",
    }
    with app.state.store.connection() as connection:
        card = connection.execute("SELECT language, condition, grade_company, grade, authenticity_status FROM cards").fetchone()
    assert tuple(card) == ("english", "graded", "psa", "9", "authenticated")


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


def test_explicit_archive_code_uses_exact_folder_and_is_idempotent(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"explicit-code-card"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "front.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }
    assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200

    first = client.post(
        f"/api/intakes/{intake_id}/complete",
        headers=headers,
        json={"archiveCode": "Z9A0"},
    )
    second = client.post(
        f"/api/intakes/{intake_id}/complete",
        headers=headers,
        json={"archiveCode": "B2C3"},
    )

    assert first.status_code == 200
    assert first.json()["archiveCode"] == "Z9A0"
    assert second.status_code == 200
    assert second.json()["archiveCode"] == "Z9A0"
    assert (tmp_path / "data" / "Cards" / "Z9A0").is_dir()


def test_invalid_archive_code_is_rejected(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    invalid_codes = ["AB12", "A1B", "a1b2", "A1B22", "A-1B"]

    for code in invalid_codes:
        intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
        content = code.encode()
        media_headers = {
            **headers,
            "X-Ezcan-File-Name": "front.jpg",
            "X-Ezcan-Media-Type": "image",
            "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
        }
        assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200
        response = client.post(
            f"/api/intakes/{intake_id}/complete",
            headers=headers,
            json={"archiveCode": code},
        )
        assert response.status_code == 422


def test_duplicate_archive_code_is_rejected(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}

    intake_ids = [client.post("/api/intakes", headers=headers, json={}).json()["intakeId"] for _ in range(2)]
    for intake_id in intake_ids:
        content = intake_id.encode()
        media_headers = {
            **headers,
            "X-Ezcan-File-Name": "front.jpg",
            "X-Ezcan-Media-Type": "image",
            "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
        }
        assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200

    assert client.post(
        f"/api/intakes/{intake_ids[0]}/complete",
        headers=headers,
        json={"archiveCode": "A1B2"},
    ).status_code == 200
    duplicate = client.post(
        f"/api/intakes/{intake_ids[1]}/complete",
        headers=headers,
        json={"archiveCode": "A1B2"},
    )
    assert duplicate.status_code == 409


def test_shared_file_can_be_listed_and_downloaded(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    content = b"ipa-artifact-content"
    shared_file = app.state.store.to_iphone / "Ezcan-unsigned.ipa"
    shared_file.write_bytes(content)

    listing = client.get("/api/shared-files", headers=headers)
    download = client.get("/api/shared-files/Ezcan-unsigned.ipa", headers=headers)

    assert listing.status_code == 200
    assert listing.json()["files"][0]["fileName"] == "Ezcan-unsigned.ipa"
    assert listing.json()["files"][0]["size"] == len(content)
    assert download.status_code == 200
    assert download.headers["content-disposition"].endswith('filename="Ezcan-unsigned.ipa"')
    assert download.content == content


def test_prepare_search_image_prefers_front_and_writes_generated_jpeg(tmp_path: Path) -> None:
    card_folder = tmp_path / "Cards" / "A0A0"
    original = card_folder / "original"
    original.mkdir(parents=True)
    Image.new("RGB", (2400, 3200), "white").save(original / "back.jpg")
    Image.new("RGB", (1000, 1400), "red").save(original / "front.jpg")

    prepared = prepare_search_image(card_folder)

    assert prepared == card_folder / "generated" / "ebay-search.jpg"
    assert prepared.is_file()
    with Image.open(prepared) as image:
        assert image.format == "JPEG"
        assert image.size == (1000, 1400)


def test_prepare_search_image_fails_without_an_original_image(tmp_path: Path) -> None:
    card_folder = tmp_path / "Cards" / "A0A0"
    (card_folder / "original").mkdir(parents=True)

    try:
        prepare_search_image(card_folder)
    except FileNotFoundError as error:
        assert "No image was found" in str(error)
    else:
        raise AssertionError("Expected missing front image to fail")


def test_find_back_image_prefers_named_back_and_falls_back_to_second_image(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    Image.new("RGB", (100, 100), "red").save(original / "front.jpg")
    Image.new("RGB", (100, 100), "blue").save(original / "back.jpg")
    assert find_back_image(tmp_path) == original / "back.jpg"

    (original / "back.jpg").unlink()
    Image.new("RGB", (100, 100), "blue").save(original / "scan-02.jpg")
    assert find_back_image(tmp_path) == original / "scan-02.jpg"


def test_picture_search_opener_receives_prepared_image(tmp_path: Path) -> None:
    image_path = tmp_path / "ebay-search.jpg"
    image_path.write_bytes(b"jpeg")
    opened: list[str] = []

    launch = open_picture_search(image_path, opener=lambda url: opened.append(url) or True)

    assert opened == ["https://www.ebay.com/"]
    assert launch.image_path == image_path


def test_ebay_search_session_is_persisted(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"searchable-front"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "front.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }
    assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200
    archive_code = client.post(f"/api/intakes/{intake_id}/complete", headers=headers, json={}).json()["archiveCode"]
    card = app.state.store.card_by_archive_code(archive_code)
    image_path = tmp_path / "data" / "Cards" / archive_code / "generated" / "ebay-search.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"jpeg")

    search_id = app.state.store.start_ebay_search(card, image_path)
    app.state.store.finish_ebay_search(search_id, "awaiting_manual_upload")
    search = app.state.store.latest_ebay_search(archive_code)

    assert search["search_id"] == search_id
    assert search["mode"] == "browser_assisted"
    assert search["status"] == "awaiting_manual_upload"


def test_ebay_candidate_preserves_item_shipping_and_total(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"candidate-card"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "front.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }
    assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200
    archive_code = client.post(f"/api/intakes/{intake_id}/complete", headers=headers, json={}).json()["archiveCode"]
    card = app.state.store.card_by_archive_code(archive_code)
    image_path = Path(card["folder_path"]) / "generated" / "ebay-search.jpg"
    image_path.write_bytes(b"jpeg")
    search_id = app.state.store.start_ebay_search(card, image_path)

    candidate_id = app.state.store.add_ebay_candidate(
        search_id,
        {
            "market_status": "sold",
            "title": "Japanese Pokemon card comparable",
            "item_url": "https://www.ebay.com/itm/123",
            "sale_or_listing_date": "2026-09-01",
            "price": "25.50",
            "shipping_price": "4.50",
            "condition": "near_mint",
            "grade": "",
            "listing_format": "fixed_price",
            "seller_notes": "Matching holo and card number",
        },
    )

    candidate = app.state.store.ebay_candidates(archive_code)[0]
    search = app.state.store.latest_ebay_search(archive_code)
    assert candidate["candidate_id"] == candidate_id
    assert candidate["price"] == 25.5
    assert candidate["shipping_price"] == 4.5
    assert candidate["total_buyer_cost"] == 30.0
    assert candidate["market_status"] == "sold"
    assert candidate["seller_notes"] == "Matching holo and card number"
    assert search["status"] == "candidate_recorded"


def test_ebay_candidate_rejects_invalid_listing_url(tmp_path: Path) -> None:
    from ezcan_computer import Store

    store = Store(tmp_path / "data")

    try:
        store.add_ebay_candidate(
            "missing-search",
            {"market_status": "active", "title": "No URL", "item_url": "example.com"},
        )
    except ValueError as error:
        assert "listing URL" in str(error)
    else:
        raise AssertionError("Expected invalid candidate data to fail")


def test_card_identity_requires_match_and_marks_search_confirmed(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    intake_id = client.post("/api/intakes", headers=headers, json={}).json()["intakeId"]
    content = b"identity-card"
    media_headers = {
        **headers,
        "X-Ezcan-File-Name": "front.jpg",
        "X-Ezcan-Media-Type": "image",
        "X-Ezcan-SHA256": hashlib.sha256(content).hexdigest(),
    }
    assert client.post(f"/api/intakes/{intake_id}/media", headers=media_headers, content=content).status_code == 200
    archive_code = client.post(f"/api/intakes/{intake_id}/complete", headers=headers, json={}).json()["archiveCode"]
    card = app.state.store.card_by_archive_code(archive_code)
    search_id = app.state.store.start_ebay_search(card, Path(card["folder_path"]) / "generated" / "ebay-search.jpg")
    app.state.store.add_ebay_candidate(
        search_id,
        {
            "market_status": "sold",
            "title": "Charizard holo matching candidate",
            "item_url": "https://www.ebay.com/itm/456",
            "price": "90",
            "shipping_price": "34",
        },
    )

    app.state.store.confirm_card_identity(
        archive_code,
        {
            "card_name": "Charizard",
            "set_name": "Base Set",
            "card_number": "4/102",
            "edition": "Unlimited",
            "printing": "Holo",
            "finish": "Holofoil",
        },
    )

    confirmed_card = app.state.store.card_by_archive_code(archive_code)
    confirmed_search = app.state.store.latest_ebay_search(archive_code)
    assert confirmed_card["status"] == "identified"
    assert confirmed_card["card_name"] == "Charizard"
    assert confirmed_card["set_name"] == "Base Set"
    assert confirmed_card["card_number"] == "4/102"
    assert confirmed_card["printing"] == "Holo"
    assert confirmed_search["status"] == "identity_confirmed"

    draft_path = app.state.store.create_listing_draft(archive_code)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    listing = app.state.store.latest_listing_draft(archive_code)
    assert draft["status"] == "draft"
    assert draft["title"] == "Japanese | Charizard | Base Set | 4/102"
    assert draft["shipping"] == {"firstItemCharge": "34.00", "additionalItemsCharge": "0.00"}
    assert draft["publishing"] == {"published": False, "sellerCredentialsUsed": False}
    assert str(Path(card["folder_path"]) / "original" / "front.jpg") in draft["imagePaths"]
    assert listing["status"] == "draft"
    assert Path(listing["draft_path"]) == draft_path

    app.state.store.update_listing_draft(archive_code, "Reviewed Charizard", "A reviewed local description.")
    reviewed = json.loads(draft_path.read_text(encoding="utf-8"))
    reviewed_listing = app.state.store.latest_listing_draft(archive_code)
    assert reviewed["title"] == "Reviewed Charizard"
    assert reviewed["reviewStatus"] == "reviewed"
    assert reviewed["publishing"] == {"published": False, "sellerCredentialsUsed": False}
    assert reviewed_listing["status"] == "reviewed"

    app.state.store.set_listing_status(archive_code, "approved")
    approved = json.loads(draft_path.read_text(encoding="utf-8"))
    assert app.state.store.latest_listing_draft(archive_code)["status"] == "approved"
    assert approved["reviewStatus"] == "approved"
    assert approved["publishing"]["published"] is False

    app.state.store.set_listing_status(archive_code, "rejected")
    assert app.state.store.latest_listing_draft(archive_code)["status"] == "rejected"

    (Path(card["folder_path"]) / "manifest.json").unlink()
    Store(app.state.store.root)
    assert (Path(card["folder_path"]) / "manifest.json").is_file()


def test_recommend_price_separates_sold_active_and_owner_shipping() -> None:
    recommendation = recommend_price(
        [
            {"market_status": "sold", "total_buyer_cost": "50"},
            {"market_status": "sold", "total_buyer_cost": "70"},
            {"market_status": "active", "total_buyer_cost": "90"},
        ]
    )

    assert recommendation.sold_count == 2
    assert recommendation.active_count == 1
    assert recommendation.median_sold_total == 60
    assert recommendation.lowest_sold_total == 50
    assert recommendation.highest_sold_total == 70
    assert recommendation.suggested_total_low == 54
    assert recommendation.suggested_total_high == 66
    assert recommendation.suggested_item_low == 20
    assert recommendation.suggested_item_high == 32
    assert recommendation.owner_shipping_charge == 34


def test_recommend_price_requires_sold_evidence() -> None:
    try:
        recommend_price([{"market_status": "active", "total_buyer_cost": "50"}])
    except ValueError as error:
        assert "sold comparable" in str(error)
    else:
        raise AssertionError("Expected pricing without sold evidence to fail")
