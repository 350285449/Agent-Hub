# Execution Science Assessment v3

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Final Answers

1. First predictive event: `first decisive evidence`.
2. Strongest predictive event: `first grounding event`.
3. Execution states that exist: stuck, converging, grounded, exploring, recovered. The state ranking is by predictive contribution, so `stuck` ranks first because it predicts failure, not because it is a good state.
4. Most important transition: `stuck -> exploring`.
5. Does grounding create convergence? Yes, in the operational sense: grounding usually appears no later than convergence among runs where both are observed, and grounded runs have materially higher success.
6. Can success be predicted after entering a grounded state? Yes diagnostically: success after grounding is 0.88755 versus 0.466368 without grounding.
7. Minimal execution model required for prediction: `grounding`.

## Ranked Event List

| rank | event | contribution |
| --- | --- | --- |
| 1 | first grounding event | 0.144538 |
| 2 | first decisive evidence | 0.037139 |
| 3 | first recovery event | 0.000268 |
| 4 | first successful tool call | 0.0 |
| 5 | first verification attempt | 0.0 |
| 6 | first verification success | 0.0 |
| 7 | first retrieval | -0.000261 |
| 8 | first branch collapse | -0.003139 |

## Ranked State List

| rank | state | contribution |
| --- | --- | --- |
| 1 | stuck | 0.043853 |
| 2 | converging | 0.007745 |
| 3 | grounded | 0.005191 |
| 4 | exploring | 0.004076 |
| 5 | recovered | 0.001277 |

## Ranked Transition List

| rank | transition | contribution |
| --- | --- | --- |
| 1 | stuck -> exploring | 0.026365 |
| 2 | grounded -> converging | 0.00466 |
| 3 | stuck -> converging | 0.002417 |
| 4 | exploring -> grounded | 0.002269 |
| 5 | stuck -> recovered | 0.000684 |
| 6 | exploring -> converging | 0.000524 |
| 7 | grounded -> recovered | -2.4e-05 |
| 8 | exploring -> stuck | -0.002094 |

## Smallest Feature Set Explaining Most Surviving Dynamic Assimilation Signal

The smallest recovered subset is `grounding`. In plain terms: detect decisive evidence, measure grounding latency, and confirm evidence-to-action conversion. That subset captures most of the surviving dynamic prediction signal without adding new primitive searches, new interaction laws, or a new theory zoo.
