# Agent Measurement Blind-Spot Audit

Date: 2026-06-19

Scope: modern agent research measurements, with emphasis on observables actually collected rather than theories.

## Summary

Agent research mostly measures terminal success and coarse resource use. It often records traces, but it does not usually convert traces into measurements of how each step changes the reachable task state-space.

The common measured variables are:

- task success / pass rate / score;
- step count, rounds, actions, tool calls, tokens, latency, cost;
- benchmark category, task family, model family;
- final patch/test correctness or functional completion;
- search breadth/depth in methods that explicitly search;
- self-rated or verifier-rated intermediate candidates in some planning systems;
- human intervention rate and autonomy proxies in deployed-agent studies.

The systematic blind spot is:

```text
Per-transition change in viable reachable futures under remaining resources.
```

This includes whether an action opens, closes, compresses, damages, or preserves the set of routes by which the agent can still complete the task.

## Audit Table

| System | Variables measured | Variables not measured |
| --- | --- | --- |
| ReAct | Success on QA / decision tasks, reasoning-action traces, observations, comparison against CoT/Act baselines. | Whether each observation/action increases viable reachability; transition reversibility; repair cost after bad observations; branch topology; whether reasoning updates are actually assimilated into future action constraints. |
| Tree of Thoughts | Task success, number of generated thoughts, search width/depth, value estimates or votes, cost of sampling, backtracking/search path. | Topological quality of explored tree; viable-state expansion vs decorative branching; irreversible commitment points; whether rejected branches contain repair paths; state-space compression rate. |
| LATS | Task success across coding, web, QA, math; MCTS rollouts; LM value estimates; self-reflections; environment feedback; pass@1 / average score. | Whether tree search changes reachable environmental states; value-estimate calibration to true recoverability; transition reversibility; branch merge/split structure; feedback assimilation efficiency. |
| Reflexion | Success across trials, pass@1 / accuracy, improvement after feedback, ablations over feedback type/source, memory/reflection use. | Whether feedback changes the next transition rather than just text; repair efficiency per feedback item; stale or harmful memory effects; feedback-to-action assimilation lag; reversibility of failed trials. |
| SWE-bench | Resolved/pass rate, generated patch correctness via tests, issue/repo metadata, sometimes token/tool cost and leaderboard scores. | Search path through codebase; patch irreversibility; repair cost after failed edit; state-transition graph of hypotheses/files/tests; whether test feedback narrows viable fixes or merely triggers retry. |
| AgentBench | Per-environment success, F1/reward/win metrics, rounds, step success for web tasks, invalid/repeated action failures. | Cross-step reachability; action-level damage to future options; resource burn relative to remaining task topology; branch switching; coupling between observation and action. |
| WebArena | End-to-end task success, functional correctness, human-vs-agent success, action traces in realistic websites. | Whether each click/form action expands or collapses completion paths; reversibility after navigation errors; information-foraging efficiency; latent state graph of website progress. |
| OSWorld | Execution-based task success, initial state setup, scripts for reproducible evaluation, human-vs-agent performance, GUI grounding failure categories. | GUI-state transition topology; operational knowledge as recoverability; cost to undo wrong GUI actions; per-app state-space compression; action-induced damage to remaining viable routes. |
| Anthropic agent work | Turn duration, human intervention count, auto-approval, task success, task complexity/value, work category, user expertise, autonomy in practice. | Causal transition quality inside sessions; whether fewer interventions preserve or reduce recoverability; repair gradient after user steering; branching and reversal cost of autonomous edits. |
| OpenAI reasoning / agentic coding work | Benchmark scores such as SWE-bench Verified, Aider, MultiChallenge, tool-call rates, output tokens, reasoning effort, latency/cost tradeoffs. | Internal transition graph; effect of reasoning effort on viable reachability rather than final score; transition damage; branch-collapse timing; tool-call value per reachable future gained. |
| DeepMind planning / agent work | Automated evaluator score, objective quality, verifier result, inference-time compute scaling, autonomous/human-assisted discoveries, generated candidate quality. | Search-space topology as a causal object; how verification changes reachable proof/program space; repair/restart efficiency; transition reversibility; difference between broad exploration and viable-state expansion. |

## Source Anchors

- ReAct interleaves reasoning traces and actions, with actions producing observations and reasoning updating internal context: https://arxiv.org/abs/2210.03629 and https://research.google/blog/react-synergizing-reasoning-and-acting-in-language-models/
- Tree of Thoughts reports large success gains on planning/search tasks such as Game of 24 and explicitly explores multiple reasoning paths: https://arxiv.org/abs/2305.10601
- LATS integrates MCTS, value functions, self-reflection, and external feedback, reporting pass@1 / score improvements across domains: https://proceedings.mlr.press/v235/zhou24r.html
- Reflexion reports success improvements from verbal feedback and memory, including HumanEval pass@1: https://arxiv.org/abs/2303.11366
- SWE-bench evaluates issue resolution via patches passing tests: https://www.swebench.com/original.html
- AgentBench reports success rate, reward, F1, win rate, rounds, and step success depending on environment: https://arxiv.org/html/2308.03688v3
- WebArena focuses on functional correctness and end-to-end task success: https://arxiv.org/abs/2307.13854
- OSWorld uses execution-based evaluation scripts and reports task success in real computer environments: https://arxiv.org/abs/2404.07972
- Anthropic measures autonomy in practice through turn duration, interventions, auto-approval, success, task composition, and expertise: https://www.anthropic.com/research/measuring-agent-autonomy and https://www.anthropic.com/research/claude-code-expertise
- OpenAI reports reasoning/agentic performance with benchmark score, token, tool-call, and efficiency metrics: https://openai.com/index/introducing-gpt-5-for-developers/
- DeepMind reports automated evaluator scores, verifier/reviser loops, inference-time compute scaling, and research outcomes: https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/ and https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/

## Ruthless Conclusion

The blind spot is not lack of traces. The blind spot is that traces are rarely converted into transition observables. Current research asks, "Did the agent finish?" and sometimes "How many steps did it take?" It rarely asks, "After this exact step, how many viable futures still existed, how costly were they, and did the agent know how to move toward them?"
