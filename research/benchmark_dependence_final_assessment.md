# Benchmark Dependence Final Assessment

## Questions

1. What causes benchmark dependence?

Benchmark dependence is caused by evidence availability and action branching. GAR transfers across families because grounded action generally helps, but benchmark structure decides whether grounding can happen early enough and whether a grounded action uniquely determines the successful path.

2. Which benchmark property matters most?

Retrieval burden matters most, with evidence density second and ambiguity third. High retrieval burden separates evidence discovery from action execution; low evidence density makes the action/evidence link sparse; ambiguity keeps multiple action branches alive after evidence appears.

3. Do conditional invariants exist?

Only weak conditional invariants exist. GAR is more coherent inside low-retrieval, low-ambiguity, high-evidence-density benchmark classes, but the evidence does not support a strong universal invariant.

4. Does grounded-action ratio become strong inside benchmark classes?

No. It becomes stronger and more interpretable, but not strong in the strict sense. Ceiling cells have no estimable gap, while high-retrieval and high-branching cells still show compressed benchmark-level separation.

5. Is there a benchmark-level law?

No strong benchmark-level execution law is established. The best candidate is a retrieval-burden boundary: high retrieval burden breaks GAR universality by delaying or fragmenting decisive evidence. This is a law candidate, not a controlled law.

6. What prevents universality?

Universality is prevented by benchmark designs where evidence is late, sparse, distributed, ambiguous, or coupled to recovery/tool sequencing. In those settings, the same GAR value can correspond to different trajectory states.

## Final Verdict

B. Weak invariant only.

Reason: benchmark dependence is now explainable but not fully controlled. Conditional structure improves interpretation, especially around retrieval burden and evidence density, yet it does not remove ceiling effects, sparse-evidence failures, or recovery-driven trajectory dependence.
