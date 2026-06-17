# Task Family Signal Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Family Timing Results

| family | window | rows | prospective rows | holdout R2 | prospective R2 | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| coding | pre-run | 723 | 37 | 0.518864 | 0.0 | family-specific calibration required |
| coding | during execution | 723 | 37 | 0.514105 | 0.0 | family-specific calibration required |
| coding | post-run diagnostic | 723 | 37 | 0.725707 | 0.0 | family-specific calibration required |
| reasoning | pre-run | 165 | 30 | 0.062677 | 0.035848 | family-specific calibration required |
| reasoning | during execution | 165 | 30 | 0.04632 | 0.013962 | family-specific calibration required |
| reasoning | post-run diagnostic | 165 | 30 | 0.225674 | 0.067707 | family-specific calibration required |
| research | pre-run | 0 | 0 | n/a | n/a | insufficient cloud rows |
| research | during execution | 0 | 0 | n/a | n/a | insufficient cloud rows |
| research | post-run diagnostic | 0 | 0 | n/a | n/a | insufficient cloud rows |
| agentic | pre-run | 30 | 0 | 0.351924 | 0.0 | underpowered; do not generalize |
| agentic | during execution | 30 | 0 | 0.339656 | 0.0 | underpowered; do not generalize |
| agentic | post-run diagnostic | 30 | 0 | 0.571534 | 0.0 | underpowered; do not generalize |

## Assessment By Family

Coding tasks show execution sensitivity because file selection, edits, and verifier behavior determine success after the prompt is already known.

Reasoning tasks preserve some pre-run stratification, but the decisive signal still depends on whether the model connects evidence to the final argument.

Research tasks are not estimable in the current cloud-only aligned corpus: this pass has zero rows classified as research. The program should collect a balanced research slice before making a family-specific claim there.

Agentic tasks are the least viable for broad pre-run prediction because action sequencing, tool use, and recovery behavior are execution-stage phenomena.

## Family-Specific Prediction

Family-specific prediction is viable only as bounded calibration, not as a general science yet. Each family needs separate base rates, separate uncertainty budgets, and balanced frozen cloud-only panels.
