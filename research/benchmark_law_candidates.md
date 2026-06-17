# Benchmark Law Candidates

## Candidate Laws

| candidate | claim | status |
| --- | --- | --- |
| evidence-density floor | GAR strengthens when evidence density is >= 4 | passes as a weak boundary; ceiling cells still limit gap estimation |
| retrieval-burden ceiling | GAR weakens when retrieval burden is >= 4 | best supported benchmark-level law candidate |
| ambiguity threshold | GAR gap compresses when ambiguity is >= 4 | supported, but entangled with retrieval burden |
| branching threshold | commitment drifts later when branching factor is >= 5 | supported for trajectory shape, not sufficient for GAR alone |
| planning-depth threshold | planning depth >= 5 changes commitment only when paired with branching/tool dependence | conditional only |

## Best Candidate

The strongest benchmark-level law candidate is the retrieval-burden ceiling:

> Grounded-action ratio behaves like a stable weak invariant only while decisive evidence is available without high retrieval burden; when retrieval burden reaches the high class, benchmark dependence dominates.

This is a candidate boundary law, not a universal execution law. It explains why research benchmarks remain hard even when model-family and task-family transfer look acceptable.

## Rejected Strong Laws

No ambiguity-only, planning-only, evidence-only, or branching-only threshold fully controls benchmark dependence. Each single-property threshold leaves at least one exception: ceiling coding cells, high-verification formal cells, or recovery-heavy agentic cells.
