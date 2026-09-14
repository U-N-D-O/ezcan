"""Official eBay Sell API integration for the computer-side listing workflow.

The phone app deliberately has no eBay responsibility.  This module keeps the
seller authorization and publishing path on the computer, where a listing can
be assembled from an archived card and sent directly to eBay without using a
browser automation session.

No eBay password, cookie, or access token is written to the project files.
Refresh tokens are delegated to a token store supplied by the application.
"""

from __future__ import annotations

import mimetypes
import os
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from description_html import fill_image_gallery
from listing_rules import (
    CONDITION_DISCLAIMER,
    HANDLING_TIME_DAYS,
    ITEM_LOCATION_CITY,
    ITEM_LOCATION_COUNTRY,
    SHIPPING_FLAT_RATE,
)


EBAY_SCOPE_SELL_INVENTORY = "https://api.ebay.com/oauth/api_scope/sell.inventory"
EBAY_SCOPE_SELL_ACCOUNT = "https://api.ebay.com/oauth/api_scope/sell.account"


class EbayIntegrationError(RuntimeError):
    """Base error shown by the computer-side listing workflow."""


class EbayNotConfigured(EbayIntegrationError):
    """The eBay developer application has not been configured yet."""


class EbayNotConnected(EbayIntegrationError):
    """The seller has not completed the one-time OAuth authorization."""


class EbayAPIError(EbayIntegrationError):
    """An eBay endpoint rejected a request."""

    def __init__(self, status_code: int, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True)
class EbayConfig:
    """Computer-side eBay application settings.

    These values are intentionally read from environment/configuration rather
    than being embedded in the repository.  ``ru_name`` is the eBay redirect
    name registered for the developer application.
    """

    client_id: str
    client_secret: str
    ru_name: str
    marketplace_id: str = "EBAY_US"
    environment: str = "production"
    category_id: str = ""
    merchant_location_key: str = ""
    fulfillment_policy_id: str = ""
    payment_policy_id: str = ""
    return_policy_id: str = ""
    store_category: str = "Non-TCG"

    @classmethod
    def from_environment(cls) -> "EbayConfig":
        return cls(
            client_id=os.getenv("EBAY_CLIENT_ID", "").strip(),
            client_secret=os.getenv("EBAY_CLIENT_SECRET", "").strip(),
            ru_name=os.getenv("EBAY_RU_NAME", "").strip(),
            marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US").strip() or "EBAY_US",
            environment=os.getenv("EBAY_ENVIRONMENT", "production").strip().lower() or "production",
            category_id=os.getenv("EBAY_CATEGORY_ID", "").strip(),
            merchant_location_key=os.getenv("EBAY_MERCHANT_LOCATION_KEY", "").strip(),
            fulfillment_policy_id=os.getenv("EBAY_FULFILLMENT_POLICY_ID", "").strip(),
            payment_policy_id=os.getenv("EBAY_PAYMENT_POLICY_ID", "").strip(),
            return_policy_id=os.getenv("EBAY_RETURN_POLICY_ID", "").strip(),
            store_category=os.getenv("EBAY_STORE_CATEGORY", "Non-TCG").strip() or "Non-TCG",
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.ru_name)

    @property
    def publishing_configured(self) -> bool:
        return self.configured and all(
            (
                self.category_id,
                self.merchant_location_key,
                self.fulfillment_policy_id,
                self.payment_policy_id,
                self.return_policy_id,
            )
        )

    @property
    def api_base(self) -> str:
        return "https://api.sandbox.ebay.com" if self.environment == "sandbox" else "https://api.ebay.com"

    @property
    def auth_base(self) -> str:
        return "https://auth.sandbox.ebay.com" if self.environment == "sandbox" else "https://auth.ebay.com"

    @property
    def media_base(self) -> str:
        return "https://apim.sandbox.ebay.com" if self.environment == "sandbox" else "https://apim.ebay.com"


class RefreshTokenStore(Protocol):
    def load(self) -> str | None:
        ...

    def save(self, refresh_token: str) -> None:
        ...

    def clear(self) -> None:
        ...


class EnvironmentRefreshTokenStore:
    """Small adapter for development and packaging.

    Production UI should replace this with Windows Credential Manager.  The
    adapter never writes the refresh token to the workspace.
    """

    def load(self) -> str | None:
        value = os.getenv("EBAY_REFRESH_TOKEN", "").strip()
        return value or None

    def save(self, refresh_token: str) -> None:
        # Deliberately do not write credentials to disk.  The UI can inject a
        # secure OS-backed store when it is initialized.
        os.environ["EBAY_REFRESH_TOKEN"] = refresh_token

    def clear(self) -> None:
        os.environ.pop("EBAY_REFRESH_TOKEN", None)


class ComputerRefreshTokenStore:
    """Use Windows Credential Manager when the optional keyring package exists.

    The environment adapter remains useful for automated tests and a first
    development run.  A packaged Windows build installs ``keyring`` and keeps
    the long-lived eBay refresh token outside the workspace and source files.
    """

    service_name = "SugimoriGemArchive.eBay"
    account_name = "seller-refresh-token"

    def __init__(self) -> None:
        self._fallback = EnvironmentRefreshTokenStore()

    @staticmethod
    def _keyring() -> Any | None:
        try:
            import keyring  # type: ignore
        except ImportError:
            return None
        return keyring

    def load(self) -> str | None:
        keyring = self._keyring()
        if keyring is None:
            return self._fallback.load()
        try:
            return keyring.get_password(self.service_name, self.account_name)
        except Exception:
            return self._fallback.load()

    def save(self, refresh_token: str) -> None:
        keyring = self._keyring()
        if keyring is None:
            self._fallback.save(refresh_token)
            return
        try:
            keyring.set_password(self.service_name, self.account_name, refresh_token)
        except Exception as error:
            raise EbayIntegrationError(
                "Windows could not securely save the eBay connection. Install keyring and try again."
            ) from error

    def clear(self) -> None:
        keyring = self._keyring()
        if keyring is None:
            self._fallback.clear()
            return
        try:
            keyring.delete_password(self.service_name, self.account_name)
        except Exception:
            # Deleting an already absent credential is a successful disconnect.
            pass


@dataclass
class _AccessToken:
    value: str
    expires_at: float


class EbayOAuth:
    """OAuth authorization-code and refresh-token flow for the computer."""

    def __init__(
        self,
        config: EbayConfig,
        token_store: RefreshTokenStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.token_store = token_store or EnvironmentRefreshTokenStore()
        self.client = client or httpx.Client(timeout=30.0)
        self._access_token: _AccessToken | None = None

    def _require_configured(self) -> None:
        if not self.config.configured:
            raise EbayNotConfigured(
                "Configure the eBay developer App ID, Cert ID, and RuName on the computer first."
            )

    def authorization_url(self, state: str | None = None) -> str:
        self._require_configured()
        query = urlencode(
            {
                "client_id": self.config.client_id,
                "redirect_uri": self.config.ru_name,
                "response_type": "code",
                "state": state or secrets.token_urlsafe(24),
                "scope": " ".join((EBAY_SCOPE_SELL_INVENTORY, EBAY_SCOPE_SELL_ACCOUNT)),
            }
        )
        return f"{self.config.auth_base}/oauth2/authorize?{query}"

    def exchange_authorization_code(self, code: str) -> dict[str, Any]:
        self._require_configured()
        if not code.strip():
            raise EbayIntegrationError("The eBay authorization code was empty.")
        response = self.client.post(
            f"{self.config.api_base}/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code.strip(),
                "redirect_uri": self.config.ru_name,
            },
            auth=(self.config.client_id, self.config.client_secret),
        )
        payload = self._json_or_text(response)
        if response.status_code >= 400:
            raise EbayAPIError(response.status_code, "eBay authorization was rejected.", payload)
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise EbayIntegrationError("eBay authorization succeeded without a refresh token.")
        self.token_store.save(refresh_token)
        self._set_access_token(payload)
        return payload

    def disconnect(self) -> None:
        self._access_token = None
        self.token_store.clear()

    def access_token(self) -> str:
        if self._access_token and self._access_token.expires_at > time.time() + 60:
            return self._access_token.value
        self._require_configured()
        refresh_token = self.token_store.load()
        if not refresh_token:
            raise EbayNotConnected("Connect this computer to the eBay seller account first.")
        response = self.client.post(
            f"{self.config.api_base}/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join((EBAY_SCOPE_SELL_INVENTORY, EBAY_SCOPE_SELL_ACCOUNT)),
            },
            auth=(self.config.client_id, self.config.client_secret),
        )
        payload = self._json_or_text(response)
        if response.status_code >= 400:
            raise EbayAPIError(response.status_code, "eBay access could not be refreshed.", payload)
        self._set_access_token(payload)
        return self._access_token.value

    def _set_access_token(self, payload: dict[str, Any]) -> None:
        token = str(payload.get("access_token", ""))
        if not token:
            raise EbayIntegrationError("eBay returned no access token.")
        self._access_token = _AccessToken(token, time.time() + int(payload.get("expires_in", 7200)))

    @staticmethod
    def _json_or_text(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
            return value if isinstance(value, dict) else {"value": value}
        except ValueError:
            return {"message": response.text}


class EbaySellClient:
    """Typed, small surface over the eBay Sell APIs used by Ezcan."""

    def __init__(self, oauth: EbayOAuth, client: httpx.Client | None = None) -> None:
        self.oauth = oauth
        self.config = oauth.config
        self.client = client or oauth.client

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        request_headers = {
            "Authorization": f"Bearer {self.oauth.access_token()}",
            "Accept": "application/json",
        }
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        response = self.client.request(method, url, headers=request_headers, json=json_body, content=content)
        if response.status_code == 401 and retry_auth:
            self.oauth._access_token = None
            return self._request(
                method,
                url,
                json_body=json_body,
                headers=headers,
                content=content,
                retry_auth=False,
            )
        if response.status_code >= 400:
            payload = EbayOAuth._json_or_text(response)
            detail = payload.get("errors") or payload.get("message") or "eBay request failed."
            raise EbayAPIError(response.status_code, str(detail), payload)
        return response

    def default_category_tree_id(self) -> str:
        response = self._request(
            "GET",
            f"{self.config.api_base}/commerce/taxonomy/v1/get_default_category_tree_id",
            headers={"X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id},
        )
        return str(response.json()["categoryTreeId"])

    def item_aspects(self, category_tree_id: str, category_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_item_aspects_for_category?category_id={category_id}",
            headers={
                "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id,
                "X-EBAY-C-ENDUSERCTX": f"contextualLocation={self.config.marketplace_id}",
            },
        )
        return response.json()

    def fulfillment_policies(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/sell/account/v1/fulfillment_policy?marketplace_id={self.config.marketplace_id}",
            headers={"Content-Language": "en-US"},
        )
        return response.json()

    def fulfillment_policy(self, policy_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/sell/account/v1/fulfillment_policy/{policy_id}",
            headers={"Content-Language": "en-US"},
        )
        return response.json()

    def validate_fixed_shipping_policy(self, policy_id: str) -> dict[str, Any]:
        """Verify the saved eBay policy before any listing is published."""
        policy = self.fulfillment_policy(policy_id)
        handling = policy.get("handlingTime", {})
        if handling.get("value") != HANDLING_TIME_DAYS or str(handling.get("unit", "")).upper() != "DAY":
            raise EbayIntegrationError("The eBay fulfillment policy does not have 2 business days handling time.")
        options = {str(option.get("optionType", "")).upper(): option for option in policy.get("shippingOptions", [])}
        for option_type in ("DOMESTIC", "INTERNATIONAL"):
            option = options.get(option_type)
            if not option or str(option.get("costType", "")).upper() != "FLAT_RATE":
                raise EbayIntegrationError(f"The eBay fulfillment policy must use flat-rate {option_type.lower()} shipping.")
            services = option.get("shippingServices", [])
            if not services:
                raise EbayIntegrationError(f"The eBay fulfillment policy has no {option_type.lower()} shipping service.")
            first = services[0]
            amount = (first.get("shippingCost") or {}).get("value")
            try:
                amount_matches = Decimal(str(amount)) == SHIPPING_FLAT_RATE
            except (InvalidOperation, TypeError, ValueError):
                amount_matches = False
            if not amount_matches or first.get("freeShipping") is True:
                raise EbayIntegrationError(f"The eBay fulfillment policy must charge ${SHIPPING_FLAT_RATE} for {option_type.lower()} shipping.")
        return policy

    def payment_policies(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/sell/account/v1/payment_policy?marketplace_id={self.config.marketplace_id}",
            headers={"Content-Language": "en-US"},
        )
        return response.json()

    def return_policies(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/sell/account/v1/return_policy?marketplace_id={self.config.marketplace_id}",
            headers={"Content-Language": "en-US"},
        )
        return response.json()

    def inventory_locations(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/sell/inventory/v1/inventory_location?limit=100",
        )
        return response.json()

    def inventory_location(self, merchant_location_key: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"{self.config.api_base}/sell/inventory/v1/inventory_location/{merchant_location_key}",
        )
        return response.json()

    def validate_fixed_item_location(self, merchant_location_key: str) -> dict[str, Any]:
        location = self.inventory_location(merchant_location_key)
        address = location.get("location", {}).get("address", location.get("address", {}))
        country = str(address.get("country", "")).strip().lower()
        city = str(address.get("city", "")).strip().lower()
        if country not in {ITEM_LOCATION_COUNTRY.lower(), "gl"} or city != ITEM_LOCATION_CITY.lower():
            raise EbayIntegrationError(
                f"The eBay inventory location must be {ITEM_LOCATION_CITY}, {ITEM_LOCATION_COUNTRY}."
            )
        return location

    def upload_image(self, image_path: Path) -> str:
        path = Path(image_path)
        if not path.is_file():
            raise EbayIntegrationError(f"Image file was not found: {path}")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as image_file:
            response = self._request(
                "POST",
                f"{self.config.media_base}/commerce/media/v1_beta/image/create_image_from_file",
                headers={"Content-Type": mime},
                content=image_file.read(),
            )
        payload = EbayOAuth._json_or_text(response)
        image_url = payload.get("imageUrl") or payload.get("image_url")
        if not image_url:
            image_url = response.headers.get("Location")
        if not image_url:
            raise EbayIntegrationError("eBay accepted the image but returned no image URL.")
        return str(image_url)

    def upload_video(self, video_path: Path, *, title: str, description: str = "") -> str:
        path = Path(video_path)
        if not path.is_file():
            raise EbayIntegrationError(f"Video file was not found: {path}")
        size = path.stat().st_size
        if size > 150 * 1024 * 1024:
            raise EbayIntegrationError("eBay video files must be 150 MB or smaller.")
        created = self._request(
            "POST",
            f"{self.config.media_base}/commerce/media/v1/video",
            json_body={
                "title": title[:80] or "Card condition video",
                "size": size,
                "classification": "ITEM",
                "description": description[:200] if description else None,
            },
        )
        location = created.headers.get("Location")
        payload = EbayOAuth._json_or_text(created)
        video_id = payload.get("videoId") or (location.rstrip("/").split("/")[-1] if location else None)
        if not video_id:
            raise EbayIntegrationError("eBay created the video resource but returned no video ID.")
        with path.open("rb") as video_file:
            self._request(
                "POST",
                f"{self.config.media_base}/commerce/media/v1/video/{video_id}/upload",
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
                content=video_file.read(),
            )
        return str(video_id)

    def replace_inventory_item(
        self,
        sku: str,
        *,
        title: str,
        description_html: str,
        image_urls: list[str],
        aspects: dict[str, list[str]] | None = None,
        condition: str = "USED",
        quantity: int = 1,
        video_ids: list[str] | None = None,
    ) -> None:
        if not sku.strip():
            raise EbayIntegrationError("An archive ID is required as the eBay SKU.")
        if not image_urls:
            raise EbayIntegrationError("At least one eBay-hosted image is required.")
        product: dict[str, Any] = {
            "title": title[:80],
            "description": description_html,
            "imageUrls": image_urls,
        }
        if aspects:
            product["aspects"] = aspects
        if video_ids:
            product["videoIds"] = video_ids
        self._request(
            "PUT",
            f"{self.config.api_base}/sell/inventory/v1/inventory_item/{sku}",
            json_body={
                "availability": {"shipToLocationAvailability": {"quantity": quantity}},
                "condition": condition,
                "conditionDescription": CONDITION_DISCLAIMER,
                "product": product,
            },
            headers={"Content-Language": "en-US"},
        )

    def create_offer(
        self,
        sku: str,
        *,
        category_id: str,
        price: str,
        currency: str = "USD",
        merchant_location_key: str,
        fulfillment_policy_id: str,
        payment_policy_id: str,
        return_policy_id: str,
        store_category_names: list[str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "sku": sku,
            "marketplaceId": self.config.marketplace_id,
            "format": "FIXED_PRICE",
            "availableQuantity": 1,
            "categoryId": category_id,
            "merchantLocationKey": merchant_location_key,
            "pricingSummary": {"price": {"value": str(price), "currency": currency}},
            "listingPolicies": {
                "fulfillmentPolicyId": fulfillment_policy_id,
                "paymentPolicyId": payment_policy_id,
                "returnPolicyId": return_policy_id,
            },
        }
        if store_category_names:
            payload["storeCategoryNames"] = store_category_names
        response = self._request(
            "POST",
            f"{self.config.api_base}/sell/inventory/v1/offer",
            json_body=payload,
            headers={"Content-Language": "en-US"},
        )
        offer_id = response.json().get("offerId")
        if not offer_id:
            raise EbayIntegrationError("eBay created the offer but returned no offer ID.")
        return str(offer_id)

    def publish_offer(self, offer_id: str) -> str:
        response = self._request(
            "POST",
            f"{self.config.api_base}/sell/inventory/v1/offer/{offer_id}/publish",
        )
        listing_id = response.json().get("listingId")
        if not listing_id:
            raise EbayIntegrationError("eBay published the offer but returned no listing ID.")
        return str(listing_id)

    def publish_listing(
        self,
        sku: str,
        *,
        title: str,
        description_html: str,
        image_paths: list[Path],
        video_paths: list[Path] | None,
        aspects: dict[str, list[str]] | None,
        category_id: str,
        price: str,
        merchant_location_key: str,
        fulfillment_policy_id: str,
        payment_policy_id: str,
        return_policy_id: str,
        condition: str = "USED",
        store_category_names: list[str] | None = None,
    ) -> dict[str, str | list[str]]:
        """Upload media, replace the SKU, create an offer, and publish it.

        This is intentionally one computer-side operation.  If a later step
        fails, the SKU and offer ID can be safely retried instead of creating a
        second archive record or asking the seller to repeat data entry.
        """
        if not image_paths:
            raise EbayIntegrationError("The listing has no archived images.")
        image_urls = [self.upload_image(path) for path in image_paths[:24]]
        video_ids = [
            self.upload_video(path, title=title, description="Archive condition video")
            for path in (video_paths or [])
        ]
        self.replace_inventory_item(
            sku,
            title=title,
            description_html=fill_image_gallery(description_html, image_urls),
            image_urls=image_urls,
            aspects=aspects,
            condition=condition,
            video_ids=video_ids,
        )
        offer_id = self.create_offer(
            sku,
            category_id=category_id,
            price=price,
            merchant_location_key=merchant_location_key,
            fulfillment_policy_id=fulfillment_policy_id,
            payment_policy_id=payment_policy_id,
            return_policy_id=return_policy_id,
            store_category_names=store_category_names,
        )
        listing_id = self.publish_offer(offer_id)
        return {"sku": sku, "offerId": offer_id, "listingId": listing_id, "imageUrls": image_urls, "videoIds": video_ids}
