# 05: Show provider retry waits, and cap them

Status: ready-for-agent
Blocked by: None
Stacked on: issue/04-lint-the-mechanical-standards

**What to build:** Make `ThrottledModel` (`src/retail_ops_agent/evals/throttle.py`) say when and why it waits, and
stop it from silently waiting for hours.

On 2026-11-24, Groq's free tier answered 429 with "try again in 2h24m" once the daily 150,000 tokens were used up.
`ThrottledModel.request` slept out `error.retry_after` without a word, so two eval runs looked hung. A 120 s request
timeout (`d67a5b9`) was added for what was really a quota wait.

- [ ] Every retry logs one line on stderr (or through `logging`): the model name, the status (429, 503 or timeout),
      the attempt number, how long it will wait, and the provider's message.
- [ ] A `max_wait_seconds` cap (default 300): when `retry_after` is longer, raise an error whose message names the
      provider's wait (for example "Groq asks to wait 2h24m: daily token limit likely spent"), instead of sleeping.
- [ ] The eval runner records that error as the Scenario's error, so the Scorecard shows it.
- [ ] Tests with a fake clock (no real sleeping): a short `retry_after` is waited out and logged, and a long one
      raises at once.
- [ ] Throttle is shared by `make record` and the trigger through `paced_models_from_environment`. Live Mode is out
      of scope: it uses the unthrottled `models_from_environment` and answers provider rate limits with
      `OwnKeyNeeded` at once, which is right for an interactive page. Do not add the throttle to Live Mode, and drop
      the dashboard test that monkeypatches a `ThrottledModel` into Live Mode.
- [ ] The cap error says who asked for the wait: "Groq asks to wait …" only when the wait comes from the provider's
      `retry_after`; when it is the throttle's own back-off (a timeout, or a 503 without `retry_after`), the message
      says so instead.
- [ ] The cap message does not use "run" (a word `GLOSSARY.md` says to avoid).

## Comments

Usage: Implementer 52 input, 12,042 output, 42,146 cache creation, 1,032,581 cache read; Review Session 20 input, 4,123 output, 25,236 cache creation, 315,227 cache read.

**Review Session: Non-critical Findings**

- Live Mode (live.py:264) builds models with models_from_environment, not paced_models_from_environment, so it never uses ThrottledModel and can never raise ProviderWaitTooLong in production. The new dashboard test forces a ThrottledModel in through monkeypatch, so it covers a path production never takes.
- ThrottledModel._wait_to_retry uses the same 'X asks to wait …' wording when the wait is its own back-off (a timeout, or a 503 without retry_after) that goes over max_wait_seconds. That message is misleading, because the provider asked for nothing. It cannot happen with the default backoff_seconds and max_retries.
- The cap message says 'longer than the … this run waits'. GLOSSARY.md lists 'run' as a word to avoid.

**Review Session: Spec disagreement (not acted on)**

- The Issue says the throttle is shared by make record, the trigger and Live Mode through paced_models_from_environment, but Live Mode uses the unthrottled models_from_environment and turns provider rate limits into OwnKeyNeeded. A cap error therefore cannot happen in Live Mode as the code stands. Putting the throttle into Live Mode would change how it handles rate limits, which needs its own decision.

**Decision (2026-11-26): spec changed, option 1**

- Live Mode stays unthrottled. A rate limit there keeps raising `OwnKeyNeeded` right away; waiting out a provider's
  retry would leave a Visitor looking at a hung page. The Live Mode checkbox is rewritten to say this, and the review's
  two message findings are now checkboxes. Back to `ready-for-agent`; finish on `issue/05-show-provider-retry-waits`.
