import json
import textwrap
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from core.schema import FlowSchema
from core.llm import get_llm

SYSTEM_PROMPT = """
You are the Script Generator Agent. Given a FlowSchema, output ONLY the Python statements
that perform the steps. These statements are inserted into an existing function where the
following names are ALREADY defined and in scope:

  - `page`     : a Playwright sync Page (browser/context already created)
  - `navigate(page, url, timeout_ms)` : goto + wait for the page to finish loading
  - `safe_click(page, selector, timeout_ms)` : overlay-resistant click helper
  - `safe_fill(page, selector, value, timeout_ms)` : waits for the field, then fills
  - `safe_select(page, selector, value, timeout_ms)` : waits for the field, then selects
  - `safe_hover(page, selector, timeout_ms)` : waits for the element, then hovers
  - `safe_press(page, selector, key, timeout_ms)` : focuses the field, then presses a key (e.g. "Enter")
  - `dismiss_overlays(page)` : best-effort dismissal of cookie/consent/popover overlays

Every action helper above already pauses briefly after acting so the next element can render.

Do NOT write imports, function definitions, `with sync_playwright()`, browser/context/page
creation, try/except, artifact capture, or `sys.exit`. ONLY emit the step statements.

For EACH step, in order, emit exactly:
  1. A comment line: `# STEP {step_id}: {description}`
  2. `current_step = {step_id}`
  3. `current_selector = "{selector}"`  (use `None` if the step has no selector)
  4. The action call, always passing the step's timeout in milliseconds:
       - navigate: navigate(page, "{value}", {timeout_ms})   # waits for the page to load; NEVER use page.goto directly
       - click:    safe_click(page, "{selector}", {timeout_ms})   # NEVER page.click directly
       - fill:     safe_fill(page, "{selector}", "{value}", {timeout_ms})   # waits for the field; NEVER page.fill directly
       - select:   safe_select(page, "{selector}", "{value}", {timeout_ms})   # NEVER page.select_option directly
       - hover:    safe_hover(page, "{selector}", {timeout_ms})   # NEVER page.hover directly
       - press:    safe_press(page, "{selector}", "{value}", {timeout_ms})   # value is the key, e.g. "Enter"; NEVER page.press directly
       - assert:   if a selector is given, use
                   `page.wait_for_selector("{selector}", timeout={timeout_ms})` to assert the
                   element is present (raises on failure). If `value` expresses a URL/text
                   expectation, ALSO verify it and `raise AssertionError(...)` on mismatch.
                   `page.url` is a PROPERTY — use `page.url`, never `page.url()`.
                   NEVER pass `timeout=` to `query_selector`.

Rules:
- All statements must start at column 0 (no leading indentation); they will be indented for you.
- Use exactly the selectors/values from the FlowSchema; do not invent new ones.
- Output ONLY the statements. No markdown fences, no prose, no surrounding function.
"""

HARNESS_TEMPLATE = '''import argparse
import json
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


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
    page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    for state in ("load", "networkidle"):
        try:
            page.wait_for_load_state(state, timeout=timeout)
        except Exception:
            pass
    settle(page)


def safe_fill(page, selector, value, timeout):
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
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        try:
__STEPS_PLACEHOLDER__

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
'''

STEP_INDENT = " " * 12

_GENERATE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", (
        "Generate the step statements for the following flow:\n\n"
        "Flow ID: {flow_id}\n"
        "Flow Name: {flow_name}\n"
        "Flow Steps:\n{steps}"
    )),
])


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```python"):
        text = text[9:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def assemble_script(step_body: str) -> str:
    """Wrap the LLM-produced step statements in the fixed harness with correct indentation."""
    body = textwrap.dedent(step_body).strip("\n")
    indented = "\n".join(
        (STEP_INDENT + line) if line.strip() else ""
        for line in body.splitlines()
    )
    script = HARNESS_TEMPLATE.replace("__STEPS_PLACEHOLDER__", indented)
    try:
        compile(script, "<generated_script>", "exec")
    except SyntaxError as e:
        raise ValueError(f"Generated script has a syntax error at line {e.lineno}: {e.msg}") from e
    return script


def generate_script(
    flow: FlowSchema,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Generate a Playwright script for the given flow using a LangChain chain."""
    llm = get_llm(api_key, provider, base_url, model)
    chain = _GENERATE_PROMPT | llm | StrOutputParser()

    step_body = chain.invoke({
        "flow_id": flow.flow_id,
        "flow_name": flow.flow_name,
        "steps": json.dumps([step.dict() for step in flow.steps], indent=2),
    })

    step_body = _strip_fences(step_body)
    return assemble_script(step_body)
