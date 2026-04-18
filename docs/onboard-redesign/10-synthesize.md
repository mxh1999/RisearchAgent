# Synthesize: State → Field Map

> Explorer 结束后，把 `ExplorationState` 合成用户看得到的 `field_map.md`。
> 纯函数阶段：输入冻结的 state，输出 Markdown + 结构化 JSON。

## 职责

**单一输入**：Explorer 产出的 `ExplorationState`（status=completed）
**单一输出**：
- `data/explore/field_maps/<run_id>.md`（用户看的）
- `data/explore/field_maps/<run_id>.json`（Configure 阶段用的结构化版本）

失败不重跑 Explorer，可单独重跑。

## 两阶段处理

```
state.json
  ↓
Stage 1: LLM 合成（1 次 Pro 调用，产出结构化 JSON）
  ↓
field_map.json
  ↓
Stage 2: 确定性渲染（Python 模板，不调 LLM）
  ↓
field_map.md
```

好处：
- LLM 负责"理解与叙述"；渲染负责"样式"
- 模板变了不重调 LLM
- JSON 可被 Configure 阶段机器读取（用户改 label 后可 diff）

## Stage 1：LLM 合成

**1 次 Pro 调用**，`response_schema` 绑定以下结构：

```python
@dataclass
class FieldMap:
    header: Header                                  # 元信息
    sub_areas: List[SubArea]                        # 来自 cluster_snapshot.clusters
    dominant_benchmarks: List[BenchmarkEntry]
    schools_of_thought: List[SchoolOfThought]       # LLM 跨簇归纳
    classic_baselines: List[ClassicPaper]           # 高被引 + 早期
    active_groups: List[ActiveGroup]                # 从 author_counter
    open_questions: List[OpenQuestion]              # LLM 从 abstract 聚合
    anchor_papers: List[AnchorPaper]                # 每簇选 2-3，高被引 × 中心性
    notes: List[str]                                # 分裂警报、降级提示、种子不匹配等
```

### Prompt 要点

系统 prompt：
- 身份："你是研究领域地图合成器"
- 输入格式说明（state 的各字段）
- 输出 JSON 结构严格要求
- **引用规则**：每个声明必须附 arxiv_id；不得捏造
- **叙述风格**：每个 sub_area 描述 3-5 句，客观，不主观评价

用户 prompt（动态）：注入以下字段摘要：
- Intent + seed validation
- Cluster snapshot（全部簇的 full 视图：slug / label / description / representatives / benchmarks / authors / years）
- Counters top-20（三个）
- Coverage report
- 噪声论文（前 10 个）
- Budget 摘要（`{n_papers} surveyed, {n_queries} queries, {elapsed}`）

预估 input ~8-15k tokens，output ~3-5k tokens。单次 Pro ~$0.05/run。

### 引用校验

合成完后对输出 JSON 做**确定性**校验：

```python
def validate_citations(field_map: FieldMap, state: ExplorationState):
    all_ids_mentioned = extract_all_arxiv_ids(field_map)
    hallucinated = all_ids_mentioned - set(state.paper_pool.keys())
    if hallucinated:
        raise SynthesisError(f"Hallucinated arxiv_ids: {hallucinated}")
```

Hallucinated ID → 重试一次；仍失败 → fail，提示人工介入（不是静默降级）。

## Stage 2：渲染

纯 Python，Jinja2 或手工字符串拼装。模板：

```markdown
# Field Map: {intent_snippet}

_Generated {generated_at}  |  {n_papers} papers surveyed  |  {n_queries} queries  |  {elapsed}_

{if notes:}
> **Notes:**
> {bullet list}

## Sub-areas

### {slug}: {display_label}
{description}

**Representative papers:**
- [{arxiv_id}]({arxiv_url}) — {title}
- ...

**Shared benchmarks:** {list}
**Active authors:** {list}
**Year range:** {y1}–{y2}

{repeat per cluster}

## Dominant Benchmarks

| Benchmark | Task | Papers | Representative results |
|---|---|---|---|
...

## Schools of Thought

{each entry: name, brief, representative papers with slugs they come from}

## Classic Baselines

{list of (title, arxiv_id, year, why_classic)}

## Active Groups

{list of authors with paper counts and affiliated clusters}

## Open Questions

{LLM-identified recurring questions in abstracts}

## Anchor Papers (for SOTA seeding)

{list per cluster, top 2-3 by citation × centrality}

---

{degraded note if citation_provider was unavailable}
```

## 关键设计约束

### 1. LLM 不做"新发现"
合成只整理已有信息。**禁止**让 LLM 推断 state 里没有的事实（如没 skim 过的论文的 benchmark、没查过的作者信息）。

### 2. LLM 不做价值判断
禁止 LLM 输出"这个方向很有前景"、"X 方法不够好"等主观评价。prompt 里明示反例。

### 3. 结构化数据 + 可重渲染
JSON 是事实，Markdown 是样式。用户想要更短 / 英文 / 中文版本 → 换模板即可。

## 失败路径

| 失败 | 处理 |
|---|---|
| LLM JSON 不符 schema | 重试 1 次 → fail，保留 state 让人审 |
| Hallucinated arxiv_id | 重试 1 次 → fail |
| Citation provider 降级（state 里有 flag） | 正常合成，render 时注明 "Classic baseline section may be incomplete due to citation data unavailability" |
| 某簇的 representative 太少（<2） | LLM 可标注 "(limited data)"，不中断 |
| 所有簇为 noise | 降级模板：只渲染 header + noise papers list + "Clustering did not yield stable structure" note |

## Refine 模式：Diff 视图

Refine 跑完后，除了常规 field_map，额外生成 `field_map_diff.md`：

```markdown
# Field Map Update — {run_id_new} vs {run_id_old}

## New sub-areas
- `{slug}`: {label} ({n} papers)

## Grown sub-areas
- `{slug}`: {n_old} → {n_new} papers

## Shrunk / dormant
- `{slug}`: {n_old} → {n_new} papers (or disappeared)

## New benchmarks
- {name} (first seen in {n} papers this refresh)

## Notable new papers
- ...
```

Diff 是确定性计算，无需 LLM（比较两份 field_map.json）。

## 测试

- **结构化校验（确定性）**：输出 FieldMap 通过 pydantic；所有 arxiv_id 合法；每簇 sub_area 非空
- **内容校验（T2 LLM）**：
  - 给 fixture state，合成后检查 sub_areas.count == cluster_snapshot.clusters.count
  - 检查 description 长度 50–300 字符
  - 检查 `dominant_benchmarks` 与 `benchmark_counter` top-10 重合度 ≥ 80%
- **Golden render 测试**：给固定 FieldMap JSON，渲染后和预期 Markdown 字符串比对（catches 模板 bug）

## 开放点（实装时再定）

- Markdown 里 arxiv 链接用 `https://arxiv.org/abs/{id}` 还是内部相对路径
- Sub-area 最多展示几个 representative（默认 3，可配）
- `notes` 列表的顺序规则（按重要性？）
