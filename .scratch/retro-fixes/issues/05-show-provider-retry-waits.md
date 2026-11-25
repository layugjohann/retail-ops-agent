# 05: Show provider retry waits, and cap them

Status: ready-for-agent
Blocked by: None

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
- [ ] Throttle is shared by `make record`, the trigger and Live Mode through `paced_models_from_environment`. Check
      that a cap error in Live Mode shows the "run the day again" message, not a traceback.
