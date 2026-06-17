# Trajectory Normalization

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Runs were normalized by execution fraction using the sampled 10%, 25%, 50%, and 75% windows. Event count and reasoning-step normalization are represented by existing state switches, branch-collapse, grounding latency, and evidence-action latency fields rather than a newly invented composite score.

## Normalized State Shape

| normalized point | grounded-or-better share | converging share | stuck share | state counts |
| --- | --- | --- | --- | --- |
| 10% | 0.229847 | 0.0 | 0.28976 | exploring:441, grounded:211, stuck:266 |
| 25% | 0.271242 | 0.0 | 0.305011 | exploring:389, grounded:249, stuck:280 |
| 50% | 0.311547 | 0.279956 | 0.200436 | converging:257, exploring:448, grounded:16, recovered:13, stuck:184 |
| 75% | 0.311547 | 0.279956 | 0.200436 | converging:257, exploring:448, grounded:16, recovered:13, stuck:184 |

## Prefix Predictability Shape

| prefix | features | holdout R2 | prospective R2 | uncertainty p(1-p) | collapse from 0% | entropy drop | holdout R2 delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% | 7 | 0.406068 | 0.0 | 0.147799 | 0.0 | 0.0 | 0.0 |
| 10% | 9 | 0.342405 | 0.0 | 0.154674 | -0.046518 | -0.006875 | -0.063663 |
| 25% | 13 | 0.423852 | 0.005219 | 0.154735 | -0.046928 | -6.1e-05 | 0.081447 |
| 50% | 17 | 0.632214 | 0.109202 | 0.088636 | 0.400294 | 0.066099 | 0.208362 |
| 75% | 21 | 0.613042 | 0.039278 | 0.095919 | 0.351017 | -0.007283 | -0.019172 |
| 90% | 24 | 0.624795 | 0.099063 | 0.096129 | 0.349597 | -0.00021 | 0.011753 |

## Determination

Different runs do share a coarse common shape: exploration/retrieval comes first, grounding appears next, and outcome commitment concentrates near the middle of execution. The common shape is probabilistic, not deterministic. The 50% prefix is the clearest normalized point where uncertainty collapse and grounded-action conversion align.
