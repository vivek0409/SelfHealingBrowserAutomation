import argparse
import json
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# Best-effort dismissal of common consent / cookie / popup overlays that
# intercept pointer events and block clicks (Amazon, OneTrust, generic modals).
OVERLAY_DISMISS_SELECTORS = [
    "#sp-cc-accept",
    "input#sp-cc-accept",
    ".a-popover-wrapper .a-button-close",
    "[data-action='a-popover-floating-close']",
    "button#onetrust-accept-btn-handler",
    "#onetrust-accept-btn-handler",
    "[aria-label='Close']",
    "[aria-label='close']",
    "button[title='Close']",
    ".modal-close, .close-button, .icon-close",
]


# Short pause after every action so the next element has time to render before
# the following step runs (handles UIs that update asynchronously after a click/fill).
SETTLE_MS = 600


def settle(page):
    try:
        page.wait_for_timeout(SETTLE_MS)
    except Exception:
        pass


def dismiss_overlays(page):
    for sel in OVERLAY_DISMISS_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(timeout=1000)
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def navigate(page, url, timeout):
    # Go to the page and wait for it to actually finish loading before any
    # subsequent step acts, so actions never run against a half-loaded page.
    page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    for state in ("load", "networkidle"):
        try:
            page.wait_for_load_state(state, timeout=timeout)
        except Exception:
            # networkidle can legitimately never settle on busy pages; the
            # domcontentloaded/load above is enough to proceed safely.
            pass
    settle(page)


def safe_fill(page, selector, value, timeout):
    # Wait for the field to be present/visible before filling, so we don't act
    # before the element has rendered.
    page.wait_for_selector(selector, timeout=timeout, state="visible")
    page.fill(selector, value, timeout=timeout)
    settle(page)


def safe_click(page, selector, timeout):
    try:
        page.click(selector, timeout=timeout)
    except Exception:
        dismiss_overlays(page)
        try:
            page.click(selector, timeout=timeout)
        except Exception:
            page.click(selector, timeout=timeout, force=True)
    settle(page)


def safe_select(page, selector, value, timeout):
    page.wait_for_selector(selector, timeout=timeout, state="visible")
    page.select_option(selector, value, timeout=timeout)
    settle(page)


def safe_hover(page, selector, timeout):
    page.wait_for_selector(selector, timeout=timeout, state="visible")
    page.hover(selector, timeout=timeout)
    settle(page)


def safe_press(page, selector, key, timeout):
    # Focus the field, then send the key via the keyboard. This avoids the
    # element-stability wait that can time out on inputs with live typeahead.
    try:
        page.focus(selector, timeout=timeout)
    except Exception:
        page.wait_for_selector(selector, timeout=timeout)
    page.keyboard.press(key)
    settle(page)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--screenshot')
    parser.add_argument('--snapshot')
    args = parser.parse_args()

    current_step = None
    current_selector = None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        # A realistic context reduces bot-detection interstitials (captchas /
        # "Continue shopping" pages) that hide the real DOM in headless mode.
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        # Mask the most common automation tell (navigator.webdriver === true).
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        try:
            # STEP 1: Navigate to https://www.flipkart.com/
            current_step = 1
            current_selector = None
            navigate(page, "https://www.flipkart.com/", 30000)

            # STEP 2: Close the login dialog box if it is open.
            current_step = 2
            current_selector = "span:has-text('\u2715')"
            safe_click(page, "span:has-text('\u2715')", 5000)

            # STEP 3: Type 'laptop' into the search bar.
            current_step = 3
            current_selector = "input[name='q']"
            safe_fill(page, "input[name='q']", "laptop", 5000)

            # STEP 4: Click the search button to submit the search for 'laptop'.
            current_step = 4
            current_selector = "button[aria-label='Search for Products, Brands and More']"
            safe_click(page, "button[aria-label='Search for Products, Brands and More']", 5000)

            # STEP 5: Filter the search results to show only laptops with Core i5 processors.
            current_step = 5
            current_selector = "label:has-text('Core i5')"
            safe_click(page, "label:has-text('Core i5')", 5000)

            # On success, capture artifacts and exit cleanly.
            if args.screenshot:
                page.screenshot(path=args.screenshot, full_page=True)
            if args.snapshot:
                with open(args.snapshot, 'w', encoding='utf-8') as f:
                    f.write(page.content())
            browser.close()
            sys.exit(0)
        except Exception as e:
            err_type = 'timeout' if isinstance(e, PlaywrightTimeoutError) else type(e).__name__
            try:
                if args.screenshot:
                    page.screenshot(path=args.screenshot, full_page=True)
                if args.snapshot:
                    with open(args.snapshot, 'w', encoding='utf-8') as f:
                        f.write(page.content())
            except Exception:
                pass
            report = {
                "type": err_type,
                "message": str(e),
                "step_id": current_step,
                "selector": current_selector,
            }
            print("ERROR_REPORT: " + json.dumps(report))
            browser.close()
            sys.exit(1)


if __name__ == "__main__":
    main()
