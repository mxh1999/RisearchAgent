# Action 系统

> Explorer 的动作集合、参数契约、执行模型、校验分层。
> 所有 action 都经过 Planner 提议 → Spec 校验 → Executor 执行 → State 更新的统一循环。

## 目录（9 个 action）

| # | Action | 作用 | LLM 使用 | 预算属性 |
|---|---|---|---|---|
| 1 | `search` | ArXiv 通用查询扇出 | — | 次数不限 |
| 2 | `search_by_author` | 按作者搜其他论文 | — | 次数不限 |
| 3 | `fetch_citations` | 被引 / 引用扩展（Semantic Scholar） | — | 次数不限（受 SS 配额） |
| 4 | `fetch_related` | 相关论文推荐（Semantic Scholar） | — | 次数不限 |
| 5 | `cluster_refresh` | 重新聚类 + LLM 打标签 | Flash（每新 slug 1 次） | 次数不限 |
| 6 | `skim_abstract` | 从 abstract 提 benchmark/method/keyword | Flash（1 次/篇） | 次数不限 |
| 7 | `read_paper` | 深读（复用 DeepReader） | Pro（3-pass） | 硬上限 3 次/run |
| 8 | `coverage_audit` | 自审产出 CoverageReport | Pro | 建议 ≤ 3 次/run |
| 9 | `stop` | 请求终止 exploration | — | 1 次（成功则退出） |

### 命名澄清

- 原 `synthesize_partial` 改名 **`coverage_audit`**：该 action 只产 CoverageReport，不产 user-facing 内容（那是 Synthesize **阶段** 的事）。
- `stop` 是 action 而非自动触发：统一决策路径，spec 只有一套逻辑判停。

## 类型设计：typed subclass

```python
@dataclass(kw_only=True)
class Action:
    reasoning: str                    # planner 的理由，进 log 和 ActionRecord

@dataclass
class SearchAction(Action):
    query: str
    categories: List[str]
    max_results: int = 20             # 上限由 spec 管
    date_range: Optional[Tuple[date, date]] = None
    sort_by: Literal["relevance", "date"] = "relevance"
    source_tag: Literal[
        "user_intent_rewrite", "llm_generated", "cluster_targeted",
        "benchmark_seeded", "classic_lookup",
    ] = "llm_generated"
    targeted_cluster_slug: Optional[str] = None

@dataclass
class SearchByAuthorAction(Action):
    author_name: str                  # "Wang L." 形式
    max_results: int = 15
    date_range: Optional[Tuple[date, date]] = None

@dataclass
class FetchCitationsAction(Action):
    arxiv_id: str
    direction: Literal["cited_by", "references", "both"] = "references"
    max_results: int = 20

@dataclass
class FetchRelatedAction(Action):
    arxiv_id: str
    max_results: int = 10

@dataclass
class ClusterRefreshAction(Action):
    force: bool = False

@dataclass
class SkimAbstractAction(Action):
    arxiv_id: str

@dataclass
class ReadPaperAction(Action):
    arxiv_id: str

@dataclass
class CoverageAuditAction(Action):
    pass

@dataclass
class StopAction(Action):
    claimed_reason: Literal[
        "saturated", "coverage_complete", "budget_exhausted"
    ]
```

## LLM 输出契约

Planner 只产 **JSON**，按 `action_type` 做 pydantic discriminated union 分发：

```json
{
  "action_type": "search",
  "args": {
    "query": "vision-language navigation classic baselines",
    "categories": ["cs.RO", "cs.CV"],
    "max_results": 20,
    "date_range": ["2019-01-01", "2021-12-31"],
    "source_tag": "classic_lookup"
  },
  "reasoning": "Cluster vln-ce has no papers before 2022; searching 2019-2021 classics."
}
```

不符 schema → Q8 的 "JSON malformed" 路径 → 落盘 + 诊断信息 + 退出。

## 校验分层

```
L1 Schema (pydantic)       JSON 能解析为 typed Action              → 失败：退出
L2 Arg 合法性 (__post_init__)  max_results∈[1,50], arxiv_id 格式…   → 失败：退出（同 L1）
L3 Spec 规则 (运行时)        预算 / 饱和 / 多样性 / 死锁            → 失败：block/rewrite
```

L1+L2 是**结构性**检查（等同 JSON malformed），L3 是**决策性**检查（可协商）。

## Action 执行接口

```python
class ActionExecutor:
    async def execute(
        self, action: Action, state: ExplorationState
    ) -> ActionResult:
        ...

@dataclass
class ActionResult:
    success: bool
    summary: str                      # "+12 papers, 2 dupes"
    details: ActionDetails
    duration_ms: int
    llm_calls: List[LLMCallRecord]
    error: Optional[str] = None
```

`ActionDetails` 按 action 子类化（SearchDetails / ClusterRefreshDetails / …），Executor 通过 `match action` 派发到专属 handler。

### 每种 Action 的详细契约

#### SearchAction
- **Effects**: 创建 QueryRecord（source 来自 source_tag）；新论文加入 pool（source="search"，source_query_id=query_id）
- **Side effects**: 新论文生成 embedding + counters 更新；若 SS 可用则异步拉 citation 数
- **Details**: `query_id, n_fetched, n_new, n_deduped, new_arxiv_ids`

#### SearchByAuthorAction
- **Internal**: Executor 构造 `au:"<name>"` query 调 ArXiv（不让 planner 编 query 语法）
- **Effects / Side effects / Details**: 同 SearchAction，source="author_seeded"

#### FetchCitationsAction
- **Effects**: 创建 QueryRecord（source="citation_seeded"）；新论文 source="citation_expansion"，source_paper_id=arxiv_id
- **Side effects**: 同 Search
- **Details**: `query_id, n_fetched, n_new, new_arxiv_ids, source_paper_id, direction`

#### FetchRelatedAction
- **Internal**: 走 Semantic Scholar `/recommendations`
- **Effects**: 新论文 source="related"
- **Details**: 类似

#### ClusterRefreshAction
- **Internal**: HDBSCAN 聚类（确定性）；每个**新** slug 1 次 Flash（生成 slug + label + description）；老 slug（重合 ≥ 50%）直接继承
- **Effects**: 写新 ClusterSnapshot；更新所有 paper.cluster_id
- **Details**: `snapshot_id, n_clusters, new_slugs, disappeared_slugs, structural_change_rate`

#### SkimAbstractAction
- **Internal**: 1 次 Flash 从 abstract 抽 benchmark/method/keyword
- **Effects**: 填 paper.skim；benchmark 写入 benchmark_counter（经 alias 归一化）
- **Details**: `skim_result: SkimResult`

#### ReadPaperAction
- **Internal**: PDFDownloader 下载 + DeepReader 3-pass
- **Effects**: 填 paper.explore_reading（state 内的字段，**不写主 DB 的 deep_readings 表**）；counters 更新（benchmark / author）
- **Budget**: 占用 `read_paper_budget`（默认 3）
- **Details**: `reading_summary` 等

#### CoverageAuditAction
- **Internal**: 1 次 Pro，输入 state 摘要，输出 CoverageReport
- **Effects**: 替换 state.coverage_report
- **Details**: `n_questions, passes, unanswered_count`

#### StopAction
- **Internal**: 无执行；验证由 spec 完成
- **Effects**: state.metadata.status = "completed"，termination_reason = claimed_reason，跳出主循环

## 自动副作用（非 action）

这些是 action 执行后**自动发生**的，不占 planner 决策带宽、不进 action_history：

| 自动操作 | 触发时机 |
|---|---|
| budget.actions_used += 1 | 每 action 结束 |
| budget.llm_tokens_used 累加 | 每次 LLM 调用 |
| counters（benchmark/author/venue）增量更新 | 新论文 / skim / read 完成 |
| embedding 生成（写 ChromaDB） | 新论文加入池 |
| 自动 flag（如 seed_mismatch、deep_read_candidate） | 相关流程结束 |
| 论文去重（按 arxiv_id） | 加入池前 |
| Checkpoint 落盘 | 每 action 结束 |
| Dashboard 刷新 | 每 action 结束 |

## 主循环骨架

```python
async def explore_loop(state, planner, spec, executor, dashboard):
    while state.metadata.status == "running":
        # 1. Planner 提议
        raw = await planner.propose(state)
        try:
            action = parse_action(raw)                 # L1 + L2
        except (pydantic.ValidationError, ValueError) as e:
            fail_fast(state, "json_malformed", diagnostics=raw, exception=e)
            raise

        # 2. Spec 评估（L3）
        verdict = spec.evaluate(action, state)

        if verdict.kind == "block":
            record_blocked_attempt(state, action, verdict)
            continue                                    # 下轮 planner 看到 feedback
        elif verdict.kind == "rewrite":
            action = verdict.rewritten_action

        # 3. 执行
        result = await executor.execute(action, state)

        # 4. State + 副作用
        apply_action_effects(state, action, result)
        state.action_history.append(
            ActionRecord.from_action_and_result(action, result, verdict)
        )
        save_checkpoint(state)
        dashboard.update(state)

        # 5. Stop 的特殊处理
        if isinstance(action, StopAction) and result.success:
            state.metadata.status = "completed"
            state.metadata.termination_reason = action.claimed_reason
            break
```

## 关键设计点

### ① `read_paper` 的成本与实现
v1 **直接复用** `DeepReader`（3-pass Pro），通过 `read_paper_budget` 限到 3 次/run。
v2 可能写 `LightweightReader`（1-pass Flash）专供 Explorer；v1 不优化。

### ② 读的结果**不进主 DB**
Explorer 的 `read_paper` 只更新 state 内的 `PaperRecord.explore_reading`，不写 SQLite `deep_readings` 表。同篇走主 pipeline 时会被重读，带 relevance 判断。

### ③ `search` 结果**不自动 skim**
新论文进池只做**便宜元数据处理**（去重、embedding、聚类归属）。Skim 交给 planner 显式 `skim_abstract(arxiv_id)`——让它按需决策（例如只 skim 噪声论文）。

### ④ `cluster_refresh` 的 LLM 成本
LLM 调用数 = **新 slug 数** × 1 Flash。继承的老 slug 不重调。典型 1–3 次/ refresh。

### ⑤ `stop` 的声明式验证
Planner 提议 `stop` → spec 依次验：
1. 饱和度：`new_paper_ratio_last_3 < 0.10`
2. 覆盖度：`coverage_report.unanswered_count == 0`
3. 预算健康（若是预算型终止则跳过 1/2）

任一失败 → block + feedback。"何时可以停"完全声明在 spec 里。

### ⑥ `cluster_refresh` 的兜底
Planner 显式提议为主，但 spec 加一条**强制**规则：`pool 新增 ≥ 15 篇 → force_action(cluster_refresh)`。防止 planner 忘聚类导致决策依赖的 snapshot 过旧。

### ⑦ `search_by_author` 单独 action
Planner 不编 ArXiv 的 `au:` 语法（不可靠）。专属 action 把 author_name 作结构化参数，Executor 内部构造正确 query。

## 已定与未定

**已定**：
- 9 个 action 的类型与参数契约
- 校验分层（L1/L2 硬失败，L3 协商）
- 执行接口与主循环
- 自动副作用清单
- `read_paper` 复用 DeepReader / 不写主 DB
- `skim_abstract` 单篇（不批量）
- `cluster_refresh` 保留为 action + spec 兜底强制

**未定（留给后续文档）**：
- 每种 action 的参数**上下界**具体值（比如 max_results 的 hard cap，写进 spec 规则文档 07）
- ActionDetails 每个字段的确切格式（实现时细化）
- Planner 的 prompt 模板（文档 08）
- Spec 规则 DSL 的代码形态（文档 07）
