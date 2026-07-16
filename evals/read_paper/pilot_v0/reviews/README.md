# Model Review Reports

This directory stores reproducible model-proxy audits of candidate reference
annotations. A report is supporting evidence, not a substitute for the human
sign-off required by `read-paper-reference/v1`. Model reviews therefore do not
populate `human_reviewer` or change a case from `draft` to `reviewed`.

## Current audit

Both reports were produced with Codex CLI 0.144.1, model `gpt-5.6-sol`, reasoning
effort `max`, an ephemeral session, and a read-only repository sandbox:

- `gpt-5.6-sol-max-vlfm.md`: `PASS_WITH_CORRECTIONS`
- `gpt-5.6-sol-max-palme.md`: `PASS_WITH_CORRECTIONS`

The shared and case-specific review contracts live in the parent directory.
