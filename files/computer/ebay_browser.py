"""Computer-only eBay page workflow for visual identification and Sell One Like This.

This worker uses a persistent Edge/Chrome profile and Playwright.  It never
receives anything from the iPhone and it does not attempt to bypass eBay login,
CAPTCHA, 2FA, or other seller checks.  If eBay presents one of those checks,
the worker stops and reports it to the computer UI.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any, Callable
from urllib.parse import urlparse

from listing_rules import (
    COMBINED_SHIPPING_ENABLED,
    CONDITION_DISCLAIMER,
    HANDLING_TIME_DAYS,
    ITEM_LOCATION_CITY,
    ITEM_LOCATION_COUNTRY,
    SHIPPING_FLAT_RATE,
    SHIPPING_SERVICE,
    SHIPPING_TRANSIT_TIME,
    REQUIRE_IMMEDIATE_PAYMENT,
)


class EbayBrowserError(RuntimeError):
    """A page automation step could not be completed safely."""


class EbayBrowserUnavailable(EbayBrowserError):
    """Playwright or a supported browser is not installed."""


class EbayLoginRequired(EbayBrowserError):
    """The dedicated computer-side eBay profile is not signed in."""


@dataclass(frozen=True)
class VisualMatch:
    rank: int
    url: str
    title: str
    image_url: str
    price: str = ""
    shipping: str = ""


@dataclass(frozen=True)
class PreparedSellDraft:
    source_url: str
    draft_url: str
    uploaded_files: tuple[str, ...]


class EbayBrowserWorker:
    """A single Playwright thread that keeps the eBay page session alive."""

    def __init__(self, profile_path: Path, browser_path: str | None = None, headless: bool | None = None) -> None:
        self.profile_path = Path(profile_path)
        self.browser_path = browser_path or self._find_browser()
        self.headless = (
            os.getenv("EZCAN_EBAY_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}
            if headless is None
            else headless
        )
        self._tasks: Queue[tuple[Callable[[Any], Any], Queue[tuple[bool, Any]]]] = Queue()
        self._closed = False
        self._startup_error: Exception | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ezcan-ebay-pages")
        self._thread.start()

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            self._startup_error = EbayBrowserUnavailable("Playwright is not installed. Run pip install -r requirements.txt.")
            self._ready.set()
            return

        try:
            self.profile_path.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as playwright:
                launch_options: dict[str, Any] = {
                    "headless": self.headless,
                    "viewport": {"width": 1440, "height": 1000},
                }
                if self.browser_path:
                    launch_options["executable_path"] = self.browser_path
                context = playwright.chromium.launch_persistent_context(str(self.profile_path), **launch_options)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    self._page = page
                    while True:
                        task = self._tasks.get()
                        if task is None:
                            break
                        operation, result_queue = task
                        try:
                            result_queue.put((True, operation(page)))
                        except Exception as error:
                            result_queue.put((False, error))
                finally:
                    context.close()
        except Exception as error:
            self._startup_error = EbayBrowserUnavailable(f"eBay page automation could not start: {error}")
            self._finish_pending(self._startup_error)
        finally:
            self._ready.set()

    def _finish_pending(self, error: Exception) -> None:
        while not self._tasks.empty():
            try:
                _, result_queue = self._tasks.get_nowait()
            except Exception:
                return
            result_queue.put((False, error))

    def _call(self, operation: Callable[[Any], Any]) -> Any:
        if self._closed:
            raise EbayBrowserError("The eBay page session is closed.")
        self._ready.wait(timeout=10)
        startup_error = getattr(self, "_startup_error", None)
        if startup_error:
            raise startup_error
        result_queue: Queue[tuple[bool, Any]] = Queue(maxsize=1)
        self._tasks.put((operation, result_queue))
        success, result = result_queue.get()
        if success:
            return result
        raise result

    def visual_search(self, image_path: Path) -> list[VisualMatch]:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"The visual-search image does not exist: {path}")
        return self._call(lambda page: self._visual_search_on_page(page, path))

    def prepare_sell_one_like_this(self, match: VisualMatch, files: list[Path]) -> PreparedSellDraft:
        safe_files = [Path(path) for path in files if Path(path).is_file()]
        if not safe_files:
            raise EbayBrowserError("No archived photos or video were available for upload.")
        return self._call(lambda page: self._sell_one_like_this_on_page(page, match, safe_files))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tasks.put(None)  # type: ignore[arg-type]
        if self._thread.is_alive():
            self._thread.join(timeout=4)

    @staticmethod
    def _visual_search_on_page(page: Any, image_path: Path) -> list[VisualMatch]:
        page.goto("https://www.ebay.com/", wait_until="domcontentloaded", timeout=30000)
        EbayBrowserWorker._raise_for_login_or_challenge(page)
        camera = page.locator("button[aria-label*='camera' i], a[aria-label*='camera' i]").first
        if camera.count() == 0:
            camera = page.get_by_text(re.compile("visual search|search by image|camera", re.I)).first
        if camera.count() == 0:
            raise EbayBrowserError("eBay's camera search control was not found on the page.")
        try:
            with page.expect_file_chooser(timeout=6000) as chooser_info:
                camera.click()
            chooser_info.value.set_files(str(image_path))
        except Exception:
            file_input = page.locator("input[type='file']").first
            if file_input.count() == 0:
                raise EbayBrowserError("eBay's image upload control did not open.")
            file_input.set_input_files(str(image_path))
        page.wait_for_timeout(3500)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        EbayBrowserWorker._raise_for_login_or_challenge(page)
        matches = EbayBrowserWorker._scrape_matches(page)
        if not matches:
            raise EbayBrowserError("eBay returned no visual matches for this card image.")
        return matches[:5]

    @staticmethod
    def _scrape_matches(page: Any) -> list[VisualMatch]:
        results: list[VisualMatch] = []
        seen: set[str] = set()
        links = page.locator("a[href*='/itm/']")
        for index in range(min(links.count(), 40)):
            link = links.nth(index)
            href = str(link.get_attribute("href") or "").split("?")[0]
            if not href or href in seen or not re.search(r"/itm/\d+", href):
                continue
            title = str(link.get_attribute("title") or "").strip()
            if not title:
                try:
                    title = link.inner_text(timeout=1000).strip()
                except Exception:
                    title = "eBay visual match"
            if not title or title.lower() in {"shop on ebay", "see details"}:
                continue
            image_url = ""
            image = link.locator("img").first
            if image.count():
                image_url = str(image.get_attribute("src") or image.get_attribute("data-src") or "")
            container = link.locator("xpath=ancestor::*[self::li or @class][1]")
            text = ""
            try:
                text = container.inner_text(timeout=500).strip()
            except Exception:
                pass
            results.append(VisualMatch(len(results) + 1, href, title, image_url, text[:240]))
            seen.add(href)
        return results

    @staticmethod
    def _sell_one_like_this_on_page(page: Any, match: VisualMatch, files: list[Path]) -> PreparedSellDraft:
        page.goto(match.url, wait_until="domcontentloaded", timeout=30000)
        EbayBrowserWorker._raise_for_login_or_challenge(page)
        sell = page.get_by_text(re.compile(r"^sell one like this$", re.I)).first
        if sell.count() == 0:
            sell = page.get_by_role("button", name=re.compile(r"sell one like this", re.I)).first
        if sell.count() == 0:
            raise EbayBrowserError("The selected eBay listing has no 'Sell one like this' action.")
        current_pages = set(page.context.pages)
        sell.click()
        page.wait_for_timeout(2500)
        new_page = next((candidate for candidate in page.context.pages if candidate not in current_pages), page)
        new_page.wait_for_load_state("domcontentloaded", timeout=30000)
        EbayBrowserWorker._raise_for_login_or_challenge(new_page)
        upload = new_page.locator("input[type='file']").first
        if upload.count() == 0:
            trigger = new_page.get_by_text(re.compile("upload from computer|add photos|photos", re.I)).first
            if trigger.count():
                trigger.click()
                new_page.wait_for_timeout(500)
            upload = new_page.locator("input[type='file']").first
        if upload.count() == 0:
            raise EbayBrowserError("The eBay listing draft has no computer upload control.")
        upload.set_input_files([str(path) for path in files])
        new_page.wait_for_timeout(2000)
        EbayBrowserWorker._apply_fixed_listing_rules(new_page)
        EbayBrowserWorker._apply_fixed_shipping_rules(new_page)
        EbayBrowserWorker._apply_payment_rules(new_page)
        return PreparedSellDraft(match.url, new_page.url, tuple(str(path) for path in files))

    @staticmethod
    def _apply_payment_rules(page: Any) -> None:
        immediate_payment = EbayBrowserWorker._set_checkbox(
            page,
            re.compile(r"require immediate payment|immediate payment", re.I),
            checked=REQUIRE_IMMEDIATE_PAYMENT,
        )
        if not immediate_payment:
            raise EbayBrowserError(
                "eBay did not expose the immediate-payment setting. The draft was stopped so it cannot accidentally prevent combined payments."
            )
        if not COMBINED_SHIPPING_ENABLED:
            raise EbayBrowserError("Combined shipping is disabled by the fixed store rules.")

    @staticmethod
    def _apply_fixed_shipping_rules(page: Any) -> None:
        service = EbayBrowserWorker._set_choice(page, re.compile(r"shipping service|delivery service", re.I), re.compile(re.escape(SHIPPING_SERVICE), re.I))
        handling = EbayBrowserWorker._set_text_controls(page, re.compile(r"handling time", re.I), str(HANDLING_TIME_DAYS), minimum=1)
        shipping_costs = EbayBrowserWorker._set_text_controls(page, re.compile(r"shipping.*(cost|price|rate)|(cost|price|rate).*shipping", re.I), f"{SHIPPING_FLAT_RATE:.2f}", minimum=2)
        country = EbayBrowserWorker._set_choice(page, re.compile(r"country|region", re.I), re.compile(r"^greenland$", re.I))
        city = EbayBrowserWorker._set_text_controls(page, re.compile(r"item location.*city|city.*item location", re.I), ITEM_LOCATION_CITY, minimum=1)
        transit_text = re.sub(r"\s+", " ", SHIPPING_TRANSIT_TIME).strip()
        visible_text = re.sub(r"\s+", " ", page.locator("body").inner_text(timeout=2000)).strip()
        transit = bool(re.search(r"7\s*-\s*15\s+business\s+days", visible_text, re.I)) or transit_text.lower() in visible_text.lower()
        if not all((service, handling, shipping_costs, country, city, transit)):
            missing = []
            if not service:
                missing.append(SHIPPING_SERVICE)
            if not handling:
                missing.append(f"{HANDLING_TIME_DAYS} business days handling")
            if not shipping_costs:
                missing.append(f"${SHIPPING_FLAT_RATE:.2f} domestic and international shipping")
            if not country or not city:
                missing.append(f"{ITEM_LOCATION_CITY}, {ITEM_LOCATION_COUNTRY} item location")
            if not transit:
                missing.append(SHIPPING_TRANSIT_TIME)
            raise EbayBrowserError(
                "eBay did not expose the required shipping controls: "
                + ", ".join(missing)
                + ". The draft was stopped so inherited shipping settings cannot pass through."
            )

    @staticmethod
    def _apply_fixed_listing_rules(page: Any) -> None:
        """Never allow cloned condition or grading data to pass through silently."""
        vintage = EbayBrowserWorker._set_checkbox(page, re.compile(r"vintage", re.I), checked=True)
        condition = EbayBrowserWorker._set_choice(page, re.compile(r"condition", re.I), re.compile(r"^poor$", re.I))
        grading = EbayBrowserWorker._set_choice(page, re.compile(r"graded|grading|professional grader|grade", re.I), re.compile(r"ungraded|not graded|none", re.I))
        condition_description = EbayBrowserWorker._set_text_controls(
            page,
            re.compile(r"condition description", re.I),
            CONDITION_DISCLAIMER,
            minimum=1,
        )
        if not vintage or not condition or not grading or not condition_description:
            missing = []
            if not vintage:
                missing.append("Vintage")
            if not condition:
                missing.append("Poor condition")
            if not grading:
                missing.append("Ungraded")
            if not condition_description:
                missing.append("the condition description")
            raise EbayBrowserError(
                "eBay did not expose the required fixed listing controls: "
                + ", ".join(missing)
                + ". The draft was stopped so no inherited grading or condition can be published."
            )

    @staticmethod
    def _set_checkbox(page: Any, label_pattern: re.Pattern[str], *, checked: bool) -> bool:
        inputs = page.locator("input[type='checkbox']")
        for index in range(inputs.count()):
            control = inputs.nth(index)
            descriptor = " ".join(
                str(control.get_attribute(name) or "")
                for name in ("aria-label", "name", "id", "title")
            )
            if not label_pattern.search(descriptor):
                continue
            if checked:
                control.check()
            else:
                control.uncheck()
            return True
        try:
            label = page.get_by_label(label_pattern).first
            if label.count():
                if checked:
                    label.check()
                else:
                    label.uncheck()
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _set_choice(page: Any, label_pattern: re.Pattern[str], value_pattern: re.Pattern[str]) -> bool:
        for selector in ("select", "[role='combobox']", "button"):
            controls = page.locator(selector)
            for index in range(controls.count()):
                control = controls.nth(index)
                descriptor = " ".join(
                    str(control.get_attribute(name) or "")
                    for name in ("aria-label", "name", "id", "title")
                )
                try:
                    descriptor += " " + control.inner_text(timeout=200)
                except Exception:
                    pass
                if not label_pattern.search(descriptor):
                    continue
                if EbayBrowserWorker._choose_control_value(page, control, selector, value_pattern):
                    return True
        return False

    @staticmethod
    def _set_text_controls(page: Any, label_pattern: re.Pattern[str], value: str, *, minimum: int) -> bool:
        changed = 0
        controls = page.locator("input:not([type='checkbox']):not([type='file']), textarea")
        for index in range(controls.count()):
            control = controls.nth(index)
            descriptor = " ".join(
                str(control.get_attribute(name) or "")
                for name in ("aria-label", "name", "id", "title", "placeholder")
            )
            if not label_pattern.search(descriptor):
                continue
            try:
                control.fill(value)
                changed += 1
            except Exception:
                continue
        return changed >= minimum

    @staticmethod
    def _choose_control_value(page: Any, control: Any, selector: str, value_pattern: re.Pattern[str]) -> bool:
        if selector == "select":
            options = control.locator("option")
            for index in range(options.count()):
                option = options.nth(index)
                text = str(option.inner_text()).strip()
                if value_pattern.search(text):
                    control.select_option(str(option.get_attribute("value") or ""))
                    return True
            return False
        try:
            control.click()
            option = page.get_by_role("option", name=value_pattern).last
            if option.count():
                option.click()
                return True
            option = page.get_by_text(value_pattern).last
            if option.count():
                option.click()
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def _raise_for_login_or_challenge(page: Any) -> None:
        url = str(page.url).lower()
        title = ""
        try:
            title = page.title().lower()
        except Exception:
            pass
        if "signin" in url or "sign in" in title:
            raise EbayLoginRequired("Sign in to eBay through the computer's dedicated eBay profile first.")
        if any(marker in url for marker in ("captcha", "challenge", "verify")):
            raise EbayBrowserError("eBay presented a verification challenge. Complete it in the eBay session, then retry.")

    @staticmethod
    def _find_browser() -> str | None:
        candidates = [
            shutil.which("msedge.exe"),
            shutil.which("chrome.exe"),
            shutil.which("brave.exe"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        return None
