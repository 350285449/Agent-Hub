# Agent-Hub Proofs

This directory is for local benchmark proof submitted by users.

Agent-Hub does not ask people to trust generic benchmark claims. It ships the
benchmark corpus so users can verify routing, cost, latency, and success in
their own repository.

## Submit a Proof

1. Run a local benchmark:

   ```sh
   agent-hub benchmark run --baseline claude-sonnet --route coding
   ```

2. Generate a share card or case study:

   ```sh
   agent-hub benchmark-card --variant markdown
   agent-hub generate-case-study --output docs/proofs/my-proof.md
   ```

3. Remove private repository names, paths, secrets, customer data, and prompts
   that should not be public.

4. Open a PR with the proof markdown, or post it in the `Share Your Benchmark`
   GitHub Discussion category.

## Recommended Fields

- Baseline model
- Task count
- Repository size
- Primary workflow
- Cost reduction
- Latency reduction
- Success-rate delta
- One route replay example
- Reproduction command

Use `proof-template.md` when writing a new proof by hand.
