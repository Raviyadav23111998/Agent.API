"""
Copilot surface — prompt sections.

The web/embed copilot drives the user's screen with the page_* tools. Its
prompt content (the navigation playbook + the app's route map) lives HERE, in
the api surface layer — NOT in the core engine. The core `PromptBuilder` is
feature-agnostic; a CLI agent or a Telegram bot has no "page navigation". The
copilot session builder injects these via `prompt_builder.set_section(...)`.

Section keys/orders (see core.prompt_sections for the shared convention):
    copilot_routes    order 10  (the static app route map, from the client)
    copilot_playbook  order 20  (how to drive the page)
"""
from typing import Iterable

ROUTES_KEY = "copilot_routes"
ROUTES_ORDER = 10
PLAYBOOK_KEY = "copilot_playbook"
PLAYBOOK_ORDER = 20

_MAX_ROUTES = 80   # defensive cap so a pathological page can't bloat the prefix


# How to drive the page. Injected whenever a session has the page_* tools.
PAGE_NAV_PLAYBOOK = (
    "<page_navigation>\n"
    "You can see and drive the user's CURRENT screen with the page_* tools. "
    "When the user asks you to reach a screen or perform an on-screen task, "
    "follow this contract EXACTLY:\n"
    "1. If the target route is listed in <app_routes>, call "
    "page_navigate(route) with it DIRECTLY — do not explore the sidebar to "
    "rediscover a route you already have.\n"
    "2. Otherwise, call page_observe FIRST to see the real elements (nav "
    "links, buttons, fields) by their on-screen LABEL, then reach the section "
    "by CLICKING the matching menu/sidebar link with page_act (it may be "
    "nested under a group — expand it first). Do NOT invent route paths that "
    "aren't in <app_routes>; if you'd be guessing, observe and click instead.\n"
    "3. Do not confuse a dashboard CARD, CHART, or stat tile that merely "
    "mentions a word (e.g. a 'Drivers' count widget) with the NAV LINK that "
    "opens that section. Prefer sidebar/menu links.\n"
    "4. After any click or navigation, the screen changes — call page_observe "
    "AGAIN before the next action. Element labels from before are stale.\n"
    "5. If a click lands on the wrong screen, do not keep retrying the same "
    "thing. Re-observe, and pick a different nav link.\n"
    "6. To fill a form, observe it, then use ONE page_act with all the steps "
    "(fill each field by label, then click the submit/save button).\n"
    "7. If after observing you genuinely cannot find a way to the target, say "
    "so and ask the user — never loop blindly.\n"
    "8. NEVER type a password or other credential on the user's behalf. If a "
    "login/password field is in the way, ask the user to enter it themselves, "
    "then continue.\n"
    "</page_navigation>"
)


def render_routes(nav: Iterable[dict]) -> str:
    """Render the host app's STATIC navigation map (from the client) into an
    <app_routes> block. Sorted → byte-stable → cached in the prefix. Lets the
    copilot call page_navigate(route) directly instead of discovering routes by
    observing and clicking. Empty/malformed → '' (no block)."""
    items = set()
    for n in (nav or []):
        if not isinstance(n, dict):
            continue
        label = (n.get("label") or "").strip()
        route = (n.get("route") or "").strip()
        if not label or not route:
            continue
        group = (n.get("group") or "").strip()
        items.add((group, label, route))
    if not items:
        return ""
    # Cap defensively — a pathological page must never bloat the cached prefix.
    # Deterministic (sorted) so the truncation itself stays byte-stable.
    lines = []
    for group, label, route in sorted(items)[:_MAX_ROUTES]:
        prefix = f"{group} > " if group else ""
        lines.append(f"  {prefix}{label} → {route}")
    return ("<app_routes>\n"
            "This app's known routes (static for this session). To reach a "
            "listed screen, call page_navigate(route) with its route directly — "
            "no need to observe/click the sidebar. page_observe only when the "
            "target isn't listed here.\n"
            + "\n".join(lines) + "\n</app_routes>")
