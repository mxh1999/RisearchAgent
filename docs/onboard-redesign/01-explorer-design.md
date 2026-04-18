# Explorer Agent 设计

## Goals / Non-goals

### Goals
- 独立运行 5–15 分钟，产出一份有引用、可审计的领域地图
- 广度优先：扫过 100–300 篇 abstract，深读极少（0–3 篇）
- 输出可追溯：每个声明背后有论文证据
- 可终止：明确的饱和判据，不靠 LLM 主观判断

### Non-goals
- 不深读每篇（交给 reader / RTI）
- 不决定"用户想要什么"（交给 Configure 阶段）
- 不翻译、不思维导图（交给 RTI）

## Exploration State（核心数据结构）

Agent 的**认知状态**，每轮读写，合成时消费。

```
ExplorationState
├── seed_intent: 用户意图 + 种子论文（可选）
├── query_log: [(query, categories, timestamp, n_new_papers)]
├── paper_pool: {arxiv_id -> PaperRecord}
│     PaperRecord = {meta, abstract, source_queries, citation_count, first_seen_turn}
├── cluster_snapshot: 最近一次聚类结果
├── benchmark_counter: {benchmark_name -> [arxiv_ids]}
├── author_counter: {author -> [arxiv_ids]}
├── venue_counter: {venue/year -> [arxiv_ids]}
├── open_questions: [agent 自己记下的假设，留待下一轮验证]
└── coverage_report: 领域分几支？每支多少论文？classic vs recent 比例？
```

关键点：**这是 agent 思考的产物，不是日志**。每轮都读上一轮的状态，决定下一步。

## Action Space（受限，不是自由）

| Action | 说明 |
|---|---|
| `search(query, categories)` | 横向扇出 |
| `fetch_citations(arxiv_id)` | 引用图扩展 |
| `fetch_related(arxiv_id)` | semantic scholar / connected papers |
| `cluster_refresh()` | 重新聚类 |
| `skim_abstract(arxiv_id)` | 已在池里但没仔细看 |
| `read_paper(arxiv_id)` | 深读，只对枢纽论文，预算极小 |
| `synthesize_partial()` | 尝试写中间报告，发现 gap |

## 查询扇出策略

单靠 LLM "想 query" 质量太飘。种子来源分类：

| 种子来源 | 作用 |
|---|---|
| 用户意图改写 | 基础查询 |
| 同义/邻域扩展 | LLM 给近义词 |
| 已抓论文的关键词 | 从 abstract 提术语反哺 |
| 引用图扩展 | 池中高频被引论文的引用 |
| 作者扩展 | 池中高频作者的其他工作 |
| benchmark 反查 | 从识别出的 benchmark 名搜回去 |
| 时间分层 | 分别搜 classic（2018–2021）/ frontier（2023–2025） |

每类至少发一次，保证覆盖不坍缩到 LLM 初始直觉。

## 停止条件

同时满足：

1. **饱和度**：最近 3 轮 query 带来的新论文占比 < 10%
2. **覆盖度**：
   - 池 ≥ 80 篇
   - Benchmark counter top-3 集中（出现 ≥ 5 次）
   - 时间分布同时覆盖近 1 年 + 3 年以上
   - 至少识别出 2 个子簇
3. **Budget**：硬上限兜底（时间 / API / token）
4. **Self-audit**：LLM 读 state，能回答 "领域分几支 / 主导 benchmark / 经典基线 / 代表作者"

## 合成（Synthesize）

探索结束后单独一步，**不做新检索**，只做结构化。产出 `field_map.md`：

```markdown
# Field Map: <topic>
Generated: <date> | Papers surveyed: 147 | Queries issued: 23

## Sub-areas
### A. Zero-shot ObjNav
Representative: [2312.xxxxx](...), [2401.xxxxx](...)
Key challenges: ...

## Dominant benchmarks
| Benchmark | Task | Seen in | Representative results |

## Schools of thought

## Classic baselines

## Active groups / authors

## Open questions

## Anchor papers for SOTA seeding
```

Synthesize 失败不重跑 explore，可以单独重试。

## 与主 pipeline 的复用

- `ArxivScraper.search()` 复用
- `RelevanceJudge` 不用（explore 阶段保留所有）
- `DeepReader` 只在 `read_paper` action 用
- ChromaDB 用来对论文做在线聚类
- 实现上 = 新 orchestrator + planner + state 对象，底层 I/O 复用
