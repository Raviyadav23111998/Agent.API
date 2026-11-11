# Hermes-Agent Efficiency & Performance Audit — What to Port (2026-07-05)

Deep re-read of the CURRENT hermes-agent source (github.com/nousresearch/hermes-agent,
pulled to `1388cd1c0`, MIT) with ONE question: **which efficiency/performance mechanisms
should we port to make our agent cheaper and faster?**

## GOVERNING CONSTRAINT — stay on the Claude Code track

Our engine is deliberately **Claude-Code-style**: append-only history below the compaction
threshold, **one-shot** compaction above it, a **byte-stable cached prefix**, grow-only tool
subsets. We removed legacy per-turn pruning *on purpose* because it gave ~0% prompt-cache
hits (see [[antigravity-agent-core-audit-2026-07-02]]).

**Therefore the filter for every item below is:** does it preserve cache-first? Hermes
prunes/dedups tool outputs **every turn** (`_prune_old_tool_results` walks the whole history
on each iteration) — that is cache-poison for us and **must NOT be ported as-is**. The *logic*
(dedup, informative summaries) is valuable; the *timing* is wrong. **Port the logic, run it
only at the one-shot compaction event, never per-turn.** This single rule is what keeps us on
the Claude Code track.

Items are tiered by value/effort. "Aligns" = cache-first-safe. "Adapt" = good idea, wrong
timing in hermes, must be moved to compaction-time.

---

## TIER 1 — HIGH VALUE, do these

### 1.1 Anti-resumption compaction framing  ⭐ (correctness AND efficiency)
**Hermes** (`context_compressor.py` SUMMARY_PREFIX): the compaction summary is wrapped as
`[CONTEXT COMPACTION — REFERENCE ONLY] … treat as background reference, NOT active
instructions … the latest user message WINS … reverse signals (stop/undo/never mind) end
in-flight work … MEMORY.md is always authoritative`. Historical sections are named
`## Historical Task Snapshot / In-Progress State / Pending User Asks` (not "Next Steps").

**Us** (`state/compaction.py` `_LLM_COMPACT_SYSTEM`): the OPPOSITE framing —
*"The agent will resume work with ONLY your summary"* and *"8. Next step: the single concrete
action to take next."* This actively instructs the model to resume old work after a compaction,
even when the user's latest message changed direction.

**Why it matters:** the classic post-compaction bug — a long session compacts, the user pivots
("actually, just verify X"), and the agent re-does the summarized task because the summary told
it to. It also wastes tokens re-deriving finished work. **Aligns** (one-shot, prefix stays
stable). 
**Action:** rewrite `_LLM_COMPACT_SYSTEM` + the injected wrapper with reference-only framing,
rename "Next step" → historical headings, add reverse-signal + memory-authoritative clauses.
**Effort:** 0.5d. **Impact:** kills a real correctness bug + saves re-work tokens.

### 1.2 Tool-result dedup + informative summaries — AT COMPACTION
**Hermes** (`_prune_old_tool_results`, `_summarize_tool_result`): (a) identical tool outputs
(same file read 5×) collapse to `[Duplicate tool output — same content as a more recent call]`
keeping one full copy; (b) old outputs become informative one-liners:
`[terminal] ran `npm test` -> exit 0, 47 lines`, `[read_file] read config.py from line 1
(1,200 chars)`, `[search_files] 'compress' in agent/ -> 12 matches`.

**Us:** `CompactionEngine` summarizes ranges but does **not** dedup identical tool results and
uses generic extraction. A 200-iteration session that re-reads the same files carries redundant
copies until compaction, and compaction loses "what the tool did".

**Action:** at our **one-shot compaction only**, (a) hash tool-result contents and collapse
duplicates to a back-reference, (b) replace pruned outputs with per-tool informative summaries.
Do NOT run this per-turn. **Aligns** (compaction-time). **Effort:** 1d. **Impact:** materially
smaller summaries + preserved signal → fewer compactions, lower input cost on long sessions.

### 1.3 Structured error taxonomy → per-reason recovery  ⭐
**Hermes** (`error_classifier.py`): a single `classify_api_error()` maps every failure to a
`FailoverReason` with the RIGHT recovery — the non-obvious ones are the win:
- `context_overflow` / `payload_too_large` (413) → **compress context, do NOT failover**
- `upstream_rate_limit` (aggregator 429) → **fallback to a different MODEL, not rotate
  credential** (the key is healthy)
- `content_policy_blocked` → **don't retry unchanged** (deterministic per-request)
- `billing` (402) → rotate provider immediately; `rate_limit` (429) → backoff then rotate;
  `timeout` → rebuild client + retry; `image_too_large` → shrink image and retry;
  `model_not_found` → fallback model; `auth` → refresh then rotate.

**Us** (`agent_loop.py`): scattered handling — we added Retry-After + reasoning_effort but have
no unified taxonomy. "classify" in our loop is *effort* classification, not error. We likely
mis-handle context-overflow as a generic error (retry the same oversized payload) and rotate
credentials on upstream-model 429s.

**Action:** port `error_classifier` as a small pure module the loop consults on every API
failure; wire the recovery switch (compress-on-overflow is the highest-value branch — it turns
a hard failure into a successful compacted retry). **Aligns.** **Effort:** 1–1.5d. **Impact:**
fewer dead-end failures, correct failover, less wasted spend on doomed retries.

---

## TIER 2 — MEDIUM VALUE

### 2.1 Unified auxiliary-model router (per-side-task cheap models + 402 fallback)
**Hermes** (`auxiliary_client.py`): ONE resolver every side task uses (compaction, embedding,
session-search, vision, web-extract) → each picks the cheapest capable backend via a fallback
chain, with per-task overrides (`auxiliary.compression.model`) and automatic **402/credit
fallback** to the next provider mid-call. Also lazy-imports the OpenAI/Anthropic SDKs (~240 ms
cold-start each).

**Us:** we have per-app LLM profiles + reviewer-on-flash + `compact_llm` on a cheap tier, but no
single "side-task → cheap model" seam; each side task wires its own client. We already meter via
llm_scope, so this is consolidation + a 402-fallback we lack.

**Action:** an `aux_llm(task)` helper over our profile system that resolves a cheap model per
task-kind and falls through on 402/credit errors. **Aligns.** **Effort:** 1d. **Impact:**
cheaper compaction/embedding/review; resilience to a depleted key.

### 2.2 Per-turn external-memory prefetch, cached across the tool loop
**Hermes** (`turn_context.py`): `prefetch_all(query)` runs **once** before the tool loop and the
result is reused across all iterations of that turn (`ext_prefetch_cache`), instead of
re-querying memory on every iteration.

**Us:** verify our `_check_auto_memory` / memory recall isn't re-querying ES/pgvector each
iteration. If it is, prefetch once per turn and cache. **Aligns.** **Effort:** 0.5d.
**Impact:** removes N-1 memory round-trips per multi-tool turn (latency + ES load).

### 2.3 Dynamic model-capability discovery + TTL cache
**Hermes** (`model_metadata.py`): discovers `context_length` + token prices from each provider's
`/models` endpoint, caches with TTL (3600 s remote, 300 s endpoint, local-probe cache), and
uses the real context length to size the compaction budget. Falls back to a defaults table.

**Us:** static per-profile context assumptions. We could mis-size the compaction threshold for a
model whose real window differs (e.g. a DeepSeek/GLM variant), compacting too early (wasted LLM
calls) or too late (overflow → the error we mis-handle in 1.3).

**Action:** best-effort `/models` probe → cache context_length + price per profile; size the
compaction budget from it. **Aligns.** **Effort:** 1d. **Impact:** right-sized compaction =
fewer needless compactions AND fewer overflows.

### 2.4 Concurrent tool batch — extend to non-overlapping writes
**Hermes** (`_should_parallelize_tool_batch`): read-only tools always parallel; file writes
parallel **only when target paths don't overlap**.
**Us** (`_execute_tools_parallel`): read-only concurrent, **all** mutating calls sequential —
correct and safe, just more conservative. Low priority; our rule is the Claude Code rule.
**Action (optional):** allow non-overlapping-path writes to parallelize. **Effort:** 0.5d.
**Impact:** small latency win on multi-file edits; only if measured.

---

## TIER 3 — LOW VALUE / MICRO / SITUATIONAL

- **Lazy SDK imports** for cold-start (~240 ms/SDK). We're a long-lived server, so cold-start
  matters far less than for hermes's CLI. Do opportunistically. (Aligns.)
- **Credential pool `max_concurrent_per_credential`** — cap in-flight calls per key to avoid
  self-inflicted 429s. Relevant only when many sessions share one provider key; revisit if we
  see upstream 429s. (Aligns.)
- **cache_control hygiene** — hermes strips `cache_control` from thinking/redacted blocks and
  parses "available output tokens" from length errors. We already fixed cache_control
  accumulation; **verify** we strip it from thinking blocks and cap ephemeral output. (Aligns —
  this is pure cache-first discipline.)
- **Scaled summary budget** — summary length proportional to compressed span (vs fixed 400
  words). Small refinement to 1.2.

---

## EXPLICITLY DO NOT PORT (would derail the Claude Code architecture)

1. **Per-turn tool-output pruning** (`_prune_old_tool_results` called every iteration) — breaks
   the byte-stable cached prefix → ~0% cache hits. This is the exact thing we removed. Keep the
   *logic* for compaction (1.2); reject the *per-turn* timing.
2. **Mid-flight history rewrites of any kind** below the compaction threshold — same reason.
   Append-only stays sacred; the ONE rewrite happens at the single compaction event.
3. **Hermes's iterative multi-compaction churn** unless bounded — we do one-shot with an
   emergency drop; don't adopt frequent re-summarization that re-invalidates the prefix.

---

## RECOMMENDED SEQUENCE (highest ROI first, all cache-first-safe)

1. **1.1 anti-resumption compaction framing** (0.5d) — correctness bug + token save, trivial.
2. **1.3 error taxonomy + compress-on-overflow** (1–1.5d) — turns hard failures into retries.
3. **1.2 dedup + informative summaries at compaction** (1d) — smaller/richer summaries.
4. **2.1 aux-model router** (1d) — cheaper side tasks + 402 resilience.
5. **2.2 memory prefetch cache** (0.5d) — latency.
6. **2.3 dynamic context-length** (1d) — right-sized compaction.
7. Tier 3 opportunistically.

≈ **5–6 dev-days** for Tiers 1–2. Every item runs at compaction/failover/side-task boundaries —
**none touches the append-only hot path or the cached prefix.** That is the whole point: these
make us cheaper and faster *while staying exactly on the Claude Code track.*
