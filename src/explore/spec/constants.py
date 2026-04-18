"""Spec rule parameters.

Kept in a dedicated module to avoid circular-import fragility.
See docs/onboard-redesign/07-spec-rules.md section "参数常量".
v1: hardcoded here. Future (OP-2 in 04-open-design-questions.md): move to yaml.
"""

# —— Budget defaults ——
TIME_BUDGET_SECONDS_DEFAULT = 900  # 15 min
ACTION_BUDGET_DEFAULT = 60
READ_PAPER_BUDGET_DEFAULT = 3

# —— Query quality thresholds ——
QUERY_DIVERSITY_THRESHOLD = 0.92  # cosine similarity ceiling
QUERY_DIVERSITY_WINDOW = 3
QUERY_WARMUP_POOL_SIZE = 50

# —— Saturation ——
SATURATION_RATIO_THRESHOLD = 0.10
SATURATION_WINDOW = 3

# —— Forced behaviors ——
FORCE_CLUSTER_REFRESH_DELTA = 15

# —— Deadlock thresholds ——
DEADLOCK_ESCALATE_THRESHOLD = 5
DEADLOCK_ABORT_THRESHOLD = 8
