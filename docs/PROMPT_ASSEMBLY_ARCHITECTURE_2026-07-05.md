# Prompt Assembly — Decoupled Architecture (2026-07-05)

## Why (the current state, grounded in code)

`PromptBuilder` (core engine) has become a pile of **feature-specific** blocks, and
the engine reaches into **surface-specific** concerns:

- `build_system_prompt` enumerates features by name — each with a bespoke field +
  render clause: `_skills_index`, `_memory_context`, `knowledge_items`,
  `_use_fallback_tools`, and `_page_nav_enabled` + a hardcoded `_PAGE_NAV_PLAYBOOK`.
- **`agent_loop.py:1262-1264` sniffs copilot tool names** (`page_observe`/
  `page_navigate`) and toggles the copilot playbook — the *core* engine coupled to a
  *web-copilot UI* concern.
- `_PAGE_NAV_PLAYBOOK` — copilot prompt text lives **inside the core engine**.
- Two injection channels exist: `PromptBuilder` blocks (static, cached) **and**
  `ws.py:233` appends VSCode context to the *user message* (dynamic).
- `set_memory_context` has **no callers** (dead).

A CLI agent or a Telegram bot has no "page navigation" — yet the core engine hardcodes
it. Adding the new copilot nav-map as another bespoke field continues this drift. This
doc defines the clean model and the migration.

## The clean model — three layers

**L1 — Engine core (PromptBuilder owns, unchanged):** identity, doctrine, constraints,
communication, environment, effort sections, fallback-tools. The engine's operating
instructions; identity/constraints/communication are persona-overridable via `custom_*`.

**L2 — Generic section registry (the new seam):**
```python
class PromptBuilder:
    def set_section(self, key: str, text: str, order: int = 100) -> None:
        """Register a named, byte-stable prompt section. Rendered in the dynamic
        zone, ordered by (order, key) for determinism (cache-stable). Empty text
        removes it. The engine never learns what a section *is* — the contributor
        owns the fully-rendered text."""
```
`build_system_prompt` replaces the per-feature `if self._x:` clauses with **one loop**:
```python
for s in sorted(self._sections.values(), key=lambda s: (s.order, s.key)):
    parts.append(s.text)
```

**L3 — Contributors (host/surface layers own their text):** each feature renders its own
block and registers it. The engine no longer enumerates them.

| Section | order | Owner (contributor) |
|---|---|---|
| `copilot_routes` (NEW nav map) | 10 | copilot surface (api) |
| `copilot_playbook` (moved out of engine) | 20 | copilot surface (api) |
| `skills_index` | 30 | skills contributor |
| `memory` | 40 | (delete — dead) or memory contributor |
| `knowledge` | 50 | KI contributor |

## Correcting the current coupling

1. **Move the copilot playbook OUT of the engine.** Delete `_PAGE_NAV_PLAYBOOK`,
   `_page_nav_enabled`, `set_page_navigation` from `PromptBuilder`. Delete the
   tool-name sniff at `agent_loop.py:1262-1264`. The playbook text moves to a copilot
   prompt module in the api layer (`api/services/copilot_prompt.py`): `PAGE_NAV_PLAYBOOK`
   + `render_routes(nav) -> str`.
2. **The copilot surface injects both sections.** The place that builds a copilot session
   (it wired `RemoteToolExecutor` + page tools: `ws.py`, `embed_ws.py`, and the in-app
   Angular path via `chat_service`) calls
   `prompt_builder.set_section("copilot_playbook", PAGE_NAV_PLAYBOOK, 20)` and, when the
   client sent a nav map, `set_section("copilot_routes", render_routes(nav), 10)`.
   Trigger = "this surface uses page tools" (known at the surface), not tool-name
   sniffing in the engine.
3. **Migrate the engine-capability blocks to the seam** (consistency): skills_index,
   knowledge, (memory if kept) become `set_section(...)` calls. Rendering moves to thin
   helpers next to their contributors (`set_skills_index(rows)` → a `render_skills_index`
   helper → `set_section("skills_index", ...)`). Delete dead `set_memory_context`.
4. **Byte-stability preserved:** ordered by (order, key); each contributor produces
   stable text (sorted inputs). Same cache-first guarantee as today.

## Blast radius / callers to update
- `PromptBuilder`: add `set_section` + registry + loop; remove page-nav + (migrated) blocks.
- `agent_loop.py:1262-1264`: remove the copilot sniff.
- Contributors: `factory.py:585` (skills), `chat_service.py:287` (KI) + skills index call,
  `cli.py:1044` (KI), `runner.py:351` (KI) → `set_section`.
- New `api/services/copilot_prompt.py` (playbook text + route renderer).
- Copilot surfaces (`ws.py`, `embed_ws.py`, chat_service copilot path) inject the two
  copilot sections + read `context.nav`.
- Tests: `test_skills_learning_core.py` uses `set_skills_index` → update to the new path.

## Scope decision (needs your steer)
Two honest scopes:
- **Minimal-correct:** add the seam; move ONLY the copilot playbook out of the engine +
  add the nav map on it (fixes the clearest smell — surface concern in core). Leave
  skills/memory/knowledge as engine-intrinsic bespoke blocks for now. Low regression.
- **Full decouple:** also migrate skills/memory/knowledge onto the seam so the engine has
  ZERO bespoke feature blocks — just core doctrine + the generic registry. Cleanest, but
  touches the tested/live skills path.

## Verification
- Engine unit: `set_section` renders byte-stable, order-deterministic; empty removes;
  `build_system_prompt` output equals today's for the same content (golden compare).
- Skills: `test_skills_learning_core` green after migration (or its equivalent).
- Copilot e2e: playbook + `<app_routes>` appear only for copilot surfaces; a nav task
  resolves in 1 `page_navigate` turn.
- Regression: chat/CLI/bot prompts unchanged (no copilot sections leak into non-copilot
  surfaces — the engine no longer injects them at all).
