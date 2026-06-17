# Primitive Falsification

Baseline K+rho+A R2: `0.485879`.

| test | R2 | delta vs baseline | verdict |
| --- | --- | --- | --- |
| K replaced by Compatibility v2 | 0.483559 | -0.00232 | roughly redundant |
| K replaced by Route Friction | 0.489618 | 0.003739 | roughly redundant |
| rho removed | 0.465147 | -0.020733 | replacement loses signal |
| rho replaced by category one-hot proxy | 0.466896 | -0.018984 | roughly redundant |
| A removed | 0.469963 | -0.015917 | roughly redundant |
| A replaced by retrieval controls | 0.478799 | -0.00708 | roughly redundant |

Answers:

- Can K be replaced? Not cleanly. Compatibility v2 and Route Friction carry related reliability signal but are less primitive and more success-prior dependent.
- Does rho disappear under better measurement? Not proven. It weakens under controls but still marks model-task/repository affinity gaps.
- Does A vanish after retrieval controls? A changes form; clean retrieval controls absorb part of it, suggesting measurement redesign rather than elimination.
- Applying the same standard that rejected prior theories: K/rho/A survive provisionally, but only as measurement targets, not as finished formulas.
