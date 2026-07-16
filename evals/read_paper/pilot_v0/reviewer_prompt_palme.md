# PaLM-E Independent Model Review

Read and follow `evals/read_paper/pilot_v0/reviewer_prompt.md`, with the following
scope override: audit only
`evals/read_paper/pilot_v0/cases/2303.03378v1.yaml`, its frozen local PDF, and its
frozen raw TeX source.

All independence, primary-source, severity, ledger, and no-edit rules in the base
contract remain binding. References in the base contract to two cases and 38
records are replaced for this invocation by this one case and all 20 of its
experiment records. Still audit every evidence entry, claim, method component,
limitation, ambiguity, and coverage item, and check for material omissions. Use
the raw TeX to verify dense table structure and the rendered PDF where visual
grouping matters.

Return the complete Markdown report for this case only.
