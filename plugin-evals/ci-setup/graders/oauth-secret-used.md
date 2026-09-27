---
type: regex
target: { source: file, path: .github/workflows/agent-evals-pr.yml }
pattern: "secrets\\.CLAUDE_CODE_OAUTH_TOKEN"
---

The user asked for the subscription, so the pr workflow must read the OAuth
token from a repository secret. A literal token or an API-key-only workflow
fails this.
