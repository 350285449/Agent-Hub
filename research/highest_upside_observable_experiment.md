# First Experiment: Viable Reachability Delta

Date: 2026-06-19

## Goal

Measure Viable Reachability Delta directly in a 20-50 row pilot.

## Target Size

30 rows.

Minimum useful range: 20-50 rows.

## Task Mix

Use tasks where intermediate state can be inspected:

- 10 coding/debugging tasks;
- 10 web or OS-style navigation tasks;
- 10 information/research tasks with verifiable constraints.

## Row Schema

Each row records one agent run.

| Field | Type | Meaning |
| --- | --- | --- |
| `row_id` | string | unique row |
| `task_family` | enum | coding, web_os, research |
| `model_family` | string | model used |
| `step_id` | integer | transition index |
| `state_summary_before` | text | compact observable state before transition |
| `action_or_observation` | text | transition content |
| `state_summary_after` | text | compact observable state after transition |
| `remaining_budget_before` | number | steps/tool calls/tokens left |
| `remaining_budget_after` | number | steps/tool calls/tokens left |
| `viable_routes_before` | integer 0-5 | estimated count of distinct viable routes |
| `viable_routes_after` | integer 0-5 | estimated count after transition |
| `min_completion_cost_before` | integer | estimated cheapest remaining steps |
| `min_completion_cost_after` | integer | estimated cheapest remaining steps |
| `reversibility_after` | enum | reversible, costly, irreversible |
| `feedback_used` | boolean | whether transition used feedback/evidence |
| `valid_coupling` | boolean | whether action was constrained by valid observed evidence |
| `vrd` | number | computed delta |
| `terminal_success` | boolean | final outcome |

## VRD Calculation

Simple pilot score:

```text
reachability_score =
  viable_routes
  - 0.25 * min_completion_cost
  - reversibility_penalty
```

Where:

```text
reversibility_penalty:
  reversible = 0
  costly = 1
  irreversible = 2
```

Then:

```text
VRD_t = reachability_score_after - reachability_score_before
```

## Procedure

1. Freeze 30 tasks and a maximum budget per task.
2. Run one agent per task with full trace logging.
3. Segment each run into observable transitions.
4. Score the first 5-8 transitions per row, plus any feedback/repair transition and final pre-terminal transition.
5. Use two independent raters or verifier prompts for reachability fields.
6. Resolve disagreements only after preserving raw scores.
7. Compute VRD summaries per row:
   - mean VRD;
   - minimum VRD;
   - first negative VRD step;
   - first positive repair rebound;
   - cumulative VRD before commitment/lock-in.
8. Compare VRD summaries against terminal success and existing labels such as GAR, commitment, and regime if available.

## Pass Criteria

VRD is worth expanding if:

- coverage >= 85% of targeted transitions;
- inter-rater agreement >= 0.65 weighted kappa or equivalent;
- successful rows have higher cumulative early VRD than failures;
- negative VRD precedes terminal failure in at least 60% of failed rows;
- repair rebounds predict recovery better than feedback presence alone.

## Kill Criteria

Stop treating VRD as high-upside if:

- raters cannot reliably distinguish viable routes;
- VRD mostly duplicates step count or task family;
- VRD can only be scored using outcome knowledge;
- positive and negative VRD have no relationship to success, repair, commitment, or grounding;
- the metric collapses into subjective "looks good" labels.

## Smallest Useful Table

At 30 rows, record one row-level summary table:

| row_id | family | success | early_cum_vrd | min_vrd | first_negative_step | repair_rebound | feedback_present | valid_coupling_rate | mean_reversibility |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |

This is enough to detect whether VRD has signal before building a larger pipeline.
