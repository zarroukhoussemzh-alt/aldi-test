#!/usr/bin/env python3
"""
Aldi Talk Auto +1 GB Booker
Logs into the Aldi Talk portal and clicks the +1 GB button.
If the button is gray (not bookable yet), nothing happens.
If it's active (blue), it books 1 GB automatically.

Run via GitHub Actions every 10 minutes.
"""

import asyncio
import os
import sys
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PWTimeout


RUFNUMMER = os.environ.get("ALDI_RUFNUMMER", "017656874563")
PASSWORD  = os.environ.get("ALDI_PASSWORD", "Na240271!!??")

LOGIN_URL     = "https://www.alditalk-kundenportal.de/"
UEBERSICHT_URL = "https://www.alditalk-kundenportal.de/portal/auth/uebersicht/"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


async def run() -> None:
    if not RUFNUMMER or not PASSWORD:
        log("ERROR: Set ALDI_RUFNUMMER and ALDI_PASSWORD environment variables (GitHub Secrets).")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="de-DE",
        )
        page = await context.new_page()

        try:
            # ── 1. Open portal (redirects to login) ──────────────────────────
            log("Opening portal...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2_000)

            # Accept cookie banner if present
            try:
                await page.click("text=Akzeptieren", timeout=4_000)
                log("Cookie banner accepted.")
            except PWTimeout:
                pass

            # ── 2. Login ──────────────────────────────────────────────────────
            # Visible inputs live inside Shadow DOM — use page.locator() which pierces it.
            # Confirmed selectors: placeholder="Rufnummer" and placeholder="Passwort eingeben"
            log("Logging in...")
            ruf_field = page.locator('input[placeholder="Rufnummer"]')
            pw_field  = page.locator('input[placeholder="Passwort eingeben"]')
            await ruf_field.wait_for(state="visible", timeout=15_000)
            await ruf_field.fill(RUFNUMMER)
            await pw_field.fill(PASSWORD)
            # Submit — "Anmelden" button (also in Shadow DOM)
            await page.get_by_text("Anmelden", exact=True).first.click()

            await page.wait_for_url("**/uebersicht/**", timeout=20_000)
            log("Logged in successfully.")

            # ── 3. Wait for Web Components to render ──────────────────────────
            await page.wait_for_load_state("networkidle", timeout=15_000)
            await page.wait_for_timeout(3_000)

            # ── 4. Find the +1 GB button ──────────────────────────────────────
            # The button is a <one-button circle> custom element (unique circle attribute).
            # Text content is "1 GB" (the "+" is rendered as a CSS/SVG icon, not text).
            log("Looking for +1 GB button...")
            btn = page.locator("one-button[circle]")
            count = await btn.count()

            if count == 0:
                log("Button not found on page — skipping.")
                return

            log(f"Button found. Clicking...")

            # Check if disabled attribute is set (gray = disabled)
            is_disabled = await btn.first.get_attribute("disabled")
            if is_disabled is not None:
                log("Button is disabled (not enough data used yet) — skipping.")
                return

            # Click the inner <button> inside the shadow DOM of <one-button circle>
            # force=True on the outer element doesn't trigger the inner click handler.
            clicked = await page.evaluate("""
                () => {
                    const outer = document.querySelector('one-button[circle]');
                    if (!outer) return 'not_found';
                    // Try inner shadow button first
                    if (outer.shadowRoot) {
                        const inner = outer.shadowRoot.querySelector('button, a, [role="button"]');
                        if (inner) { inner.click(); return 'shadow_inner'; }
                    }
                    // Fallback: click the outer element
                    outer.click();
                    return 'outer';
                }
            """)
            log(f"Click sent (method: {clicked})!")

            # Screenshot to see if a confirmation dialog appeared
            await page.wait_for_timeout(2_000)
            await page.screenshot(path="after_click.png", full_page=False)
            log("Saved after_click.png")

            # ── 5. Handle confirmation dialog if one appears ──────────────────
            await page.wait_for_timeout(2_000)
            for label in ["Bestätigen", "Buchen", "Jetzt buchen", "OK", "Ja"]:
                try:
                    confirm = page.get_by_text(label, exact=True)
                    if await confirm.count() > 0:
                        await confirm.first.click(timeout=3_000)
                        log(f"Confirmation clicked: '{label}'")
                        break
                except PWTimeout:
                    pass

            await page.wait_for_timeout(2_000)
            log("Done.")

        except Exception as e:
            log(f"FATAL ERROR: {e}")
            try:
                await page.screenshot(path="error.png", full_page=True)
                log("Saved error.png for debugging.")
            except Exception:
                pass
            sys.exit(1)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
