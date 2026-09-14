from __future__ import annotations

import json
from pathlib import Path

import httpx

from ebay_api import EbayConfig, EbayOAuth, EbaySellClient


class MemoryTokenStore:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def load(self) -> str | None:
        return self.token

    def save(self, refresh_token: str) -> None:
        self.token = refresh_token

    def clear(self) -> None:
        self.token = None


def make_config() -> EbayConfig:
    return EbayConfig("app-id", "app-secret", "runame", marketplace_id="EBAY_US")


def test_authorization_url_contains_required_scopes_and_redirect() -> None:
    oauth = EbayOAuth(make_config(), MemoryTokenStore())

    url = oauth.authorization_url(state="fixed-state")

    assert "client_id=app-id" in url
    assert "redirect_uri=runame" in url
    assert "state=fixed-state" in url
    assert "sell.inventory" in url
    assert "sell.account" in url


def test_exchange_code_saves_refresh_token() -> None:
    store = MemoryTokenStore()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/identity/v1/oauth2/token")
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(
            200,
            json={"access_token": "access", "expires_in": 3600, "refresh_token": "refresh"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oauth = EbayOAuth(make_config(), store, client)

    payload = oauth.exchange_authorization_code("one-time-code")

    assert payload["access_token"] == "access"
    assert store.token == "refresh"
    assert oauth.access_token() == "access"


def test_sell_client_refreshes_after_unauthorized() -> None:
    store = MemoryTokenStore("refresh")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})
        if len(calls) == 2:
            return httpx.Response(401, json={"errors": [{"message": "expired"}]})
        return httpx.Response(200, json={"categoryTreeId": "0"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oauth = EbayOAuth(make_config(), store, client)
    sell = EbaySellClient(oauth, client)

    assert sell.default_category_tree_id() == "0"
    assert calls.count("/commerce/taxonomy/v1/get_default_category_tree_id") == 2


def test_category_aspects_pass_category_id_as_query_parameter() -> None:
    store = MemoryTokenStore("refresh")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        assert request.url.params["category_id"] == "183454"
        assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
        return httpx.Response(200, json={"aspects": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sell = EbaySellClient(EbayOAuth(make_config(), store, client), client)

    assert sell.item_aspects("0", "183454") == {"aspects": []}


def test_seller_setup_endpoints_are_available_to_computer_only() -> None:
    store = MemoryTokenStore("refresh")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        if request.url.path.endswith("/fulfillment_policy"):
            return httpx.Response(200, json={"fulfillmentPolicies": [{"fulfillmentPolicyId": "ship-1"}]})
        if request.url.path.endswith("/payment_policy"):
            return httpx.Response(200, json={"paymentPolicies": [{"paymentPolicyId": "pay-1"}]})
        if request.url.path.endswith("/return_policy"):
            return httpx.Response(200, json={"returnPolicies": [{"returnPolicyId": "return-1"}]})
        assert request.url.path.endswith("/inventory_location")
        return httpx.Response(200, json={"locations": [{"merchantLocationKey": "home"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sell = EbaySellClient(EbayOAuth(make_config(), store, client), client)

    assert sell.fulfillment_policies()["fulfillmentPolicies"][0]["fulfillmentPolicyId"] == "ship-1"
    assert sell.payment_policies()["paymentPolicies"][0]["paymentPolicyId"] == "pay-1"
    assert sell.return_policies()["returnPolicies"][0]["returnPolicyId"] == "return-1"
    assert sell.inventory_locations()["locations"][0]["merchantLocationKey"] == "home"


def test_fixed_shipping_policy_is_verified_before_publish() -> None:
    store = MemoryTokenStore("refresh")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        assert request.url.path.endswith("/fulfillment_policy/policy-1")
        return httpx.Response(
            200,
            json={
                "handlingTime": {"value": 2, "unit": "DAY"},
                "shippingOptions": [
                    {"optionType": "DOMESTIC", "costType": "FLAT_RATE", "shippingServices": [{"shippingCost": {"value": "35.0"}, "freeShipping": False}]},
                    {"optionType": "INTERNATIONAL", "costType": "FLAT_RATE", "shippingServices": [{"shippingCost": {"value": "35.00"}, "freeShipping": False}]},
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sell = EbaySellClient(EbayOAuth(make_config(), store, client), client)

    assert sell.validate_fixed_shipping_policy("policy-1")["handlingTime"]["value"] == 2


def test_fixed_item_location_is_verified() -> None:
    store = MemoryTokenStore("refresh")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        assert request.url.path.endswith("/inventory_location/nuuk")
        return httpx.Response(200, json={"location": {"address": {"country": "GL", "city": "Nuuk"}}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sell = EbaySellClient(EbayOAuth(make_config(), store, client), client)

    assert sell.validate_fixed_item_location("nuuk")["location"]["address"]["city"] == "Nuuk"


def test_upload_image_sends_binary_image_and_returns_url(tmp_path: Path) -> None:
    store = MemoryTokenStore("refresh")
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        assert request.headers["content-type"] == "image/jpeg"
        assert request.read() == b"jpeg-bytes"
        return httpx.Response(200, json={"imageUrl": "https://i.ebayimg.com/images/g/test/s-l1600.jpg"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sell = EbaySellClient(EbayOAuth(make_config(), store, client), client)

    assert sell.upload_image(image).startswith("https://i.ebayimg.com/")


def test_replace_inventory_item_uses_archive_sku_and_html_description(tmp_path: Path) -> None:
    store = MemoryTokenStore("refresh")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sell = EbaySellClient(EbayOAuth(make_config(), store, client), client)

    sell.replace_inventory_item(
        "A0A0",
        title="Japanese Carddass Bulbasaur",
        description_html="<div data-archive-id='A0A0'>A0A0</div>",
        image_urls=["https://i.ebayimg.com/images/g/test/s-l1600.jpg"],
        aspects={"Game": ["Pokémon"]},
    )

    assert captured["path"].endswith("/sell/inventory/v1/inventory_item/A0A0")
    assert captured["body"]["product"]["description"].startswith("<div")
    assert captured["body"]["product"]["aspects"] == {"Game": ["Pokémon"]}
