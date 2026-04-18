# Configure: Field Map → config.yaml

> Onboard 流程的最后一阶段。用户在 field_map 上做选择和轻量编辑，派生 `config.yaml` 并 seed SOTA。
> 核心原则（见 00）：**默认 Enter 即完成**；命令模式只对想精调的用户开放。

## 输入 / 输出

**输入**：
- `field_map.json`（10 的 Stage 1 产物）
- `state.json`（作为数据源，提供 paper_pool / counters / metadata）

**输出**：
- `config.yaml`（更新或新建，主 pipeline 的配置）
- `data/sota/*.md`（seed 一批 SOTA leaderboard）
- 若 refine：diff 展示 vs 旧 config

## Happy Path（5 秒体验）

```
╭─ Field Map Summary ──────────────────────────────╮
│ Intent: embodied navigation                      │
│ 5 sub-areas identified, 147 papers surveyed      │
│                                                  │
│ Suggested to track all 5 clusters:               │
│   zero-shot-objnav  (22 papers)                  │
│   vln-ce            (35 papers)                  │
│   slam-classical    (12 papers)                  │
│   llm-planner       (18 papers)                  │
│   lang-nav-grounding (9 papers)                  │
│                                                  │
│ Suggested threshold: 6                           │
│ Will seed SOTA from 12 anchor papers (3 deep reads per cluster max)  │
╰──────────────────────────────────────────────────╯

[Enter]  accept defaults, write config.yaml
[e]      edit interactively
[q]      quit without saving
>
```

用户按 Enter → 写 config.yaml + 启动 seed（可在后台进度条展示）。

## 命令模式

按 `e` 进入后：

```
configure> help

Commands:
  list                         show all clusters
  show <slug>                  detail of one cluster
  select <slug,slug,...>       choose which to track (default: all)
  select all / none            bulk
  rename <slug> "<label>"      change display label
  drop <slug>                  exclude this cluster
  merge <slug1,slug2> as "<label>"   merge two clusters into one topic
  split <slug>                 re-cluster papers in this slug
  threshold <n>                relevance score threshold (default 6)
  anchors <slug> <n>           pick n anchor papers for seed (default 3)
  reasoning <slug>             show the LLM's description for this cluster
  preview                      show the config.yaml that would be written
  accept                       finalize
  cancel                       abandon edits

configure>
```

命令语法**单行式**，解析简单（`shlex.split`），不搞交互 wizard。

### 命令语义细节

**`select`**：维护一个 `selected: Set[str]`。未被 select 的簇在派生 config 时跳过。默认 `select all`（所以不用操作也完成）。

**`rename`**：改 `cluster.display_label`，slug 不变。Slug 不可改（那是 ID）。

**`drop`**：从 `selected` 移除。等价 `select <all except this>`。

**`merge`**：把两簇标为合并，派生 config 时产生一个 topic，query 由 LLM 结合两簇生成（一次额外 Flash 调用）。合并后的 slug 是 `<slug1>+<slug2>` 组合。**merge 不重新聚类**——只是 config.yaml 层面合并。

**`split`**：对该簇内的 paper_ids 子集跑一次 mini-HDBSCAN，产生 2+ 子簇。各自需 LLM label。分裂后原 slug 被移除，新 slug 加入。此操作**会重新调 LLM**（不是免费）。

**`threshold`**：直接改最终写入的 relevance_threshold。

**`anchors`**：调整某簇的 anchor paper 数（用于 seed SOTA）。默认从 `representative_paper_ids` + citation rank 综合选 top-3。

**`preview`**：打印当前状态下 config.yaml 的 dry-run 结果（不写盘）。

**`accept`**：进入落盘阶段。

## 派生 config.yaml

```python
def derive_config(
    field_map: FieldMap,
    selections: ConfigureSession,
    intent: Intent,
) -> dict:
    topics = []
    for cluster in field_map.sub_areas:
        if cluster.slug not in selections.selected:
            continue

        # 合并的簇特殊处理
        if cluster.slug in selections.merged_into:
            continue  # 已合并到别处

        query = selections.get_query_for(cluster) or derive_query(cluster)
        categories = dominant_categories(cluster, state.paper_pool)

        topics.append({
            "name": selections.labels.get(cluster.slug, cluster.display_label),
            "query": query,
            "categories": categories,
            "research_profile": cluster.description,
        })

    return {
        "topics": topics,
        "filter": {
            "relevance_threshold": selections.threshold,
            "borderline_min": max(selections.threshold - 2, 2),
        },
        # ... 其他字段保留 config.yaml 原值或默认
    }
```

### Query 派生规则
每簇的 query 由 LLM 一次 Flash 调用生成：输入 `cluster.display_label + description + representative titles + categories`，输出 ArXiv 搜索语法，目标"能把这个簇新论文大部分捞到"。

**不直接用 `cluster.label`**——label 是人读的，query 是 ArXiv 的。

### Categories 派生
`dominant_categories` = cluster 内论文的 categories 频次 top 2–3。

## Atomic 写入

```python
def write_config_atomically(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp.replace(path)            # atomic on POSIX
    # Windows：tmp.replace(path) 在 Python 3.3+ 也是 atomic
```

避免写到一半 crash 留下破损 config。

写入前**备份旧 config**到 `config.yaml.bak.<timestamp>`。

## Seed SOTA

这是 Configure 的**副作用**：对每个选中簇的 anchor 论文做深读，把实验数据写入 SOTA leaderboards。

```python
async def seed_sota(selections, state):
    all_anchors = []
    for slug in selections.selected:
        cluster = find_cluster(slug)
        n = selections.anchor_count.get(slug, 3)
        anchors = pick_anchors(cluster, state, n=n)  # 引用 × 中心性
        all_anchors.extend(anchors)

    # 并发深读，限制并发数
    semaphore = asyncio.Semaphore(3)
    async def read_one(arxiv_id):
        async with semaphore:
            return await deep_reader.read_paper(arxiv_id, ...)

    readings = await asyncio.gather(*[read_one(a) for a in all_anchors],
                                      return_exceptions=True)

    # 把成功的结果写入 SOTA knowledge base
    sota_kb = SOTAKnowledgeBase(...)
    for r in readings:
        if isinstance(r, Exception):
            continue
        await sota_kb.update_from_reading(r)
```

### 和 Explorer 的 read_paper 关系

**区别**：
- Explorer 的 `read_paper` action：探索性，只更新 state，不写 DB
- Configure 的 seed：权威性，写入主 DB 的 `deep_readings` 表 + SOTA leaderboards

**复用**：两者都调同一个 `DeepReader`（3-pass Pro）。只是入口和落盘目的地不同。

### 失败处理
- 单篇 anchor 深读失败 → 跳过，log warning
- 50% 以上 anchor 失败 → Configure 整体失败，但 **config.yaml 保留**（已 atomic 写入）
- 用户可以手动重跑 `python run.py seed-sota` 补齐（新命令）

## Refine 模式下的 Configure

如果 config.yaml 已存在（refine 场景）：

1. 读现有 config
2. Diff：新 field_map 的 topics vs 现 config.topics
3. 对新增 topic：默认加入 selected
4. 对消失的 topic：默认**保留**（用户可能仍想追踪），标注 "field map 不再覆盖此 topic"
5. 用户 accept → 写合并后的 config

展示格式：
```
Changes vs current config.yaml:
  + vln-ce (new sub-area, 35 papers)
  + video-nav (new sub-area, 12 papers)
  ~ zero-shot-objnav: 22 → 45 papers
  - slam-classical: no longer in field map (kept in config)

[Enter] apply changes  [e] edit  [q] cancel
```

## 测试

- **派生逻辑（确定性）**：给 fixture FieldMap + ConfigureSession，断言 `derive_config()` 输出精确 yaml 结构
- **Atomic 写入**：mock IO 错误在 `tmp.replace` 前，确认原 config 未动
- **命令解析**：每种命令给 3–5 个输入字符串，解析后断言 Session 状态
- **Merge / Split**：集成测试（需 LLM），走 T2 路径

## 开放点（实装时再定）

- Merge 时合并后的新 slug 命名规则（目前是 `slug1+slug2`，可能要 LLM 另起名）
- 用户 rename 后的 display_label 是否推到 config.yaml 的 `name`（倾向 yes）
- `preview` 的输出格式：YAML diff 还是全文？（倾向 diff）
- 命令模式退出时若有未保存更改，是否二次确认
