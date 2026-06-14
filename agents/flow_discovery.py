import uuid
import json
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from core.schema import FlowSchema, FlowStep
from core.llm import get_llm

MAX_STEPS = 14
MAX_RETRIES = 3

DECIDE_SYSTEM_PROMPT = """
You are the Flow Discovery Agent driving a real web browser to accomplish a user's goal.
You work ONE step at a time. Each turn you are given: the goal, the current page URL/title,
the steps already completed, and a list of REAL elements currently on the page (with their
attributes and visible text). Decide the single NEXT action, OR declare the goal complete.

Respond with ONE raw JSON object (no markdown):
{
  "flow_name": "<short name for the overall flow>",
  "done": false,
  "action": "click | fill | select | hover | press | navigate | assert",
  "selector": "<Playwright selector for a REAL current element, or null for navigate>",
  "selector_strategy": "css | text | testid | role",
  "value": "<text to type / option to select / key to press / URL to navigate / assertion text, else null>",
  "description": "<short human description of this step>",
  "timeout_ms": 5000,
  "reason": "<why this is the right next action toward the goal>"
}
Set "done": true (and omit the action fields) when the goal is already accomplished by the
completed steps.

HOW TO CHOOSE THE SELECTOR (critical):
The user's words DESCRIBE what to interact with — they are NOT a selector. Pick the matching
element from the CURRENT elements list and use THAT element's provided `selector` field
verbatim. Every element already includes a ready-to-use, validated `selector` — do not invent
or modify it. Match the user's intent to the element by its `text`/`aria_label`/`href`.

When several similar elements match (e.g. many search-result links), choose the one whose
text/href best matches the goal's intended target (prefer the official site or the most
directly relevant result), not the first one you see.

NEVER:
  - invent an id or selector that is not present in an element's `selector` field;
  - turn human words or an href fragment (e.g. "#Holding_companies") into a CSS id;
  - choose an element that is not in the current list.

SEQUENCING (applies to EVERY kind of flow — login, signup, search, checkout, menus, forms):
You may only act on elements that exist on the CURRENT page right now. Reach the goal ONE
real page/state at a time. Do NOT skip ahead to an element that is not in the current list;
if your target is not present yet, first do the action that reveals or navigates to it.
General patterns (use whichever fits the goal — do not assume it is a search):
- FORMS (login/signup/contact/checkout): fill each required field in order, then click the
  submit/continue/login button. Fill before submitting.
- SEARCH: type into the search field, then SUBMIT — prefer clicking the search/submit button
  if one exists (some sites, e.g. Wikipedia, do NOT submit on Enter); otherwise `press` Enter
  on the field. After results load, click the result that best matches the goal.
- MENUS / DROPDOWNS / ACCORDIONS: the sub-item may be hidden until you `hover` or `click` the
  parent menu/toggle. Do that first; the child appears in the next element list, then click it.
- LISTS / PAGINATION / "load more": click the expander/next control to reveal more items, then
  act on the newly revealed element.
- VERIFICATION: when the goal asks to confirm/check something, use an `assert` step on an
  element that proves success.
Only act on an element once it actually appears in the current elements list.
For `navigate`, selector is null and value is the URL (absolute, or a path relative to the
current page).
"""

_EXTRACT_JS = """
() => {
    const q = (s) => "'" + String(s).replace(/'/g, "\\\\'") + "'";
    const buildSelector = (node, tag) => {
        const id = node.getAttribute('id');
        if (id) { try { return '#' + CSS.escape(id); } catch (e) { return '#' + id; } }
        const testid = node.getAttribute('data-testid');
        if (testid) return '[data-testid=' + q(testid) + ']';
        const name = node.getAttribute('name');
        if (name) return tag + '[name=' + q(name) + ']';
        const aria = node.getAttribute('aria-label');
        if (aria) return tag + '[aria-label=' + q(aria) + ']';
        const ph = node.getAttribute('placeholder');
        if (ph) return tag + '[placeholder=' + q(ph) + ']';
        const isField = (tag === 'input' || tag === 'select' || tag === 'textarea');
        if (!isField) {
            const txt = (node.innerText || '').trim();
            if (txt) return tag + ':has-text(' + q(txt.substring(0, 60)) + ')';
        }
        const same = document.querySelectorAll(tag);
        const idx = Array.prototype.indexOf.call(same, node);
        if (idx >= 0) return ':nth-match(' + tag + ', ' + (idx + 1) + ')';
        return tag;
    };

    const out = [];
    const selectors = [
        'a', 'button', 'input', 'select', 'textarea', 'label', 'summary',
        '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
        '[role="checkbox"]', '[role="radio"]', '[role="switch"]', '[role="combobox"]',
        '[role="option"]', '[role="menuitemcheckbox"]', '[role="menuitemradio"]',
        '[role="treeitem"]', '[contenteditable="true"]', '[onclick]',
        '[tabindex]:not([tabindex="-1"])'
    ].join(', ');
    const nodes = document.querySelectorAll(selectors);
    nodes.forEach((node) => {
        const style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        const rect = node.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;

        const tag = node.tagName.toLowerCase();
        const text = (node.innerText || node.value || node.getAttribute('aria-label') || '').trim().substring(0, 80);
        const item = {
            tag: tag,
            id: node.getAttribute('id') || '',
            name: node.getAttribute('name') || '',
            type: node.getAttribute('type') || '',
            placeholder: node.getAttribute('placeholder') || '',
            aria_label: node.getAttribute('aria-label') || '',
            role: node.getAttribute('role') || '',
            testid: node.getAttribute('data-testid') || '',
            href: node.getAttribute('href') || '',
            text: text,
            selector: buildSelector(node, tag)
        };
        if (!item.text && !item.id && !item.name && !item.testid && !item.aria_label && !item.placeholder) return;
        out.push(item);
    });
    return out.slice(0, 400);
}
"""

OVERLAY_DISMISS_SELECTORS = [
    "#sp-cc-accept", "input#sp-cc-accept", "[data-action='a-popover-floating-close']",
    "button#onetrust-accept-btn-handler", "#onetrust-accept-btn-handler",
    "[aria-label='Close']", "[aria-label='close']", "button[title='Close']",
]

# LangChain prompt template for the discovery decision
_DECIDE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", DECIDE_SYSTEM_PROMPT),
    ("human", (
        "Goal: {goal}\n\n"
        "Current page URL: {url}\n"
        "Current page title: {title}\n\n"
        "Steps completed so far ({n_steps}):\n{completed}\n\n"
        "Elements currently on this page:\n{elements}\n"
        "{feedback_line}\n\n"
        "Decide the single next action (or set done=true if the goal is complete)."
    )),
])


def _extract_from_page(page) -> List[dict]:
    try:
        elements = page.evaluate(_EXTRACT_JS)
    except Exception as e:
        print(f"Error extracting DOM elements: {e}")
        return []
    return [{k: v for k, v in el.items() if v} for el in elements]


def _settle(page, timeout: int = 8000):
    for state in ("load", "networkidle"):
        try:
            page.wait_for_load_state(state, timeout=timeout)
        except Exception:
            pass
    try:
        page.wait_for_timeout(500)
    except Exception:
        pass


def _dismiss_overlays(page):
    for sel in OVERLAY_DISMISS_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(timeout=1000)
        except Exception:
            pass


def _selector_resolves(page, selector: str) -> bool:
    if not selector:
        return False
    try:
        return page.locator(selector).count() > 0
    except Exception:
        return False


def _execute(page, action: str, selector: Optional[str], value: Optional[str], timeout: int):
    if action == "navigate":
        page.goto(value, wait_until="domcontentloaded", timeout=max(timeout, 30000))
        _settle(page)
        return
    if action == "assert":
        return

    loc = page.locator(selector).first
    try:
        loc.scroll_into_view_if_needed(timeout=timeout)
    except Exception:
        pass

    if action == "click":
        try:
            loc.click(timeout=timeout)
        except Exception:
            _dismiss_overlays(page)
            loc.click(timeout=timeout, force=True)
    elif action == "fill":
        loc.fill(value or "", timeout=timeout)
    elif action == "select":
        loc.select_option(value, timeout=timeout)
    elif action == "hover":
        loc.hover(timeout=timeout)
    elif action == "press":
        try:
            page.focus(selector, timeout=timeout)
        except Exception:
            pass
        page.keyboard.press(value or "Enter")
    _settle(page)


def _parse_decision(text: str) -> dict:
    t = text.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1:
            t = t[start:end + 1]
    return json.loads(t)


def _decide_next(goal, page, completed, feedback, api_key, provider, base_url, model) -> dict:
    """Use a LangChain chain to decide the next browser action."""
    elements = _extract_from_page(page)

    llm = get_llm(api_key, provider, base_url, model)
    chain = _DECIDE_PROMPT | llm | StrOutputParser()

    response = chain.invoke({
        "goal": goal,
        "url": page.url,
        "title": page.title(),
        "n_steps": len(completed),
        "completed": json.dumps(completed, indent=2) if completed else "(none yet)",
        "elements": json.dumps(elements, indent=2),
        "feedback_line": f"IMPORTANT FEEDBACK: {feedback}" if feedback else "",
    })

    return _parse_decision(response)


def discover_flow(
    url: str,
    goal: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> FlowSchema:
    steps: List[FlowStep] = []
    completed_summaries: List[dict] = []
    flow_name = "Discovered Flow"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            _settle(page)
            steps.append(FlowStep(
                step_id=1, action="navigate", selector=None, selector_strategy=None,
                value=url, description=f"Navigate to {url}", timeout_ms=30000,
            ))
            completed_summaries.append({"action": "navigate", "value": url, "description": f"Navigate to {url}"})

            feedback = None
            fails = 0
            iterations = 0
            max_iterations = MAX_STEPS * 2
            while len(steps) < MAX_STEPS and iterations < max_iterations:
                iterations += 1
                try:
                    decision = _decide_next(goal, page, completed_summaries, feedback,
                                            api_key, provider, base_url, model)
                except Exception as e:
                    print(f"Discovery: decision call failed ({e}); stopping.")
                    break
                feedback = None
                flow_name = decision.get("flow_name") or flow_name
                if decision.get("done"):
                    break

                action = (decision.get("action") or "").strip()
                selector = decision.get("selector")
                value = decision.get("value")
                timeout = int(decision.get("timeout_ms") or 5000)
                strategy = decision.get("selector_strategy") or ("css" if selector else None)
                description = decision.get("description") or f"{action} {selector or value or ''}".strip()

                if action == "navigate" and value and not value.startswith(("http://", "https://")):
                    value = urljoin(page.url, value)

                print(f"Discovery decision @ {page.url} -> action={action!r} selector={selector!r} value={value!r} :: {description}")

                needs_selector = action not in ("navigate", "assert")
                if needs_selector and not _selector_resolves(page, selector):
                    fails += 1
                    feedback = (
                        f"The selector {selector!r} for '{description}' matched NO element on the "
                        f"CURRENT page ({page.url}). It is probably not reachable yet — first do the "
                        f"action that reveals or navigates to it (fill+submit a form, click/hover a menu "
                        f"or toggle to expand it, click a 'next'/'load more' control, or navigate). Then "
                        f"pick an element that actually appears in the current list, using its exact "
                        f"`selector` field."
                    )
                    if fails > MAX_RETRIES:
                        print("Discovery: too many consecutive failures resolving selectors; stopping.")
                        break
                    continue

                try:
                    _execute(page, action, selector, value, timeout)
                except Exception as e:
                    fails += 1
                    feedback = f"Executing '{description}' failed: {e}. Try a different element or approach."
                    if fails > MAX_RETRIES:
                        print("Discovery: too many consecutive failures executing steps; stopping.")
                        break
                    continue

                steps.append(FlowStep(
                    step_id=len(steps) + 1,
                    action=action,
                    selector=selector,
                    selector_strategy=strategy,
                    value=value,
                    description=description,
                    timeout_ms=timeout,
                ))
                completed_summaries.append({
                    "action": action, "selector": selector, "value": value, "description": description,
                })
                fails = 0
        finally:
            browser.close()

    return FlowSchema(
        flow_id=str(uuid.uuid4()),
        flow_name=flow_name,
        url=url,
        steps=steps,
        created_at=datetime.utcnow().isoformat() + "Z",
        target_framework="playwright",
    )
