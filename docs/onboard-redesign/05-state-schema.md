# ExplorationState Schema

> Explorer 的核心数据结构。Spec predicate 从这里读判断依据，Planner 从这里取决策上下文，Checkpoint 序列化它。
> 本文档描述 **v1 的 schema**，后续破坏性变更须提升 `schema_version`。

## 设计目标

1. **所有 spec predicate 的输入都在 state 里**（或派生属性里）
2. **所有 planner 决策所需的上下文都在 state 里**
3. **state 可以 JSON 序列化、人类可读、跨版本可迁移**
4. **state 不存冗余大对象**（embedding 向量 / 全文 / 对话记录都在别处）

## 顶层结构

```python
@dataclass
class ExplorationState:
    # —— 元信息 ——
    schema_version: int                    # v1 = 1
    metadata: RunMetadata

    # —— 输入 ——
    intent: Intent
    feedback: Optional[str]                # refine 模式的新 objective

    # —— 核心数据 ——
    paper_pool: Dict[str, PaperRecord]     # arxiv_id → record
    query_log: List[QueryRecord]           # 全部历史
    action_history: List[ActionRecord]     # 全部 action，planner 只看最近 N 条

    # —— 结构化视图 ——
    cluster_snapshot: Optional[ClusterSnapshot]
    counters: Counters

    # —— 评估 ——
    coverage_report: Optional[CoverageReport]
    budget: BudgetState
```

预估大小：200 篇论文时约 500KB JSON。

## 组件详解

### RunMetadata

```python
@dataclass
class RunMetadata:
    run_id: str                                  # "20260417-1430-a3f"
    started_at: datetime
    last_updated_at: datetime
    llm_tier: Literal["production", "budget", "dev"]
    code_version: str                            # git commit，用于 schema 兼容排查
    status: Literal["running", "completed", "cancelled", "failed"]
    termination_reason: Optional[str]            # "saturated" / "user_cancel" / "api_error" / "rule_deadlock" ...
```

### Intent

```python
@dataclass
class Intent:
    natural_language: str
    seed_arxiv_ids: List[str]
    seed_validation: Dict[str, SeedValidation]   # arxiv_id → validation

@dataclass
class SeedValidation:
    matched: bool
    match_score: float                           # 0.0–1.0
    reason: str                                  # LLM 给的理由
    used_as_anchor: bool                         # 是否作为引用扩展起点
```

种子论文"不匹配"仍保留在 pool 里（flag 中标注），只是不做引用起点。

### PaperRecord

```python
@dataclass
class PaperRecord:
    # —— ArXiv 元数据 ——
    arxiv_id: str
    title: str
    abstract: str
    authors: List[str]
    published: date
    categories: List[str]
    pdf_url: str

    # —— 探索溯源 ——
    first_seen_turn: int
    source: Literal["search", "citation_expansion", "related", "seed"]
    source_query_id: Optional[str]
    source_paper_id: Optional[str]

    # —— Embedding 引用（向量本体在 ChromaDB）——
    embedding_id: Optional[str]

    # —— Semantic Scholar 信号（可降级时为 None）——
    citation_count: Optional[int]
    reference_count: Optional[int]
    citation_data_fetched_at: Optional[datetime]

    # —— LLM skim 结果 ——
    skim: Optional[SkimResult]

    # —— 聚类归属（Clusterer 填）——
    cluster_id: Optional[str]                    # = cluster.slug，如 "zero-shot-objnav"
    is_noise: bool

    # —— Flag ——
    flags: List[str]                             # ["seed_mismatch", "deep_read_candidate", ...]

@dataclass
class SkimResult:
    benchmarks: List[str]
    methods: List[str]
    keywords: List[str]
    skimmed_at: datetime
```

### QueryRecord

```python
@dataclass
class QueryRecord:
    query_id: str                                # uuid
    turn: int
    query_text: str
    categories: List[str]
    source: Literal[
        "user_intent_rewrite",
        "llm_generated",
        "cluster_targeted",
        "citation_seeded",
        "author_seeded",
        "benchmark_seeded",
        "classic_lookup",
    ]
    targeted_cluster_slug: Optional[str]         # 若 source == "cluster_targeted"
    query_embedding_id: Optional[str]            # 用于 spec 的 query_diversity 判断

    # —— 结果 ——
    n_results_raw: int                           # ArXiv 返回多少
    n_new_to_pool: int                           # 饱和度分子
    executed_at: datetime
```

### ActionRecord

```python
@dataclass
class ActionRecord:
    turn: int
    action_type: Literal[
        "search",
        "fetch_citations",
        "fetch_related",
        "cluster_refresh",
        "skim_abstract",
        "read_paper",
        "synthesize_partial",
    ]
    action_args: dict                            # 结构化参数，每种 action 不同

    proposed_at: datetime

    # —— Spec 评估 ——
    spec_verdict: Literal["allow", "block", "rewrite", "force"]
    spec_feedback: Optional[str]
    spec_rules_fired: List[str]

    # —— 执行 ——
    executed_at: Optional[datetime]
    outcome: Literal["success", "skipped", "failed", "not_executed"]
    outcome_summary: str                         # "+12 papers, 2 dupes"
    duration_ms: int

    # —— LLM 成本 ——
    llm_calls: List[LLMCallRecord]

@dataclass
class LLMCallRecord:
    model: str                                   # "gemini-2.5-pro" / "gemini-2.5-flash"
    purpose: str                                 # "planner_propose" / "skim_abstract" / ...
    input_tokens: int
    output_tokens: int
    duration_ms: int
```

### ClusterSnapshot

```python
@dataclass
class ClusterSnapshot:
    snapshot_id: str
    generated_at: datetime
    generated_after_turn: int
    n_papers_at_time: int
    algorithm: str                               # "hdbscan"
    params: dict

    clusters: List[Cluster]
    noise_paper_ids: List[str]

    prev_snapshot_id: Optional[str]
    # 稳定性从 prev vs current 的 slug 集合 Jaccard 现场算，不落盘
```

### Cluster

```python
@dataclass
class Cluster:
    slug: str                                    # 内容生成的 id，严格格式
    display_label: str                           # 人类友好标签，可被用户编辑
    description: str                             # LLM 生成

    paper_ids: List[str]
    size: int

    centroid_paper_id: Optional[str]
    representative_paper_ids: List[str]          # top-5 by 距离质心

    # 从 counters 派生的簇级视图
    shared_benchmarks: List[str]
    top_authors: List[str]
    year_range: Tuple[int, int]
    density: Literal["dense", "sparse", "mixed"]

    # 血缘
    inherited_from_slug: Optional[str]           # 若 != slug，说明曾 rename 过
    first_seen_in_snapshot: str

    # Configure 阶段的编辑历史
    user_edits: List[EditRecord]

@dataclass
class EditRecord:
    edit_type: Literal["rename_display", "edit_description", "merge_source"]
    from_value: Optional[str]
    to_value: Optional[str]
    edited_at: datetime
```

**Slug 规则**：
- 格式：`[a-z0-9]+(-[a-z0-9]+){0,2}`（lowercase + hyphen，1–3 token）
- 生成：LLM prompt 里带上一次快照的 (slug, representative_papers)，指示"若与旧簇论文重合 ≥ 50% → 复用旧 slug；否则生成新 slug"
- 碰撞：两个语义不同的新簇 slug 冲突 → 要求 LLM 给第二个换更具区分度的 slug（不加机械后缀）
- 校验：Clusterer 拿到 LLM 输出后正则校验，不符就截断或重问

**Slug ≠ Label 的分工**：
- `slug` 是引用 id，改动要谨慎（会影响 paper.cluster_id）
- `display_label` 是展示名，用户 `rename` 改的是这个

### Counters

```python
@dataclass
class Counters:
    benchmark_counter: Dict[str, List[str]]      # benchmark_name → [arxiv_ids]
    author_counter: Dict[str, List[str]]
    venue_counter: Dict[str, List[str]]          # 含 "2024" 等年份

    benchmark_aliases: Dict[str, str]            # "HM3D-ObjNav" → "HM3D"
```

Per-cluster 的 counter（如 `cluster.shared_benchmarks`）是派生视图，在 Cluster 对象里直接算好。

### CoverageReport

```python
@dataclass
class CoverageReport:
    generated_at: datetime
    generated_after_turn: int
    questions: List[CoverageQuestion]
    passes: bool
    unanswered_count: int

@dataclass
class CoverageQuestion:
    question: str                                # "领域分几支？"
    answer_available: bool
    evidence: str                                # "clusters has 4 labeled entries with descriptions"
    gap_description: Optional[str]               # 若 not available，缺什么
```

### BudgetState

```python
@dataclass
class BudgetState:
    # 时间
    time_budget_seconds: int
    elapsed_seconds: float

    # Action 次数
    action_budget: int
    actions_used: int
    read_paper_budget: int                       # 默认 3
    read_papers_used: int

    # Token
    llm_tokens_used: Dict[str, int]              # {"pro": ..., "flash": ...}
    llm_cost_estimate_usd: float

    # 外部 API
    semantic_scholar_quota_remaining: Optional[int]
```

## 派生属性

不落盘，给 spec predicate 用。定义在 ExplorationState 类上作为 `@property` 或方法：

```python
class ExplorationState:
    @property
    def pool_size(self) -> int: ...

    @property
    def new_paper_ratio_last_n_rounds(self, n: int = 3) -> float: ...

    @property
    def recent_query_embedding_ids(self, n: int = 3) -> List[str]: ...

    @property
    def consecutive_blocked_actions(self) -> int: ...

    @property
    def is_saturated(self) -> bool:
        return self.new_paper_ratio_last_n_rounds(3) < 0.10

    @property
    def is_cluster_stable(self) -> bool:
        # 比较 current 和 prev snapshot 的 slug 集合 Jaccard
        ...

    @property
    def has_classic_baseline_per_cluster(self) -> bool: ...

    @property
    def recent_history(self, n: int = 10) -> List[ActionRecord]: ...
```

Spec predicate **只读 fields 和 properties**，不扒原始 dict，保证稳定。

## 什么不放进来

| 不放 | 原因 |
|---|---|
| Embedding 向量本体 | 在 ChromaDB，state 存 id |
| PDF 全文 | 太大，需要时 re-download |
| LLM 对话 transcript | 在 `logs/<run_id>.log` |
| 原始 API response | 提取完就丢 |
| 成对相似度矩阵 | 派生属性现场算 |

## 序列化

- **JSON**（不用 pickle，跨版本稳定、人可读可改）
- `datetime` → ISO 8601 string
- `Literal` → str
- 所有 dict key 保持 str

建议用 `pydantic` 做验证 + 序列化；若不想引入则用 `dataclasses.asdict` + 自定义 JSON encoder。

## 版本与 migration

```python
schema_version: int = 1
```

- 破坏性变更（删字段 / 改类型 / 改语义）→ 版本号 +1
- 非破坏（加字段 + default）→ 版本号不变
- Resume 时若 state 版本低于代码 → 走 migration 函数升级
- 升级失败 → 拒绝 resume，报告缺失的迁移步骤

## 开放点（不阻塞 v1）

### OP-1. action_history 保留全部 vs 限窗
v1 方案：**全保留**（每条 ~500B，500 条也才 250KB），planner prompt 只注入最近 N。
v2 若发现膨胀再引入滚动窗口。

### OP-2. Hot/Cold state 拆分
v1：**全量 JSON 写**（每 action 一次）。
v2 若 I/O 成瓶颈再拆：`hot.json`（history/budget）+ `cold.json`（pool/cluster）。

### OP-3. Embedding 持久化位置
所有向量都走 ChromaDB 的 collection，state 只存 id 引用。ChromaDB 自己持久化，resume 时两边必须一致。若 ChromaDB 丢了 state 还在，视为 fatal，不尝试重建。

### OP-4. 多 run 的 ChromaDB collection 策略
- 方案 A：每个 run_id 一个 collection（互不干扰，但清理成本）
- 方案 B：全局一个 collection，id 带 run_id 前缀（复用 embedding，但污染风险）
- v1 倾向 A（简单、干净），v2 优化到 B。
