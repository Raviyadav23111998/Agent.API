# Persona Topic-Scoping — Root Cause + Guardrail Architecture (how Hermes & the big systems do it, and how we should)

**Date:** 2026-07-05
**Trigger:** Fleet Support copilot (bot + embedded app, `agent_personas.persona_id = 2`) answered an off-domain request — it wrote a `random_numbers.py` script and explained how to run it — then reverted to "would you like to get back to adding a staff member?". A Fleet Management copilot should not be a general-purpose coding assistant.
**Companion docs:** `PERSONA_CRON_ARCHITECTURE_AUDIT_AND_PLAN_2026-07-05.md` (persona governance seam), the guardrail engine in `agent.core/core/guardrails.py`.

**STATUS: FIXED (structural, not a patch).** A first-class **input scope rail** was added as the missing fourth guardrail layer — a pre-generation topic gate on `GuardrailEngine`, wired at the single pre-generation seam in `AgentLoop`, driven by a per-persona `scope_policy` column. This is the architectural layer §4's mature systems all have; the "populate the prompt paragraph" mitigation was explicitly rejected as a patch. See §5 (Implemented) for the shipped design.

---

## 1. Root cause (definitive, code-traced)

**Our persona system has no topic/scope enforcement of any kind. Topic scope exists only as free-text in the prompt, and for Fleet that text was never written.**

Traced end to end:

1. **The guardrail engine is a *data-security* engine, not a *topic* engine.** `core/guardrails.py` docstring and `GuardrailEngine.evaluate()` are explicit: the three layers are
   - **Input** = a free-text `input_guardrail_prompt` appended to the system prompt (prose, not a gate),
   - **Execution** = IAM-style allow/deny on tool *name + arguments* (`execution_policies`) + embed page-action danger patterns,
   - **Output** = regex DLP + optional semantic LLM redaction of *leaked data*.

   `evaluate()` — the single pre-execution seam — only runs `execution_policy` and `embed_action_policy`. **There is no layer that looks at what the user asked and decides "that's out of scope."** Grep for any topic/scope/off-topic/decline gate in `agent.core/core` + `agent.api/api` returns nothing.

2. **Topic scope, if it exists at all, is prompt text — and it's assembled here:** `agent_loop.py:1254-1273`
   ```python
   constraints_override = self._prompt_overrides.get("constraints") or ""      # persona.constraints_prompt
   if self.guardrail_engine and self.guardrail_engine.has_input_guardrail:     # persona.input_guardrail_prompt
       guardrail_block = self.guardrail_engine.get_input_guardrail_prompt()
       constraints_override = f"{constraints_override}\n\n[SECURITY BOUNDARY — NON-NEGOTIABLE]\n{guardrail_block}"
   system_prompt = self.prompt_builder.build_system_prompt(
       ..., custom_constraints=constraints_override or None, ...)
   ```
   So the *only* two places a topic boundary could live are the persona's `constraints_prompt` and `input_guardrail_prompt` columns — **both are prose injected into the system prompt, both are soft, and both are optional.**

3. **The Fleet persona populates neither.** `migrations/fix_fleet_persona.sql` sets `identity_prompt` for `persona_id = 2` and nothing else. That identity text *enables* general capability ("**Answer questions**: use brain_ask… be proactive… you are a copilot that drives the page") and never says "refuse anything that isn't Fleet Management." `constraints_prompt` / `input_guardrail_prompt` for that row are (as far as the migration history shows) empty. ⚠️ **Verify with a live query before acting:**
   ```sql
   SELECT persona_id, name,
          length(coalesce(constraints_prompt,''))      AS constraints_len,
          length(coalesce(input_guardrail_prompt,''))  AS input_guard_len,
          length(coalesce(output_semantic_rules,''))   AS out_sem_len
   FROM ag_system.agent_personas WHERE persona_id = 2;
   ```

4. **Why the model happily wrote code:** the tool whitelist (`page_*` + `brain_*`) correctly stops it from *doing* off-domain *actions*, but **writing a Python snippet is plain text generation — it calls no tool**, so no layer touches it. Underneath the persona costume the model is still a general-purpose LLM; with nothing telling it a coding question is out of scope, it answers, then its own context-tracking pulls it back to the pending "add staff" task.

**One line:** *scope enforcement was never a feature — it was an unwritten paragraph, and Fleet's paragraph is blank.*

---

## 2. What this is NOT

- **Not a whitelist bug.** `allowed_tools` did its job; the leak is on the pure-text channel it doesn't cover.
- **Not a prompt-injection / jailbreak.** No adversary; an ordinary user asked an ordinary off-topic question and the bot obliged. (A jailbreak is a *harder* version of the same missing control.)
- **Not high-severity security.** The copilot can't *act* off-domain (no shell/code-exec tool). The damage is brand/trust ("our Fleet bot moonlights as a coding tutor") and wasted tokens — real, but not a breach. Calibrate the fix to that.

---

## 3. How Hermes does it (answer: it deliberately doesn't topic-scope)

Hermes' entire security surface (`tools/tirith_security.py`, `threat_patterns.py`, `url_safety.py`, `website_policy.py`, `gateway/response_filters.py`, `plugins/security-guidance/`) is **content-threat** defense:
- **prompt-injection / promptware / exfiltration** pattern scanning on context, memory, tool results (`threat_patterns.py`, organized by *attack class*);
- **pre-exec command scanning** for homograph URLs, pipe-to-interpreter, terminal injection (`tirith` binary, exit-code verdict);
- **SSRF / URL / website** blocklists;
- output *silence* markers, not topic filtering.

Hermes is a **personal, run-anywhere, do-anything agent** — topic-restricting it would defeat its purpose, so it has **no topical rail at all**. Its `threat_patterns.py` even documents *not* flagging "bossy English" ("you must", "you are obligated to") because that's normal instruction-writing. **Takeaway: Hermes is the wrong model to copy for an enterprise single-purpose copilot.** It solves "don't get hijacked / don't get exfiltrated," not "stay on your job." Our Fleet need is the opposite problem, and neither we nor Hermes has a built gate for it.

---

## 4. How the large systems do topic/scope guardrails

Mature deployments treat this as **defense-in-depth with a hard gate**, never prompt-only. The reference implementations:

| System | Mechanism | Layer | Nature |
|---|---|---|---|
| **NVIDIA NeMo Guardrails — "topical rails"** | Embeds the user turn, matches it to allowed *canonical intents* (Colang flows); off-topic → a `bot refuse off topic` flow fires and the main LLM is **never called**. | **Input** (pre-generation) | Embedding intent-match + dialog manager |
| **Meta Llama Guard 3** | A fine-tuned classifier LLM scores input *and* output against a category taxonomy (extensible with **custom categories**); unsafe → block/canned reply. | Input + Output | Separate classifier model |
| **Anthropic Constitutional Classifiers** | Purpose-trained input/output classifiers (a "constitution" of allowed/disallowed), robust to jailbreaks, running alongside the main model. | Input + Output | Separate classifier model |
| **OpenAI Moderation + system prompt** | Free moderation classifier on input/output, plus system-prompt scoping. GPTs/Assistants lean on the *prompt* for topic — which is exactly why they're jailbreakable (this is the weak tier we're currently in). | Input + Output + prompt | Classifier + prompt |
| **Guardrails AI / "LLM-as-judge"** | RAIL validators or a cheap fast model that classifies in-scope / out-of-scope before or in parallel with the main answer. | Input/Output | Validator or judge model |
| **RAG grounding constraint** | "Answer *only* from retrieved documents; if the KB has nothing, say you can't help." Off-topic questions retrieve nothing → natural refusal. | Retrieval | Grounding |

The **consensus stack**, weakest → strongest:
0. **System-prompt scoping** — necessary, never sufficient, jailbreakable. *(all we have today, and unpopulated for Fleet)*
1. **Input rail / classifier** — the hard gate: decide in/out of scope *before* generating; off-topic → canned refusal, main model never runs. *(we have nothing)*
2. **Tool authorization** — which tools may fire. *(we have this — `allowed_tools` + `execution_policies` — and it's good)*
3. **Output rail** — check the finished answer before delivery (DLP + topic/safety judge). *(we have DLP + a semantic LLM pass — the seam exists)*
4. **Grounding** — constrain answers to the knowledge base. *(we have `brain` RAG — usable as a scope signal)*

The industry lesson in one sentence: **prompt scoping stops the polite user, a classifier stops the curious/adversarial one, and you want both.**

---

## 5. What was built (IMPLEMENTED — the structural fix)

We did **not** ship the "write a scope paragraph" mitigation — that changes the suggestion, not the architecture, and the next persona would be equally exposed. We added the **missing layer**: a first-class **INPUT SCOPE RAIL** — a pre-generation topic gate that runs *before* the main model and short-circuits out-of-domain turns. This is the layer NeMo topical-rails / Llama Guard represent (§4); it is structural, not prose.

Our guardrail architecture now has four rails, all owned by `GuardrailEngine`:
`INPUT SCOPE (new)` → `INPUT SECURITY PROMPT` → `EXECUTION (tool IAM)` → `OUTPUT (DLP)`.

### The design

- **Config (`scope_policy` JSONB on `ag_system.agent_personas`, migration `V038`):**
  ```json
  { "mode": "off|restrict", "domain": "<one-line domain>",
    "refusal_message": "<what the user sees>", "fail_open": true }
  ```
  Default `{}` = rail off. A first-class column, symmetric with `execution_policies` / `output_dlp_patterns` (and, like them, DB/migration-configured today — see follow-ups).

- **Engine (`GuardrailEngine`, `agent.core/core/guardrails.py`):** parses `scope_policy`, exposes `has_input_scope`, and adds `async evaluate_input(user_input, recent_context) -> (allowed, refusal)`. Mechanism: **one LLM-judge classification** using the *same injected client + call pattern as the proven semantic output filter* (the one existing "LLM-as-guardrail" call in the codebase — so no new dependency, no divergent request params). The user request is DATA to the classifier, not instructions — the reason this holds where prose scoping does not. Recent conversation is passed so a legitimate continuation ("yes", "the red truck") isn't misread as off-topic. Verdict parse is whole-word regex with **OUT-precedence** (ambiguity leans toward blocking). **Fail-open by default** (scope is a brand control, not a security wall) with warning logs + telemetry (`agent_scope_classifier_errors_total` / `_unparsed_total`) so a rail that silently fails open is observable.

- **Loop (`AgentLoop._process_input_inner`):** the rail runs at the single pre-generation seam — after the user message is recorded, before any prompt build or generation. On block: append the canned refusal, emit `agent_response`, `telemetry.incr("agent_scope_blocks_total")`, `state.reset()` (the legal "turn complete → IDLE"; there is no `OBSERVING→RESPONDING` edge), return. **Zero main-model generation** for an off-domain turn — one cheap classify call and done.

- **Coverage is uniform across chat / bot / cron** because the rail lives in `GuardrailEngine` + the persona dict (which all three surfaces feed to the engine), not in one wiring path. Only `mode:"restrict"` personas pay the classify call; every other persona pays nothing.

### Why LLM-judge and not the embedding gate (yet)
The `brain` embedding intent-gate (NeMo's exact mechanism — cheaper, no per-turn LLM call) remains the right *optimization*, but the LLM-judge was chosen first because `self._llm` is already injected and the call pattern is already proven in production by the semantic output filter. It is the lowest-risk correct implementation. The embedding gate is a drop-in swap behind the same `evaluate_input` seam when per-turn latency/cost warrants it.

### Fleet, fixed structurally
`V038` sets Fleet's `scope_policy` to `mode:"restrict"` with the Fleet domain + a branded refusal — **content-targeted, not by hardcoded `persona_id`** (id numbering differs across prod/uat/sit/tenant DBs), and only where `scope_policy` is still default (idempotent, won't clobber operator tuning).

### Deliberately NOT over-built
The copilot's tool whitelist already bounds *actions*; an off-domain text answer is brand annoyance, not an incident. So the rail is **off by default**, opt-in per persona, and fail-open — the control cost matches the real threat (accidental off-topic ≫ adversarial jailbreak for an embedded enterprise copilot). No blanket LLM-judge on every persona's every turn.

---

## 6. Status & follow-ups

**Shipped (this change):**
- [x] `scope_policy` column + `V038` migration (idempotent, content-targeted Fleet population).
- [x] `GuardrailEngine.evaluate_input` input scope rail (LLM-judge, robust parse, fail-open + telemetry).
- [x] Wired at the `AgentLoop` pre-generation seam; uniform across chat/bot/cron.
- [x] `persona_repo` reads + writes `scope_policy` as a first-class column (create/update/normalize).
- [x] Unit tests: `agent.core/tests/test_input_scope_rail.py` (12 cases: activation, block/allow, continuity, prefix tolerance, blank-input, fail-open/closed, default refusal, JSON-string parse). Full suite green (323 passed).

**Follow-ups (increments, not blockers):**
- [ ] **Verify + deploy:** run the `V038` migration on prod/uat/sit + tenant DBs; re-test the exact "write me a script" prompt on the Fleet **bot** and **embedded app**.
- [ ] **Admin surface:** expose `scope_policy` (and, consistently, `execution_policies` / DLP) in the persona-create/update API request models + web persona editor. Today these are DB-configured — this is a UI increment, not an architectural gap.
- [ ] **Bootstrap seed:** give new personas a sensible default `scope_policy` prompt in the seed so scope is a first-class choice at creation.
- [ ] **Optimization:** swap the LLM-judge for the `brain` embedding intent-gate behind the same `evaluate_input` seam where per-turn latency/cost matters.
- [ ] **Output backstop:** optionally extend the existing `apply_output_filter_async` semantic pass with topic rules for brand-sensitive tenants.
- [ ] **Usage metering:** count the classifier's tokens toward the tenant ledger (currently unmetered — same as the existing semantic output filter).
