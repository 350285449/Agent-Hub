# Context Complexity Index

Agent-Hub uses tau (τ) as an experimental context-complexity index. In the
current research layer, τ is estimated from a saturating context-success curve:

```text
S(x) = 1 - exp(-x / τ)
```

Where `x` is context tokens and `S(x)` is observed benchmark success rate.

## Why τ Matters

τ estimates how quickly additional context becomes useful. A smaller τ means a
repository reaches high success with fewer tokens. A larger τ suggests the
repository may need more context before routing or coding performance saturates.

## Estimation Method

Agent-Hub runs context ablation at 0%, 25%, 50%, 75%, and 100% budgets, groups
results by context bucket, and fits the saturating exponential curve by grid
search over τ. The exported fit includes τ, R², MSE, the best efficiency bucket,
and the first bucket where marginal gains decrease.

## Repository Metrics

The repository metrics layer collects:

- total LOC
- file count
- Python file count
- average file length
- max file length
- directory count
- estimated import count
- test file count
- approximate complexity score

The complexity score is a lightweight deterministic heuristic combining LOC,
code file count, import count, and test file count.

## Interpretation

Use τ as an early comparative signal, not a proof. If two repositories are tested
with the same benchmark harness, a higher τ suggests the second repository needs
more context for success to saturate. Correlation with repository metrics can
hint whether complexity, size, or dependency structure explains the context
need.

## Current Limitations

The current study uses deterministic local benchmark/proof execution. It does
not establish real model behavior, causal effects, or generality across broad
external corpora. Synthetic repositories are useful for test coverage but should
not be treated as evidence about production codebases.

## Next Step

Repeat the cross-repository experiment with real local models first, then with
explicitly budgeted cloud models, and compare τ stability across model families.
