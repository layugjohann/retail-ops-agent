# 06: Model keys setup (human)

**What to build:** A one-time human step: create free-tier Groq and Gemini API keys and add them to `.env.local` so evals can call real models. Optionally add a frontier key (your own key) for comparisons.

**Blocked by:** 01

**Status:** done

- [x] Free-tier Groq key and Gemini key created, with data-retention settings reviewed
- [x] `.env.local` filled in from `.env.example` and confirmed to be git-ignored
- [x] A one-line smoke check confirms each key reaches its model

## Comments

Closed by hand on 2026-11-19.

- Keys: free-tier Groq and Gemini keys are in `.env.local`, which `.gitignore` ignores (`.env*`). Nothing loads it automatically, so run commands with `uv run --env-file .env.local ...`.
- Data retention: the Gemini free tier allows Google to use prompts and responses to improve its products. That is acceptable only because every request carries synthetic Cobalt Home data. A real Client would need paid or zero-retention terms; note this in the Deployment Playbook.
- Smoke check (plain reply plus a typed Pydantic output):
  - `google:gemini-3.5-flash-lite`: OK.
  - `groq:llama-3.3-70b-versatile`: 404 `model_not_found`. Groq has retired it.
  - `groq:openai/gpt-oss-120b`: OK. This is now `DEFAULT_GROQ_MODEL` in `src/retail_ops_agent/models.py`.
  - `groq:qwen/qwen3.8-27b`: OK, kept as a fallback.
- Free-tier models get retired without notice. Before an eval run, confirm the default model names still exist, or a 404 will look like a broken pipeline.
- No frontier key yet. Using one needs the matching `pydantic-ai-slim` extra, e.g. `[anthropic]`, plus `RETAIL_OPS_MODEL`.
