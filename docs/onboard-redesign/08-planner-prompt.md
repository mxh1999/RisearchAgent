# Planner Prompt 与测试

> Explorer 的"大脑"层。Planner 读 ExplorationState，产出下一个 action 的 JSON。
> 本文档定义 prompt 结构、输入/输出契约、质量要求、测试方法。

## 设计目标

**单一目标**：读当前 state，产出一个 JSON action，推进 exploration 向停止条件收敛。

**附属要求**：
- Action 必须符合 06 定义的 9 种之一，通过 pydantic schema
- `reasoning` 引用 state 里的具体证据（slug / arxiv_id / benchmark / 数值）
- 不捏造 ID（arxiv_id / cluster_slug 必须来自 state）
- 被 spec block 后读 feedback 调整，不硬刚

**Planner 不负责**：
- 最终 field_map 合成（Synthesize 阶段）
- 聚类算法（Clusterer）
- 规则执行（Spec）
- "是否该停"的最终判断（提 StopAction 由 spec 验）

## 模型与参数

- **模型**：Gemini 2.5 Pro（`llm_tier=production`）/ Flash（`budget`）/ Flash（`dev`）
- **Temperature**：使用 Gemini 默认，不显式设置。结构化输出由 `response_schema` 保证，query 多样性靠 prompt 引导而非温度
- **JSON 模式**：`response_mime_type: "application/json"` + `response_schema` 绑定 action 的 discriminated union

## Prompt 结构

分两部分，利用 Gemini 的 prompt cache：

### 系统级（稳定，每轮复用）
1. 身份与原则
2. Action 目录（9 种 + example + 误用反例）
3. 输出契约（JSON schema + reasoning 规范）
4. Spec 规则要点（不是全文）

### 动态级（每轮重算）
- Intent / Budget / Cluster snapshot / Counters / Saturation / Coverage / Recent history / Spec feedback

## 系统 Prompt 模板

```markdown
# You are the Explorer Planner

You are the decision-making component of an autonomous research Explorer.
Your job is to propose the next action that advances the exploration of a
research field toward a complete, well-evidenced field map.

## Your Operating Context

- The Explorer is surveying a research field based on a user's intent.
- You run for ~10-15 minutes with a fixed budget.
- Your output directly drives the next tool call (search, fetch, read, etc).
- A separate layer (Spec) validates your proposals; if blocked, you'll see
  feedback and must adjust.

## Your Principles

1. **Breadth first.** 100-300 abstracts surveyed before any deep read.
2. **Evidence over intuition.** Every action must cite specific state evidence.
3. **Structure reveals itself.** Let clustering show sub-areas; don't force
   the user's intent into preset categories.
4. **Don't waste deep reads.** read_paper is capped at 3/run. Use it only on
   hub papers whose benchmarks are ambiguous.
5. **Stop when saturated.** Pool growth < 10% over last 3 rounds + coverage
   audit passing = ready to stop.

## Available Actions

### search
Issue an ArXiv query. Use for broad exploration early, or targeted deepening
of a specific cluster/time-range later.
- Good: `search(query="SLAM classical baselines", date_range=("2018","2021"),
  source_tag="classic_lookup")` — targeting a cluster lacking classics
- Bad: `search(query="navigation")` when pool is 87 papers — too broad,
  spec will block.

### search_by_author
Structured search by author. Use when an author dominates a cluster and you
want their other work.
- Good: `search_by_author(author_name="Wang L.", max_results=10)` after
  noticing Wang appears in 8/22 papers of cluster vln-ce.

### fetch_citations
Expand from a seed paper via its references or citations (Semantic Scholar).
- `direction="references"`: find classic papers this one cites (backward)
- `direction="cited_by"`: find recent work building on it (forward)
- Good: on a high-citation seed to find classic baselines.

### fetch_related
Semantic Scholar's recommendation endpoint for a paper.
- Good: when a single paper captures the focus well and you want peers.

### cluster_refresh
Re-cluster the pool. Use when pool grew significantly since last refresh
(≥10 new papers) or when cluster assignments feel stale.
- Note: forced automatically by spec after +15 papers.

### skim_abstract
Run a Flash pass on a paper's abstract to extract benchmarks/methods.
- Good: target noise papers or cluster edges to understand them.

### read_paper
Full 3-pass deep read (expensive, 3/run limit).
- Good: on a cluster's centroid when its shared_benchmarks is empty.
- Bad: on a paper you already skimmed and has clear benchmarks.

### coverage_audit
Run a self-audit: can you answer the coverage questions from current state?
- Run before proposing `stop`. Also useful when feeling stuck.

### stop
Request termination. Spec will validate:
- Pool must be saturated (new_paper_ratio < 10% over last 3 rounds)
- Coverage report must have unanswered_count == 0
- Otherwise blocked.

## Output Contract

Output strictly valid JSON matching this schema:

{
  "action_type": "<one of: search, search_by_author, fetch_citations,
                   fetch_related, cluster_refresh, skim_abstract,
                   read_paper, coverage_audit, stop>",
  "args": { ... action-specific ... },
  "reasoning": "<2-4 sentences>"
}

### Reasoning Quality Rules

Your `reasoning` MUST include:
1. A specific observation from state (cluster slug, arxiv_id, benchmark name,
   or a numeric value like pool_size / saturation / cluster.size)
2. What gap or opportunity this observation reveals
3. Why your chosen action addresses it

**Good reasoning example:**
> "Cluster vln-ce has size=12 but year_range=[2023, 2025], missing classics.
> Searching for 2019-2021 VLN baselines targets this gap via classic_lookup."

**Bad reasoning examples (DO NOT produce):**
> "I think we should explore more."           [no evidence]
> "This seems like a good direction."         [no grounding]
> "Continuing the exploration."                [no specific gap]

## Spec Constraints You Should Know

- Per-action: no duplicate of previous action; queries must differ from last 3
- Budget: read_paper ≤ 3/run; total actions ≤ 60; total time ≤ 15 min
- Warmup: after pool > 50, search must be targeted (cluster/author/benchmark)
  or use source_tag ∈ {classic_lookup, benchmark_seeded}
- Stop: requires saturation + coverage audit passing
- Deadlock: 5 consecutive blocks → forced coverage_audit; 8 → abort

When you see a Verdict feedback in the dynamic context, it describes which
rule blocked/rewrote your previous proposal. Read it and adjust.
```

## 动态 Prompt 渲染

每轮拼装如下块：

```markdown
## Last Verdict (only if previous was blocked/rewritten)

Your previous proposal was **{kind}** by rule `{rule_name}`.
Feedback: {feedback}
{if rewritten: the rewritten action that actually ran was: ...}

## User Feedback (only if --feedback)

{feedback text}

## Intent

{natural_language}

Seed papers: {list of (arxiv_id, title, match_score, used_as_anchor)}

## Budget

| Field | Used | Limit |
|---|---|---|
| Elapsed | {elapsed_seconds}s | {time_budget_seconds}s |
| Actions | {actions_used} | {action_budget} |
| read_paper | {read_papers_used} | {read_paper_budget} |
| Pool size | {pool_size} | — |

## Saturation

new_paper_ratio over last {SATURATION_WINDOW} rounds: {value:.2f}
Target: < {SATURATION_RATIO_THRESHOLD} to satisfy stop condition.

## Cluster Snapshot (generated after turn {n})

| slug | size | year_range | top benchmarks | representative |
|---|---|---|---|---|
| {slug} | {size} | {yr_min}-{yr_max} | {top2 benchmarks} | {arxiv_id}: {title} |
| ... |

Noise: {n_noise} papers (representatives: {arxiv_ids})

## Counters (top 10 each)

**Benchmarks:** HM3D (37), R2R (28), RxR (14), ...
**Authors:** Wang L. (12), Chen S. (9), ...
**Years:** 2024 (52), 2023 (38), 2022 (21), ...

## Coverage Report {generated_at}

| Question | Answered? | Gap |
|---|---|---|
| {question} | {bool} | {gap if any} |
...

Unanswered: {count}

## Recent Action History (last 10)

1. [turn {n}] {action_type}({compact_args}) → {outcome_summary}
   Verdict: {verdict}
...

## Task

Propose the next action as JSON.
```

## 渲染细节

### Cluster 行格式

- `slug`：原样（如 `zero-shot-objnav`）
- `size`：论文数
- `year_range`：`[2022, 2025]` → `2022-2025`
- `top benchmarks`：从 `shared_benchmarks` 取前 2
- `representative`：1 个代表论文的 `arxiv_id: title` 截断到 80 字符

### Counter 格式

按 count 降序取 top 10，格式 `{name} ({count})`，其余 `(and N more)` 省略。

### Recent history 压缩

`compact_args` 规则：
- `search`: `query` + `source_tag`，若有 `targeted_cluster_slug` 也带上
- `fetch_citations`: `arxiv_id` + `direction`
- `read_paper`: `arxiv_id`
- `stop` / `coverage_audit` / `cluster_refresh`: 无 args

### Spec feedback 样式

block/rewrite 时置顶，用 ⚠️ 图标和 markdown heading 级别吸引注意：

```markdown
## ⚠️ Last Verdict: BLOCKED

**Rule:** `query_diversity`
**Feedback:** Query too similar to recent searches. Try a different angle:
target an under-explored cluster, use author/benchmark seeding, or lookup classics.

## ⚠️ All Rules That Fired: `query_diversity`, `query_must_be_specific_after_warmup`
```

**"All Rules That Fired"** 同时展示所有 fire 过的规则（不只是仲裁胜出的那条），让 planner 知道它踩了哪些线。

## JSON Schema（pydantic 定义）

见 06-action-system.md。关键点：

- Discriminated union 以 `action_type` 为 tag
- `response_schema` 强制输出必须符合
- `reasoning` 字段非空且 ≥ 30 字符（软限制，pydantic 校验）

## Prompt 缓存策略

Gemini 支持显式 prompt caching：

- **Cached** 部分：系统 prompt（身份 + action 目录 + 输出契约 + spec 要点）
  - 大小 ~3–5k token
  - TTL：单次 Explorer run 足够（~15 分钟），每 run 重建一次缓存
- **Non-cached** 部分：动态上下文
  - 大小 ~2–4k token/轮

单次 Pro 调用输入成本（缓存生效）≈ 系统部分 × 0.1 + 动态部分 × 1。粗估一轮 $0.01–0.03。

## Prompt Testing

Planner 是**非确定性**组件，需要与 Spec 不同的测试范式。

### 三档测试

| 档 | 性质 | 覆盖 | 运行频率 |
|---|---|---|---|
| **T1 结构化断言** | 确定性 | JSON schema 合法 / 无 hallucinated ID / args 合法 | 每次 PR |
| **T2 行为期望** | 概率性 N 次 | "预算用尽时不提 read_paper"、"池>50 时不提 broad search" | 手动 / nightly |
| **T3 回归场景** | 概率性 + 人工 | 刁钻 state 的退化监测 | release 前 |

### 文件组织

```
tests/explore/planner/
├── fixtures/
│   ├── initial_zero_shot.py         # 冷启动
│   ├── pool_50_no_classics.py       # warmup 边界
│   ├── saturated_no_audit.py        # 应 rewrite 为 audit
│   ├── deadlock_5_blocks.py         # 应走 deadlock_escalate
│   ├── off_topic_drift.py
│   ├── budget_exhausted_read.py
│   ├── cluster_without_benchmarks.py
│   └── ...
├── test_planner_schema.py           # T1，@pytest.mark.fast
├── test_planner_behavior.py         # T2，@pytest.mark.llm
├── test_planner_regression.py       # T3，@pytest.mark.llm_expensive
├── runners.py                       # run_n_times / assert_pass_rate
└── conftest.py
```

### Fixture 设计规则

- **人工构造**：每个 fixture 是 Python 文件，返回 `ExplorationState` 对象
- **最小完备**：只填该场景下 planner 应看见的字段，其余 placeholder
- **不变**：fixture 一旦确定不改；prompt 变 → 看对同一 fixture 输出如何变
- **命名**：`{状态描述}_{期望行为}.py`，便于索引

### Pass rate 阈值（**v1 占位，实践中校准**）

```python
# T2 默认阈值，跑过 3-5 次真实 Explorer 后校准
HARD_ERROR_PASS_RATE = 1.0       # spec 硬违规 = 绝不
STRONG_PREFERENCE_RATE = 0.7     # 强方向偏好
WEAK_PREFERENCE_RATE = 0.5       # 弱偏好
```

这些是**起点**，真实数据到手后调整。若某测试实际 pass rate 反复在 0.4–0.6 徘徊，**不要降阈值**——要么改 prompt，要么这个行为本就不该被断言。

### 测试样例

```python
# T1 —— 确定性
def test_schema_valid(all_fixtures):
    for fix in all_fixtures:
        raw = planner.propose(fix.state)
        action = parse_action(raw)   # 抛错即失败
        assert action is not None

def test_no_hallucinated_arxiv_id(all_fixtures):
    for fix in all_fixtures:
        action = parse_action(planner.propose(fix.state))
        for aid in extract_arxiv_ids(action):
            assert aid in fix.state.paper_pool

# T2 —— 概率性
@pytest.mark.llm
def test_budget_exhausted_avoids_read_paper():
    fix = load("budget_exhausted_read.py")
    actions = run_n_times(fix, n=5)
    assert_pass_rate(actions,
                     lambda a: not isinstance(a, ReadPaperAction),
                     HARD_ERROR_PASS_RATE)

@pytest.mark.llm
def test_pool_50_prefers_specific_search():
    fix = load("pool_50_no_classics.py")
    actions = run_n_times(fix, n=10)
    specific = lambda a: (isinstance(a, SearchAction) and (
        a.targeted_cluster_slug is not None
        or a.source_tag in ("classic_lookup", "benchmark_seeded")
    ))
    assert_pass_rate(actions, specific, STRONG_PREFERENCE_RATE)

@pytest.mark.llm
def test_missing_classics_proposes_classic_lookup():
    fix = load("cluster_without_classics.py")
    actions = run_n_times(fix, n=10)
    classic = lambda a: (isinstance(a, SearchAction)
                         and a.source_tag == "classic_lookup")
    assert_pass_rate(actions, classic, WEAK_PREFERENCE_RATE)

# T3 —— 回归
@pytest.mark.llm_expensive
def test_regression_snapshot(all_fixtures, regression_dir):
    for fix in all_fixtures:
        actions = run_n_times(fix, n=5)
        save_regression(fix.name, actions, regression_dir)
    # 不直接断言，人工 diff 上次 snapshot
```

### 成本

- T1 用 Flash tier 足够（schema 层不依赖推理质量）—— ~$0.01/PR
- T2 必须 Pro —— ~$0.5–1/次触发
- T3 必须 Pro —— ~$1–3/release

T1 默认 CI 跑，T2/T3 `pytest -m llm` 手动 / nightly。

### Fixture 演进原则

- **不改旧 fixture**（测试稳定性）
- 新场景 → 新 fixture
- 若 fixture 行为在 prompt 改后"预期地"退化 → 写解释 + 更新 threshold，但**不删 fixture**
- Fixture 总数增长到 30+ 时考虑按类别分目录

## 初始 Fixture 目录（实装时起点）

| Fixture | 场景 | 期望行为 |
|---|---|---|
| `initial_zero_shot` | 空 pool，只有 intent | 提议 broad search 或 citation from seed |
| `pool_20_forming` | 20 篇，簇未稳定 | 提议继续 broad search 或 cluster_refresh |
| `pool_50_no_classics` | 50 篇全是近期 | 提议 classic_lookup 或 targeted search |
| `cluster_without_benchmarks` | 某簇 shared_benchmarks 空 | 提议 read_paper 或 skim_abstract 该簇 centroid |
| `saturated_no_audit` | 饱和但 coverage_report 为 None | 提议 coverage_audit |
| `audit_with_gaps` | audit 有未回答的 question | 提议针对性 search 或 fetch |
| `deadlock_5_blocks` | consecutive_blocked=5 | 被 spec force 到 coverage_audit（测 spec 而非 planner） |
| `budget_exhausted_read` | read_papers_used=3 | **不该**提 read_paper |
| `off_topic_drift` | recent queries 已偏离 intent | 应回归 intent 范围内的 query |
| `refine_with_feedback` | `--feedback "深挖 vln-ce"` | 应目标 vln-ce 簇 |

## Future work

- **Few-shot examples**：v1 不加。若 pass rate 起步太低，加 1-2 个完整的"好 reasoning"示例入 system prompt
- **动态难度调整**：若 planner 反复撞 spec，动态在 dynamic prompt 里加强警告措辞
- **LLM-as-judge for reasoning quality**：v1 用正则检查 reasoning 引用 state；v2 可加 Pro judge 评分

## 开放点（实装时再定）

- 动态 context 的 token 预算上限（防 pool 超大时爆炸）
- 长 recent_history 压缩策略（超过 10 条时保留哪些）
- 测试的 fixture 是否版本控（目前假设 fixture 文件本身即版本控）
