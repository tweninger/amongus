from __future__ import annotations

import os
import sys

from playwright.sync_api import Error, sync_playwright


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011/"
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ".playwright-browsers")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browser_path

    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        try:
            page.goto(url, wait_until="networkidle", timeout=15_000)
            page.locator("#matchmaking-panel").wait_for(state="visible", timeout=10_000)
            roster = page.locator("#matchmaking-roster")
            roster.wait_for(state="visible", timeout=10_000)
            icons = roster.locator(".lobby-player-sprite")
            icon_count = icons.count()
            visible_icons = sum(1 for i in range(icon_count) if icons.nth(i).is_visible())
            status_text = page.locator("#matchmaking-status").inner_text(timeout=5_000)

            if visible_icons < 5:
                raise AssertionError(f"Expected at least 5 visible matchmaking icons, saw {visible_icons}")
            if not status_text.strip():
                raise AssertionError("Expected matchmaking status text to be visible")
            if page_errors:
                raise AssertionError(f"Browser page errors: {page_errors}")
            if console_errors:
                raise AssertionError(f"Browser console errors: {console_errors}")

            print(f"matchmaking ok: {visible_icons} visible icons, status={status_text!r}")
            return 0
        except (AssertionError, Error) as exc:
            print(f"matchmaking check failed: {exc}", file=sys.stderr)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
