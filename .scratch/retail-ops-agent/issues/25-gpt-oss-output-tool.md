# 25: Live Mode runs an Ops Day on gpt-oss-120b

**What to build:** Make Live Mode's real-model path work on the shared Groq key (`openai/gpt-oss-120b`), and make a failed Ops Day fail gracefully.

**Blocked by:** 20

**Status:** awaiting-merge
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/20

Found while doing Issue 21. The first real Intake call of an Ops Day fails: gpt-oss-120b calls `check_upload` correctly, then returns its answer through a tool it calls `json` instead of pydantic-ai's output tool `final_result`. It does this again on the retry, so the run fails with `UnexpectedModelBehavior` ("Unknown tool name: 'json'"). The dashboard only catches `ModelAPIError`, so the Visitor sees a raw traceback, and the failed run still uses up a shared-key slot. Probes against the real model: `NativeOutput` is refused alongside function tools, `PromptedOutput` fails the same way about half the time (with a `JSON` tool), and `ToolOutput(..., name="json")` succeeded 4 out of 4 times.

- [x] Intake, Analyst and Ops agents name their output tool `json`, the name gpt-oss uses
- [x] Any model failure in Run day shows the "run the day again" message instead of a traceback (catch `AgentRunError`, not only `ModelAPIError`)
- [x] A shared-key Ops Day that fails for a reason other than a provider rate limit gives its slot back
- [x] One full Ops Day runs against the real gpt-oss-120b before merging

## Comments

### Implementer (2026-11-20)

- New `retail_ops_agent.output_tool`: `output_tool(T)` is `ToolOutput(T, name="json")`, with the reason in its docstring. The Intake, Analyst and Ops agents return their answer through it. Other models call the output tool by whatever name it has, so nothing changes for them or for the offline scripted models.
- `SharedKeyLimiter.release()` gives back the latest run. `run_live_day` calls it when a shared-key Ops Day fails for any reason other than a provider rate limit, and re-raises the error.
- The dashboard catches `AgentRunError` (the base of `ModelAPIError` and `UnexpectedModelBehavior`) around Run day, so any model failure shows the "run the day again" message.
- Tests: a `GptOssLike` wrapper model renames every output-tool call to `json`, the way gpt-oss does, and runs every remaining sandbox day through all three agents. It failed with the same `Unknown tool name: 'json'` error before the fix. Two more tests: a failed day gives its slot back, and the dashboard shows a message, not a traceback. Gate: ruff, ruff format, pyright, pytest (390 passed).
- Real model (`groq:openai/gpt-oss-120b`, `.env.local` key, through `run_live_day`): four sandbox days in a row, 2026-11-14 to 11-17, each with 14 Uploads. The last one had a stockout-risk Anomaly that the Analyst investigated and the Ops agent turned into a proposed Reorder. No failures.

**Open finding (not fixed here):** the free tier's per-minute limit is easy to reach. Days run back to back took 76–133s while the Groq client waited and retried on 429s. On an earlier attempt the retries ran out on the second day back to back. A per-minute 429 is handled like a daily one: `limiter.exhaust()` marks the shared key used up for the whole window, for every Visitor (until the app restarts). That was Issue 20's design (`test_a_provider_rate_limit_on_the_shared_key_asks_for_the_visitors_own_key`). Telling per-minute and daily limits apart, or pacing the shared model, is a separate decision.
