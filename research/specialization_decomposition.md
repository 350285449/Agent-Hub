# Specialization Decomposition

rho is currently a model-category outcome residual. This audit splits it into observable category/architecture dimensions without changing rho itself.

| dimension | corr | AUC | single-var R2 | redundancy vs K/A |
| --- | --- | --- | --- | --- |
| agent_execution | 0.622291 | 0.912485 | 0.387246 | 0.476185 |
| reasoning | 0.419158 | 0.78585 | 0.175693 | 0.316315 |
| retrieval | 0.36509 | 0.691682 | 0.133291 | 0.701058 |
| planning | 0.346619 | 0.748766 | 0.120145 | 0.20167 |
| coding | 0.333049 | 0.695982 | 0.110922 | 0.190331 |
| long_context | 0.320727 | 0.672692 | 0.102866 | 0.477172 |
| research | 0.0 | 0.5 | 0.0 | 0.0 |
| math | 0.0 | 0.5 | 0.0 | 0.0 |
| tool_use | 0.0 | 0.5 | 0.0 | 0.0 |

Survival verdict:

- Measurable now: coding/category affinity, retrieval affinity, long-context affinity, and output-side agent-execution affinity.
- Predictive now: mostly the dimensions that proxy existing K/rho or output behavior.
- Prospectively surviving: not established here. A frozen panel must measure model x repository x category x architecture cells before outcomes.
- rho should not be discarded, but it should be remeasured as a vector of frozen affinities rather than one coarse scalar.
