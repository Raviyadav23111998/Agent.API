# Efficiency Implementation Plan — real, code-grounded (2026-07-05)

Two independent inefficiencies, each proven in *our* code/data (not a hermes port). Both are
"stop doing redundant work." Senior-eng design, **no hardcoding**, stays on the Claude Code
cache-first track.

- **Part A — LLM-to-press-a-button:** a cron whose job is "invoke tool X" spins up a full
  agent (20.5k-token prompt) to decide to call one deterministic tool. → general `[TOOL:]`
  cron primitive, zero LLM.
- **Part B — open the same page again and again:** `page_read`/`page_observe` re-execute a full
  browser round-trip every call AND (mis-classified as *writes*) wipe the whole read cache,
  forcing `view_file`/`grep` to re-run too. → fix tool-policy classification so genuine reads
  are memoized.

Both boundaries only; neither touches the append-only hot path or the cached prefix.

---

# PART A — Deterministic tool crons (`[TOOL:]`)

## A.1 Evidence
Prod `llm_usage` (7–14d): **cron = 83% of tokens / 74% of cost, avg 20,552-token prompt.**
The sink is `brain_auto_sync`: every 30 min a full LLM agent whose only act is calling
`brain_sync` → `sync_worker.sync_all()` (deterministic). Max prompt anywhere = 42k → we never
compact; the spend is almost entirely "LLM presses one button."

## A.2 Principle
A cron that just runs one tool needs no LLM. Declare the tool + args **as data in the cron
row**; execute it directly. No operation is special-cased in code (the earlier `_BrainSyncOp`
class was deleted — that was the hardcoding).

## A.3 The primitive
```
[TOOL:<tool_name>] <optional JSON args>
```
`brain_auto_sync` → `[TOOL:brain_sync] {"source":"all"}`. Joins the dispatch family
(`[CURATOR]`, `[AGENT:name]`, `[SYSTEM]`), and is the only LLM-free one.

## A.4 Execution — reuse the real path, minus the LLM
`_run_tool_cron` builds the **same** sandboxed registry the agent cron builds
(`create_user_tools(sandboxed=True)`) and runs the one tool through the **same**
`LocalToolExecutor` — identical call + subsystem resolution + tenant scope, without the 20.5k
prompt.
```
_run_tool_cron(prompt, app_id):
    name, args = parse("[TOOL:name] {json}")      # bad JSON / no name → clear error
    registry   = cli.create_user_tools(ws.ensure_workspace(0), sandboxed=True)
    if name not in registry: return "✗ [TOOL] unknown tool 'name'"   # NO llm fallback
    with current_user_context = cron_user (tenant already bound by tick):
        return await LocalToolExecutor(registry).execute(name, args)
```

## A.5 Governance (the key argument)
`[TOOL:]` grants **no new capability** — it can only call tools already in the sandboxed cron
registry (exactly what the agent cron could call). No approval (headless, like agent crons);
no persona/guardrails (there is no LLM output to filter). Creatable by cron-admin/seed only.

## A.6 Observability / learning
No LLM ⇒ **no `llm_usage` row** (the win). Run still recorded via `mark_job_run` +
`cron_job_outputs`; delivery unchanged. No `maybe_review` (no conversation).

## A.7 Changes
| File | Change |
|---|---|
| `gateway/runner.py` | dispatch `if prompt.startswith("[TOOL:")` → new `_run_tool_cron()`; **revert** the broken `[SYSTEM]`→`system_ops` bits I started; `[SYSTEM]`→persona-exempt agent stays for free-text infra. |
| `client/cli.py` | seed `brain_auto_sync` → `[TOOL:brain_sync] {"source":"all"}`. |
| ~~`gateway/system_ops.py`~~ | **deleted** (hardcoded op). |
| prod DB (1×) | `UPDATE …cron_jobs SET prompt='[TOOL:brain_sync] {"source":"all"}' WHERE name='brain_auto_sync'`. |

## A.8 Deploy order
**Code first, then the row.** New code + old row → old row runs as `[SYSTEM]`→agent (safe).
Row first → `[TOOL:]` hits old code → nonsense agent prompt. So code → row.

## A.9 Tests
Unit: parse name/args; no-args→`{}`; unknown tool→error (no LLM fallback); bad JSON→error;
fake tool executes + result returned. Live: trigger `brain_auto_sync` → correct sync report +
**zero `llm_usage` rows** for the window + gateway log shows the direct path, not
`agent_factory.spawning`.

---

# PART B — Page reads: stop re-fetching + stop poisoning the cache

## B.1 Root cause (verified)
`LocalToolExecutor` already has a working read-result cache (`_ReadResultCache`, 60s TTL,
invalidated on any write; hit→no re-execute + `tool_cache_hits_total`). BUT policies are
inferred from the tool NAME (`tools/tool_policy.py::default_policy_for`), and the default is
`side_effect=WRITE, cacheable=False`. **No `page_*` tool matches any read pattern**, so:

```
page_read      side_effect=write  cacheable=False   ← pure read, mis-classified
page_observe   side_effect=write  cacheable=False   ← pure read, mis-classified
page_act       side_effect=write  cacheable=False   ← correct (mutates the page)
page_navigate  side_effect=write  cacheable=False   ← correct
view_file      side_effect=read   cacheable=True    ← correct
```

Two costs from the mis-classification of the two *read* tools:
1. **Re-fetch:** every `page_read`/`page_observe` re-runs a full WS round-trip to the browser,
   even when the agent re-reads the same unchanged screen 2–3× in one reasoning burst.
2. **Cache poisoning (worse):** being tagged `write`, each page read triggers
   `invalidate_all()` → it **wipes cached `view_file`/`grep_search` results**, so those
   re-execute AND their output re-enters the append-only history → *more tokens*. A page read
   silently inflates unrelated file-read cost.

`query_neo4j` (a read that ends in `neo4j`, not `_query`) has the same bug — a symptom of
name-inference missing genuine reads.

## B.2 Architecturally-correct fix — tools DECLARE their policy
Name-inference is the root fault; adding more regexes just moves the brittleness. The registry
ALREADY accepts an explicit `policy=` (`tools/registry.py:35`); the `@tool()` decorator just
doesn't expose it. Fix at the source:

1. **Extend `@tool()`** (`tools/native_mcp.py`) to accept an optional
   `side_effect` / `cacheable` (or a `policy`), threaded into `registry.register(policy=…)`.
   `default_policy_for(name)` stays as the fallback for undeclared tools.
2. **Declare the page reads:** `page_read`, `page_observe` → `side_effect="read", cacheable=True`.
   Page **actions** (`page_act`, `page_navigate`, `page_wait`) stay `write` → they correctly
   `invalidate_all()`, so a cached page read can never survive a page mutation.
3. **Declare other known-misclassified reads** while we're here (`query_neo4j`, audit the tool
   list for `*read*`/`*observe*`/`*status*` that infer to `write`).

Result: repeated identical page reads within a turn are memoized (60s), page reads stop wiping
the file-read cache, and a page action still forces a fresh read.

## B.3 Staleness safety
A page can change without an agent action (async JS). Bounds: (a) 60s TTL; (b) every
page-mutating action invalidates; (c) an agent turn is seconds. For a governed copilot driving
forms/admin screens, actions are the mutation path → safe. If we later want tighter freshness,
add a **per-tool TTL** (page reads e.g. 10–15s) — noted, not required now.

## B.4 Changes
| File | Change |
|---|---|
| `tools/native_mcp.py` | `@tool(side_effect=…, cacheable=…)` optional kwargs → `register(policy=…)`. |
| `tools/page_tools.py` | declare `page_read`/`page_observe` as read+cacheable. |
| `tools/tool_policy.py` (optional) | add `query_neo4j` etc. to `_READ_PATTERNS`, or declare at their registration. |

## B.5 Tests
Unit: `default_policy_for` unchanged; a declared `@tool(side_effect="read", cacheable=True)`
yields that policy (not inferred). Executor: two identical `page_read` calls → 1 execution + 1
`tool_cache_hits_total`; a `page_act` between them → 2 executions (invalidated). Regression: a
`page_read` no longer invalidates a cached `view_file`.
Live (if copilot is exercised): `tool_cache_hits_total{tool=page_read}` > 0 after repeated
reads; confirm no correctness change on a form-drive flow.

## B.6 Impact
Removes redundant browser round-trips (latency) for the web copilot AND stops page reads from
evicting the file-read cache (which was causing extra re-reads → extra tokens). Correctness-
preserving (actions still force fresh reads).

---

# Sequencing & scope
- **A first** (bigger, isolated to the cron dispatch). **B second** (touches the tool
  framework + page tools; test the copilot flow).
- Effort: **A ≈ 0.5d, B ≈ 0.5–1d.**
- Out of scope (noted): per-user `[TOOL:]` governance, a UI tool-picker for tool crons,
  per-tool TTLs, a `[PIPELINE:]` multi-tool primitive, migrating all policy inference to
  declarations (do it opportunistically as tools are touched).
- DO NOT: cache page reads without action-invalidation; widen `[TOOL:]` beyond the sandboxed
  registry; port hermes per-turn context pruning (breaks the cached prefix).
