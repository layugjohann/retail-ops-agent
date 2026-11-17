# Zero cost: free-tier models by default, bring your own key for frontier models

This is a portfolio project, so it must cost nothing to build, run, demo and host. The agents default to free-tier models (Groq, Gemini). Anyone can supply their own key to run frontier models. Eval runs are slowed to stay inside free-tier rate limits. The demo is hosted on Streamlit Community Cloud. n8n runs only locally, in Docker, because its hosted version is paid.

## Consequences

Free models are worse at tool calling. We treat that as a finding: the eval scorecard compares free and frontier models and shows where the cheap model is good enough.
