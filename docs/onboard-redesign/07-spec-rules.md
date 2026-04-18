# Spec 规则层：DSL 与规则目录

> Explorer 的护栏层。Planner 自由提议 action → Spec 在运行时校验 → 放行 / 拦截 / 改写。
> 本文档是 spec 规则层的**权威参考**。

## 核心原则：硬性 / 弹性分工

> **Spec 只承担硬性不变量，Planner 负责所有弹性判断。**

- **硬性不变量**：能用数值比较、计数器、字段存在性、对象相等表达的事实
- **弹性判断**：方向选择、探索策略、语义合理性——全部交给 Planner（Pro，完整 context）
- **语义深审**：是否漂离 intent / 覆盖是否完整——交给 Coverage Audit（Pro，定期）
- **用户品味**：簇筛选 / 阈值调整——交给 Configure 阶段

**不在 Spec 层引入任何 LLM predicate**。原因：spec 的 LLM 不会强于 Planner，弱判断否决强判断在信息论上不合理。这条原则**永久性**，不是 v1 限制。

## DSL 形态选择：Python 类

AgentSpec（[arxiv 2503.18666](https://arxiv.org/abs/2503.18666)）用独立 DSL 文件 + ANTLR4 解析器。我们**不采用**：

- v1 只有 ~10 条规则，规则作者就是开发者自己
- Predicate 必然要读 state，天然是 Python 代码
- 引入 ANTLR 多一个学习成本

**决议：规则用 Python dataclass 表达，predicate 是纯函数**。保留 AgentSpec 的 **概念分工**（rule/trigger/check/enforce），不要它的 **形式主义**。

v3 若规则 > 50 或非开发者需编辑，可迁到 YAML（predicate 仍在 Python）。

## 核心模型

### Verdict

```python
VerdictKind = Literal["allow", "block", "rewrite", "warn", "force"]

@dataclass
class Verdict:
    kind: VerdictKind
    rule_name: str                              # 触发此 verdict 的规则
    feedback: Optional[str] = None              # 给 planner 的反馈
    rewritten_action: Optional[Action] = None   # kind == "rewrite"
    forced_action: Optional[Action] = None      # kind == "force"
    all_fired_rules: List[str] = field(default_factory=list)  # 所有 fire 过的规则名
```

**语义**：
- `allow`：通过，执行原 action
- `block`：拒绝，planner 收到 feedback 再提议
- `rewrite`：替换为 `rewritten_action` 执行
- `warn`：通过但记录警告（v1 不用）
- `force`：强制执行 `forced_action`（用于死锁 escape / 预算兜底）

### Predicate

```python
Predicate = Callable[[ExplorationState, Action], bool]
```

纯函数，**只读**。不修改 state，不调 LLM，不做 I/O。
Exception 处理由 `Rule.fail_policy` 声明（见下）。

### Rule

```python
@dataclass
class Rule:
    name: str                                   # unique，如 "query_diversity"
    description: str                            # 一句话解释
    applies_to: Optional[List[Type[Action]]] = None  # None = 任何 action
    predicates: List[Predicate] = field(default_factory=list)  # AND
    verdict_fn: Callable[[ExplorationState, Action], Verdict] = None
    severity: int = 0                           # 多规则 fire 时仲裁权重
    fail_policy: Literal["abort", "skip"] = "abort"  # predicate 抛错时
```

## Verdict 仲裁（多规则同时 fire）

```
1. 按 VerdictKind 的严厉度排（force > block > rewrite > warn > allow）
2. 同 kind 按 rule.severity（越大越先）
3. 同 severity 按 rule.name 字典序（稳定）
```

所有 fire 过的规则名记入 `winner.all_fired_rules`，便于 debug。

```python
VERDICT_KIND_SEVERITY = {"force": 4, "block": 3, "rewrite": 2, "warn": 1, "allow": 0}
```

## Action 等价判据

用于 `RULE_NO_REPEATED_EXACT_ACTION`。**严格结构等价**：同 action_type **且** args 全等，忽略 `reasoning`。

```python
def action_signature(action: Action) -> str:
    """Canonical signature, 忽略 reasoning，其他字段按字典序 JSON 序列化"""
    d = asdict(action)
    d.pop("reasoning", None)
    return f"{type(action).__name__}:{canonical_json(d)}"

def action_equal(a: Action, b: Action) -> bool:
    return action_signature(a) == action_signature(b)
```

语义相似（query 相近但非完全重复）由 `RULE_QUERY_DIVERSITY` 的 embedding cosine 覆盖，不要在这里重复。

## action_history 的记录约定

为了支持 `consecutive_blocked_actions` 等统计，所有 spec 交互都进 history：

```python
@dataclass
class ActionRecord:
    turn: int                                   # 只计执行过的 action
    action: Action                              # 实际"上手"的 action（rewrite 后的 B，不是原 A）
    was_executed: bool                          # block 时为 False
    original_proposed_action: Optional[Action] = None  # rewrite/force 时填原 A
    spec_verdict: VerdictKind
    spec_feedback: Optional[str]
    spec_rules_fired: List[str]                 # 全部 fire 过的规则
    executed_at: Optional[datetime]
    outcome: Literal["success", "skipped", "failed", "not_executed"]
    outcome_summary: str
    duration_ms: int
    llm_calls: List[LLMCallRecord]
```

- `block` → `was_executed=False`，action 字段记原提议
- `rewrite` → `was_executed=True`，action 字段是 rewritten，`original_proposed_action` 记原 A
- `force` → 类似 rewrite，action 字段是 forced，`original_proposed_action` 记原 A
- `allow` → `was_executed=True`，`original_proposed_action=None`

派生属性：

```python
@property
def consecutive_blocked_actions(self) -> int:
    count = 0
    for record in reversed(self.action_history):
        if not record.was_executed:
            count += 1
        else:
            break
    return count
```

## Predicate 异常策略

每条 rule 声明 `fail_policy`：

| 策略 | 行为 |
|---|---|
| `abort` | predicate 抛异常 → 整个 Explorer run 终止，记 bug 到 log 和 state |
| `skip` | predicate 抛异常 → 该 rule 视为不 fire，log warning 继续 |

默认 **`abort`**。硬性规则（budget / deadlock）必须 `abort`——它们的 bug 不能被静默吞掉。软性规则（diversity / specificity）可以 `skip`——bug 不会让 Explorer 跑飞，只是少了一道保护。

## 可复用 Predicate 库

`src/explore/spec/predicates/` 下按主题分文件：

```python
# predicates/budget.py
def budget_field_exceeded(used_field: str, limit_field: str) -> Predicate:
    def pred(state, action):
        return getattr(state.budget, used_field) >= getattr(state.budget, limit_field)
    return pred

# predicates/saturation.py
def pool_is_saturated(threshold: float, window: int) -> Predicate:
    def pred(state, action):
        return state.new_paper_ratio_last_n_rounds(window) < threshold
    return pred

# predicates/similarity.py
def query_too_similar_to_recent(threshold: float, window: int) -> Predicate:
    def pred(state, action):
        if not isinstance(action, SearchAction):
            return False
        return state.query_cosine_similarity_to_recent(action.query, window) > threshold
    return pred

# predicates/coverage.py
def coverage_incomplete() -> Predicate:
    def pred(state, action):
        return state.coverage_report is None or state.coverage_report.unanswered_count > 0

def no_coverage_on_record() -> Predicate:
    def pred(state, action):
        return state.coverage_report is None
    return pred

# predicates/counters.py
def consecutive_blocked_geq(n: int) -> Predicate:
    def pred(state, action):
        return state.consecutive_blocked_actions >= n
    return pred

def papers_since_refresh_geq(n: int) -> Predicate:
    def pred(state, action):
        return state.papers_since_last_cluster_refresh() >= n
    return pred

# predicates/structural.py
def action_equals_previous() -> Predicate:
    def pred(state, action):
        if not state.action_history:
            return False
        prev = state.action_history[-1]
        return prev.was_executed and action_equal(action, prev.action)
    return pred
```

## 参数常量（v1 硬编码，未来 yaml 化）

在 `src/explore/spec/rules.py` 顶部：

```python
# —— Budget defaults ——
TIME_BUDGET_SECONDS_DEFAULT = 900          # 15 min
ACTION_BUDGET_DEFAULT = 60
READ_PAPER_BUDGET_DEFAULT = 3

# —— Quality thresholds ——
QUERY_DIVERSITY_THRESHOLD = 0.92           # cosine
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
```

## v1 规则目录（11 条）

### A. 预算类（硬限制，fail_policy=abort）

```python
RULE_READ_PAPER_BUDGET = Rule(
    name="read_paper_budget",
    description="read_paper 最多 3 次/run",
    applies_to=[ReadPaperAction],
    predicates=[budget_field_exceeded("read_papers_used", "read_paper_budget")],
    verdict_fn=lambda s, a: Verdict(
        kind="block",
        rule_name="read_paper_budget",
        feedback=f"read_paper budget exhausted ({s.budget.read_papers_used}/{s.budget.read_paper_budget}). Consider skim_abstract or coverage_audit instead.",
    ),
    severity=10,
    fail_policy="abort",
)

RULE_TIME_BUDGET = Rule(
    name="time_budget_exhausted",
    description="超时后强制 coverage_audit",
    applies_to=None,
    predicates=[budget_field_exceeded("elapsed_seconds", "time_budget_seconds")],
    verdict_fn=lambda s, a: Verdict(
        kind="force",
        rule_name="time_budget_exhausted",
        feedback="Time budget exhausted. Forcing coverage_audit before stop.",
        forced_action=CoverageAuditAction(reasoning="forced by time_budget_exhausted"),
    ),
    severity=20,
    fail_policy="abort",
)

RULE_ACTION_BUDGET = Rule(
    name="action_budget",
    description="总 action 数上限",
    applies_to=None,
    predicates=[budget_field_exceeded("actions_used", "action_budget")],
    verdict_fn=lambda s, a: Verdict(
        kind="force",
        rule_name="action_budget",
        feedback="Action count budget exhausted. Forcing stop.",
        forced_action=StopAction(claimed_reason="budget_exhausted", reasoning="forced"),
    ),
    severity=20,
    fail_policy="abort",
)
```

### B. 探索质量类（软性，fail_policy=skip）

```python
RULE_QUERY_DIVERSITY = Rule(
    name="query_diversity",
    description="query 与最近 N 条太相似 → block",
    applies_to=[SearchAction],
    predicates=[query_too_similar_to_recent(QUERY_DIVERSITY_THRESHOLD, QUERY_DIVERSITY_WINDOW)],
    verdict_fn=lambda s, a: Verdict(
        kind="block",
        rule_name="query_diversity",
        feedback="Query too similar to recent searches. Try a different angle: target an under-explored cluster, use author/benchmark seeding, or lookup classics.",
    ),
    severity=5,
    fail_policy="skip",
)

RULE_QUERY_MUST_BE_SPECIFIC = Rule(
    name="query_must_be_specific_after_warmup",
    description="池子 > 50 篇后，search 必须定向",
    applies_to=[SearchAction],
    predicates=[
        lambda s, a: s.pool_size > QUERY_WARMUP_POOL_SIZE,
        lambda s, a: a.targeted_cluster_slug is None
                     and a.source_tag in ("llm_generated", "user_intent_rewrite"),
    ],
    verdict_fn=lambda s, a: Verdict(
        kind="block",
        rule_name="query_must_be_specific_after_warmup",
        feedback=(
            f"Pool has {s.pool_size} papers; broad searches no longer add value. "
            f"Target a specific cluster or use classic_lookup / benchmark_seeded source_tag."
        ),
    ),
    severity=5,
    fail_policy="skip",
)
```

### C. 终止条件类（硬性，fail_policy=abort）

```python
RULE_NO_PREMATURE_STOP_SATURATION = Rule(
    name="no_premature_stop_saturation",
    description="未饱和不许停",
    applies_to=[StopAction],
    predicates=[lambda s, a: not s.is_saturated],
    verdict_fn=lambda s, a: Verdict(
        kind="block",
        rule_name="no_premature_stop_saturation",
        feedback=(
            f"Not saturated yet. new_paper_ratio_last_{SATURATION_WINDOW}="
            f"{s.new_paper_ratio_last_n_rounds(SATURATION_WINDOW):.2f}, "
            f"target < {SATURATION_RATIO_THRESHOLD}. Keep exploring."
        ),
    ),
    severity=8,
    fail_policy="abort",
)

RULE_NO_PREMATURE_STOP_COVERAGE = Rule(
    name="no_premature_stop_coverage",
    description="覆盖未完成不许停",
    applies_to=[StopAction],
    predicates=[coverage_incomplete()],
    verdict_fn=lambda s, a: Verdict(
        kind="block",
        rule_name="no_premature_stop_coverage",
        feedback=(
            f"Coverage audit not passing. "
            f"Unanswered: {[q.question for q in (s.coverage_report.questions if s.coverage_report else []) if not q.answer_available]}. "
            "Run coverage_audit or fill gaps."
        ),
    ),
    severity=8,
    fail_policy="abort",
)
```

### D. 强制行为类（结构性，fail_policy=abort）

```python
RULE_FORCE_CLUSTER_REFRESH = Rule(
    name="force_cluster_refresh_on_pool_growth",
    description="池子自上次 refresh 后新增 ≥ 15 篇 → 强制聚类",
    applies_to=None,
    predicates=[
        lambda s, a: not isinstance(a, ClusterRefreshAction),
        papers_since_refresh_geq(FORCE_CLUSTER_REFRESH_DELTA),
    ],
    verdict_fn=lambda s, a: Verdict(
        kind="force",
        rule_name="force_cluster_refresh_on_pool_growth",
        feedback="Pool grew significantly; clustering view is stale. Refreshing first.",
        forced_action=ClusterRefreshAction(reasoning="forced by pool growth"),
    ),
    severity=15,
    fail_policy="abort",
)

RULE_REQUIRE_COVERAGE_AUDIT_BEFORE_STOP = Rule(
    name="require_coverage_audit_before_stop",
    description="没跑过 audit 却提 stop → 强制跑 audit",
    applies_to=[StopAction],
    predicates=[no_coverage_on_record()],
    verdict_fn=lambda s, a: Verdict(
        kind="rewrite",
        rule_name="require_coverage_audit_before_stop",
        feedback="No coverage audit on record. Running audit first.",
        rewritten_action=CoverageAuditAction(reasoning="rewritten from stop"),
    ),
    severity=9,
    fail_policy="abort",
)
```

### E. 防循环与死锁类（硬性，fail_policy=abort）

```python
RULE_NO_REPEATED_EXACT_ACTION = Rule(
    name="no_repeated_exact_action",
    description="和上一个 action 结构完全相同 → block",
    applies_to=None,
    predicates=[action_equals_previous()],
    verdict_fn=lambda s, a: Verdict(
        kind="block",
        rule_name="no_repeated_exact_action",
        feedback="This is structurally identical to your previous action. Try a different action type or different args.",
    ),
    severity=3,
    fail_policy="abort",
)

RULE_DEADLOCK_ESCALATE = Rule(
    name="deadlock_escalate",
    description="连续 5 次被 block → 强制 coverage_audit",
    applies_to=None,
    predicates=[consecutive_blocked_geq(DEADLOCK_ESCALATE_THRESHOLD)],
    verdict_fn=lambda s, a: Verdict(
        kind="force",
        rule_name="deadlock_escalate",
        feedback="Too many consecutive blocks. Running coverage_audit to re-orient.",
        forced_action=CoverageAuditAction(reasoning="forced by deadlock_escalate"),
    ),
    severity=18,
    fail_policy="abort",
)

RULE_DEADLOCK_ABORT = Rule(
    name="deadlock_abort",
    description="连续 8 次被 block → 终止（规则设计问题）",
    applies_to=None,
    predicates=[consecutive_blocked_geq(DEADLOCK_ABORT_THRESHOLD)],
    verdict_fn=lambda s, a: Verdict(
        kind="force",
        rule_name="deadlock_abort",
        feedback="Rule deadlock detected after 8 consecutive blocks. Aborting for inspection.",
        forced_action=StopAction(claimed_reason="budget_exhausted", reasoning="aborted by deadlock"),
    ),
    severity=25,   # 最高，压过所有其他规则
    fail_policy="abort",
)
```

## 规则注册与加载

`src/explore/spec/rules.py`：

```python
ALL_RULES: List[Rule] = [
    # A. 预算
    RULE_READ_PAPER_BUDGET,
    RULE_TIME_BUDGET,
    RULE_ACTION_BUDGET,
    # B. 质量
    RULE_QUERY_DIVERSITY,
    RULE_QUERY_MUST_BE_SPECIFIC,
    # C. 终止
    RULE_NO_PREMATURE_STOP_SATURATION,
    RULE_NO_PREMATURE_STOP_COVERAGE,
    # D. 强制
    RULE_FORCE_CLUSTER_REFRESH,
    RULE_REQUIRE_COVERAGE_AUDIT_BEFORE_STOP,
    # E. 死锁
    RULE_NO_REPEATED_EXACT_ACTION,
    RULE_DEADLOCK_ESCALATE,
    RULE_DEADLOCK_ABORT,
]
```

单文件，一眼看全。顺序不影响求值（按 severity 仲裁）。

## SpecEvaluator

```python
class SpecEvaluator:
    def __init__(self, rules: List[Rule]):
        self.rules = rules

    def evaluate(self, action: Action, state: ExplorationState) -> Verdict:
        fired: List[Tuple[Rule, Verdict]] = []

        for rule in self.rules:
            # 1. Trigger matching
            if rule.applies_to is not None:
                if not any(isinstance(action, t) for t in rule.applies_to):
                    continue

            # 2. Predicate evaluation (AND across predicates)
            try:
                if not all(p(state, action) for p in rule.predicates):
                    continue
            except Exception as e:
                if rule.fail_policy == "abort":
                    raise SpecPredicateError(rule.name, e) from e
                logger.warning(f"Rule {rule.name} predicate raised, skipping: {e}")
                continue

            # 3. Construct verdict
            fired.append((rule, rule.verdict_fn(state, action)))

        # 4. Arbitration
        if not fired:
            return Verdict(kind="allow", rule_name="__default__")

        fired.sort(key=lambda rv: (
            -VERDICT_KIND_SEVERITY[rv[1].kind],
            -rv[0].severity,
            rv[0].name,
        ))

        winner_rule, winner_verdict = fired[0]
        winner_verdict.all_fired_rules = [r.name for r, _ in fired]
        return winner_verdict


class SpecPredicateError(Exception):
    def __init__(self, rule_name: str, inner: Exception):
        self.rule_name = rule_name
        self.inner = inner
        super().__init__(f"Predicate of rule '{rule_name}' raised: {inner}")
```

`SpecPredicateError` 在主循环被捕获 → 落盘 state + 诊断信息 → 按 Q8 路径退出。

## 生命周期

- **实例化**：每次 Explorer run 开始时 `SpecEvaluator(ALL_RULES)`
- **不持状态**：evaluator 本身无状态（状态在 ExplorationState），多次 evaluate 互不影响
- **销毁**：run 结束即释放，下一 run 新建

## 测试策略

规则层是整个项目**最应该 100% 单测**的地方——predicate 和 verdict_fn 都是纯函数。

```python
def test_read_paper_budget_blocks_at_limit():
    state = make_state(read_papers_used=3, read_paper_budget=3)
    action = ReadPaperAction(arxiv_id="2401.00001", reasoning="test")
    verdict = SpecEvaluator([RULE_READ_PAPER_BUDGET]).evaluate(action, state)
    assert verdict.kind == "block"
    assert "exhausted" in verdict.feedback

def test_read_paper_budget_allows_below_limit():
    state = make_state(read_papers_used=2, read_paper_budget=3)
    action = ReadPaperAction(arxiv_id="2401.00001", reasoning="test")
    verdict = SpecEvaluator([RULE_READ_PAPER_BUDGET]).evaluate(action, state)
    assert verdict.kind == "allow"

def test_arbitration_deadlock_abort_beats_block():
    state = make_state(consecutive_blocks=8, is_saturated=False)
    action = StopAction(claimed_reason="saturated", reasoning="test")
    rules = [RULE_NO_PREMATURE_STOP_SATURATION, RULE_DEADLOCK_ABORT]
    verdict = SpecEvaluator(rules).evaluate(action, state)
    assert verdict.rule_name == "deadlock_abort"
    assert verdict.kind == "force"
    assert "no_premature_stop_saturation" in verdict.all_fired_rules

def test_predicate_abort_policy_raises():
    bad_rule = Rule(
        name="buggy", description="...", applies_to=None,
        predicates=[lambda s, a: s.nonexistent_field],
        verdict_fn=lambda s, a: Verdict(kind="block", rule_name="buggy"),
        fail_policy="abort",
    )
    with pytest.raises(SpecPredicateError):
        SpecEvaluator([bad_rule]).evaluate(SearchAction(...), make_state())

def test_predicate_skip_policy_silent():
    bad_rule = Rule(
        name="buggy", description="...", applies_to=None,
        predicates=[lambda s, a: s.nonexistent_field],
        verdict_fn=lambda s, a: Verdict(kind="block", rule_name="buggy"),
        fail_policy="skip",
    )
    verdict = SpecEvaluator([bad_rule]).evaluate(SearchAction(...), make_state())
    assert verdict.kind == "allow"  # 规则被跳过
```

目标：**spec 规则层单测覆盖率 ≥ 95%**。

## 规则演进路径

v1 落地后每轮迭代：

1. 收集每条规则的 fire 频次 + 最近 10 次 Explorer run 的 trace
2. **高频 fire + LLM 立即修正** → 规则有效，feedback 清晰
3. **高频 fire + LLM 反复撞墙** → feedback 措辞不够具体，改进
4. **零 fire 的规则** → 考虑放宽或移除
5. **LLM 做傻事但无规则拦** → 新增规则
6. v2 实验：用 Pro/o1 读 trace 自动提议新规则（AgentSpec 论文验证 95% precision 可行）

## Future work（v1 不做）

- **OP-2 参数 YAML 化**：若常调整参数（如 QUERY_DIVERSITY_THRESHOLD），把模块常量迁到 `config.spec.*`。规则定义结构不变。
- **OP-3 观察模式**：给 Rule 加 `mode: Literal["enforce", "observe"]`，observe 下 verdict 降级为 warn，用于灰度上线新规则。
- **规则自动生成**：用 LLM 从 Explorer trace 提议新规则，人工审核后入库。
- **规则热重载**：v1 每 run 实例化一次 Evaluator 足够；若 run 跨越数小时且需改规则，再加热重载能力。

## 永不做的（架构约束）

- **LLM predicate**：见顶部"核心原则"。不开后门。
- **Spec 修改 state**：Enforcement 只产 verdict，不写 state。State 变更只发生在 Action Executor。
- **Spec 发起 LLM 调用**：spec 是同步纯函数层，不应有任何 I/O。
