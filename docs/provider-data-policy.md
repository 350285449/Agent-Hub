# Provider Data Policy

Provider routing must avoid sending private workspace, secret-like content, or
untrusted tool output to providers that are not allowed for that data category.

## Categories

- `public`: safe prompts and public repository context.
- `workspace`: local source, logs, tests, and diagnostics.
- `secret`: credentials, tokens, private keys, and secret-like values.
- `regulated`: user-marked sensitive or compliance-bound data.

Provider policy should combine provider trust level, approval mode, data
category, and route intent before allowing a request.
