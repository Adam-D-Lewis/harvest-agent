# harvest-agent evals

A `pydantic_evals` suite that exercises the agent against canned harvest CLI fixtures and a frozen "today" date. Deterministic, hermetic, fast (~2-3 minutes total across 26 cases).

## Running

```bash
cd harvest-agent

# Default model (HARVEST_AGENT_MODEL or ANTHROPIC_API_KEY)
pixi run evals

# Against Qwen3-Coder-Next via local llama.cpp
HARVEST_AGENT_BASE_URL=http://localhost:8080/v1 \
HARVEST_AGENT_MODEL=Qwen3-Coder-Next \
pixi run evals
```

Comparing two models = run it twice with different env vars and eyeball the two reports.

## Categories

| Category | # | What it tests |
|---|---:|---|
| `tool_selection` | 5 | Does the agent pick the right tool for a request? (view_today vs view_week vs status etc.) |
| `shortcut` | 3 | Does it translate `"acme"` → `Web Redesign / Programming` when calling `log_time`? |
| `relative_date` | 7 | Does it compute `tomorrow`, `last Friday`, `next Monday` (including month-boundary) correctly? |
| `empty_state` | 2 | When `view_today` returns `null`, does it say "no entries" instead of hallucinating? |
| `cancel_respect` | 2 | When a destructive op is cancelled, does it relay the cancellation without retrying? |
| `hallucination` | 3 | When asked to do something we have no tool for (rename project, submit timesheet), does it refuse instead of making up a tool call? |

Total: **22 cases**.

### Why no "rounding" category?

Hour rounding to the nearest 0.25 happens deterministically inside `tools.log_time` / `tools.edit_entry` — see `_round_to_quarter`. It's covered by unit tests that run in milliseconds. Paying LLM inference cost to verify Python arithmetic is waste.

## The "next Monday" case

One `relative_date` case is specifically for the failure mode where an LLM computes a day-of-week correctly but gets the calendar date wrong — the typical symptom is "I asked for Monday but it logged it on Tuesday." The killer variant is `date_next_monday_crosses_month`: today is Wed 2026-04-29, "next Monday" is expected to be 2026-05-04, which requires crossing the April → May boundary. LLMs that do day-of-week math by simple offset arithmetic often fumble this one.

## How the task function works

1. Builds a fresh `Config` with known shortcuts (not the user's real config — evals must be reproducible).
2. Builds the agent with a **frozen today** (so `"tomorrow"` has a known correct answer). The `today` is set via `_build_agent(cfg, today=...)`.
3. Patches `harvest_cli.run` to return canned responses from a `HarvestFixture` (`empty`, `entry_99`, `multiple_entries`).
4. Patches `confirm.confirm_action` to return True or False (per case) without touching stdin.
5. Runs `agent.run(prompt)` and walks `result.all_messages()` to pull out every `ToolCallPart` the model produced.
6. Returns `AgentRunOutput(text, tool_calls)`.

Evaluators then inspect `tool_calls` and `text` — they never dig into PydanticAI internals.

## Custom evaluators

| Evaluator | Use |
|---|---|
| `ToolCalledWith(name, required_args)` | A LLM tool call with matching name and args exists (pre-tool-processing) |
| `ToolNotCalled(name)` | A specific tool (or all tools if `name=None`) was NOT called |
| `HarvestCLIInvokedWith(subcmd, positional, flags)` | The harvest CLI was invoked with matching args (post-tool-processing — checks shortcut resolution, date parsing, hour rounding) |
| `OutputContainsAny(substrings)` | Case-insensitive "any substring matches" text check (curly apostrophes normalised) |

The distinction between `ToolCalledWith` and `HarvestCLIInvokedWith` matters when the tool does processing on top of what the LLM passed:

- **Use `ToolCalledWith`** for "did the LLM pick the right tool" checks and for `ToolNotCalled`-style hallucination guards.
- **Use `HarvestCLIInvokedWith`** for end-to-end checks: did the CLI ultimately get the right project (after shortcut resolution), the right date (after natural-language date parsing), the right hours (after rounding).

## Results against Qwen3-Coder-Next

After moving rounding, shortcut resolution, and relative date parsing into the tool functions (so the LLM only has to pass the user's literal phrasing), Qwen3-Coder-Next (Q4_K_M, via local llama.cpp) hits **100% pass rate (22/22 cases, 34/34 assertions)**.

The pattern: any deterministic processing the LLM doesn't need to do, push into Python code. Shortcuts get resolved by `_resolve_shortcut`, dates by `_parse_date`, hours by `_round_to_quarter`. The system prompt tells the LLM "pass the user's words verbatim — the tool will handle the conversion." This eliminates an entire class of model failures, doesn't depend on the model being smart, and has the side benefit of working identically across every backend.

What's left in the eval suite is testing the things only an LLM can do: pick the right tool for an ambiguous request, recognize empty state, refuse to hallucinate operations we don't have tools for, and respect cancellation results.
