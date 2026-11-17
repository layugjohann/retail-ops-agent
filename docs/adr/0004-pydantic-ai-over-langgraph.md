# Pydantic AI for the agents, not LangGraph

The agents are built with Pydantic AI. It gives typed, validated agent outputs, works with Groq, Gemini and frontier providers (see ADR 0001), and is light enough that the pipeline stays plain Python.

## Considered Options

- **LangGraph**: the best-known agent framework, but its graph runtime would duplicate the deterministic pipeline from ADR 0003 and adds a lot of machinery for three agents.
- **The raw provider SDK with a hand-written tool loop**: used in earlier projects; it would mean rebuilding provider switching and output validation.
