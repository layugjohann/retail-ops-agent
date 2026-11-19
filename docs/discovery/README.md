# Discovery documents

> **SIMULATED.** These documents are written as if by an engineer embedded at Cobalt Home, a fictional Client. No real company, person, interview or measurement is behind them.

What a forward-deployed engineer writes in the first days of an engagement, before building anything:

1. [Engagement brief](engagement-brief.md): why the engagement exists and what it should deliver.
2. [Personas](personas.md): the four people whose manual work the prototype takes on.
3. [Current manual processes](manual-processes.md): how the work is done today, step by step.
4. [Baseline](baseline.md): minutes per task and how often each one comes up.

The baseline's machine-readable form is
[`src/retail_ops_agent/baseline.json`](../../src/retail_ops_agent/baseline.json). The dashboard's
**Hours Saved** comes straight from it: for each baseline task, the Audit Log entries of the Action
that now does it (and that no undo reversed) times its minutes each time. The dashboard shows every
timing and its assumption next to the figure.

Every timing is marked either with a public source or as an assumption. At the moment, all of them
are assumptions: no public timing was found for these exact tasks, and none is invented. On a real
engagement they would be replaced by timings measured with the Client's staff (see the Deployment
Playbook).
