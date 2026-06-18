# Schema Failure Breakdown

| schema/parser error | count | category |
| --- | ---: | --- |
| events[0].phase mismatch | 31 | parser/schema mismatch |
| events[1].phase mismatch | 31 | parser/schema mismatch |
| json_decode | 30 | malformed JSON |
| events[2].unexpected_keys | 13 | parser/schema mismatch |
| missing_required_events | 2 | missing required fields |
| events[0].local_grounding outside_0_1 | 2 | invalid field types |
| events[1].local_grounding outside_0_1 | 2 | invalid field types |
| events[2].local_grounding outside_0_1 | 2 | invalid field types |
| pre_commit_final_answer_disallowed | 2 | parser/schema mismatch |
| events[5].phase mismatch | 2 | parser/schema mismatch |
| events[5].local_grounding outside_0_1 | 1 | invalid field types |
| events[2].missing_keys | 1 | missing required fields |
| events[0].unexpected_keys | 1 | parser/schema mismatch |
