"""A persona's tool whitelist is a ceiling, and an empty ceiling is zero.

`persona_applicator` appended the skills tools to every persona under the
reasoning that skills are engine infrastructure rather than persona capability.
That reasoning is sound for a persona that HAS tools and wrong for one that has
declared it wants none: it turns a stated "no tools" into three.

It was not theoretical. PrepCrest's authoring persona (V042, `allowed_tools`
`'[]'`, "NO TOOLS. Narrower than the tutor's on purpose") is a payload contract
that should answer once and stop. In production it was logged twice, one line
apart, flatly contradicting itself:

    WARNING  Persona 'PrepCrest Authoring' (app_id=7) has empty allowed_tools
             — agent will have NO capability tools.
    INFO     SessionPool: Created session for conv=1fda8f9d (tools: 3, ...)

With something to call, the agent loop iterated instead of returning. One turn
of batch 9, from `ag_system.transcript_logs`:

    TOOL_CALLS         11
    TOOL_SKILL_MANAGE   9    'author-jee-integral-calculus-questions'
    TOOL_SKILL_VIEW     2     patched ... v3, v4, v5, v6, v7, v8

The question-author spent thirty minutes writing a skill about how to write
questions and never wrote a question — 21 LLM calls on a turn that wanted one,
ended by the caller's 1800s deadline with nothing banked.
"""

from api.services.persona_applicator import effective_tool_names


SKILLS = ("skills_list", "skill_view", "skill_manage")


# ── the defect ───────────────────────────────────────────────────────────

def test_a_persona_that_declared_no_tools_gets_none():
    assert effective_tool_names([], learning_on=True, skill_tools=SKILLS) == []


def test_an_absent_whitelist_is_the_same_as_an_empty_one():
    # The column defaults to '[]' and the repo coerces a missing value to [],
    # so None and [] reach here interchangeably and must not diverge.
    assert effective_tool_names(None, learning_on=True, skill_tools=SKILLS) == []


# ── what must keep working ───────────────────────────────────────────────

def test_a_persona_with_tools_still_gets_its_skills():
    # The original intent, preserved exactly: procedural memory is about how to
    # USE capability, so it belongs wherever capability is.
    names = effective_tool_names(
        ["brain_ask"], learning_on=True, skill_tools=SKILLS)

    assert names[0] == "brain_ask"
    assert set(names) == {"brain_ask", *SKILLS}


def test_skills_are_not_added_when_learning_is_off():
    assert effective_tool_names(
        ["brain_ask"], learning_on=False, skill_tools=SKILLS) == ["brain_ask"]


def test_a_persona_that_asked_for_a_skill_tool_does_not_get_it_twice():
    names = effective_tool_names(
        ["skill_view", "brain_ask"], learning_on=True, skill_tools=SKILLS)

    assert names.count("skill_view") == 1
    assert set(names) == {"brain_ask", *SKILLS}


def test_the_personas_own_order_is_preserved():
    # The registry is built by iterating this list, so a stable order keeps the
    # tool spec sent to the model stable — which is what makes prompt caching
    # hit across turns.
    names = effective_tool_names(
        ["b", "a", "c"], learning_on=True, skill_tools=SKILLS)

    assert names[:3] == ["b", "a", "c"]
