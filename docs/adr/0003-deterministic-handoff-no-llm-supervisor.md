# Deterministic handoff between agents, with no LLM supervisor

There are three agents: Intake, Analyst and Ops. Each has its own tools and permissions. A deterministic pipeline passes work from one to the next, and Anomalies are detected by statistics, not by a model. The LLM only investigates, explains and recommends. We rejected an LLM orchestrator that decides which agent runs next. It looks more "agentic", but it adds a nondeterministic step that is hard to evaluate and debug, and that step would decide which agent's permissions apply.

## Consequences

The one routing decision the model does make, an Investigation concluding Data Problem, goes back to Intake as a structured outcome, not as a free-form handoff.
