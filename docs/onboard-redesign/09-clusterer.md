# Clusterer: 聚类算法与 Slug 生成

> Explorer 的结构化视图层。每次 `cluster_refresh` 把当前 pool 聚类并用 LLM 生成 slug/label。
> 产物是 `ClusterSnapshot`，所有下游（Planner / Synthesize / Configure）都依赖它。

## 职责范围

Clusterer **只做一件事**：把当前 paper_pool 聚成几组语义相近的论文，每组有可读的 slug、label、代表论文、共享 benchmark 等表征。

Clusterer **不**负责：
- 决定什么时候聚类（Planner/Spec 管）
- 判断聚类质量是否足够（Coverage audit 管）
- 处理用户编辑簇（Configure 管）

## 算法流水线

```
Input: state.paper_pool, state.cluster_snapshot (上一次，可选)
  ↓
1. 拉取 embeddings（从 ChromaDB）
  ↓
2. (可选) UMAP 降维
  ↓
3. HDBSCAN 聚类
  ↓
4. 每簇计算 centroid / representatives / counters 派生
  ↓
5. LLM 批量生成 slug/label/description（带上一次 slugs 作 context）
  ↓
6. 处理 slug collision（极少见，LLM 已避免但兜底）
  ↓
7. 构造 ClusterSnapshot
  ↓
Output: 新的 ClusterSnapshot，更新 state.paper_pool[].cluster_id
```

## HDBSCAN 参数

```python
# src/explore/cluster/config.py

CLUSTER_MIN_SIZE = 5                    # 小于此大小不成簇
CLUSTER_MIN_SAMPLES = 3                 # 越大越严格，噪声越多
CLUSTER_METRIC = "cosine"               # 对 text embedding 天然
CLUSTER_SELECTION_METHOD = "eom"        # excess of mass，默认

MIN_POOL_SIZE_FOR_CLUSTERING = 20       # pool 小于此不聚类
```

**选择理由**：
- `min_cluster_size=5`：池子 100–300 篇时，每簇至少 5 篇才算结构，否则是噪声
- `metric="cosine"`：embedding 向量间余弦距离是标准做法
- `MIN_POOL_SIZE=20`：小于这个规模时聚类无意义，cluster_refresh 返回 `insufficient_papers`，state.cluster_snapshot 保持 None

`min_cluster_size` 可能需要根据实际跑出来的效果调整，先用 5 起步。

## 降维：UMAP？

**v1 不用 UMAP**。理由：
- Gemini embedding（768 维）在 HDBSCAN 下直接跑能出合理结果
- UMAP 引入新依赖 + 一个 stochastic 步骤，可复现性打折扣
- v1 要的是"能跑、可调试"，不是"最优聚类"

若实际跑下来簇结构混乱（太多噪声 / 假合并），v2 加 UMAP（n_components=10, random_state=42）作为 HDBSCAN 前置步骤。

## ChromaDB 集成

```python
async def fetch_pool_embeddings(state, chroma_client) -> Tuple[List[str], np.ndarray]:
    """拉取 pool 里所有论文的 embedding。返回 (arxiv_ids, N×D matrix)"""
    collection = chroma_client.get_collection(f"explore_{state.metadata.run_id}")
    arxiv_ids = list(state.paper_pool.keys())
    result = collection.get(
        ids=[state.paper_pool[aid].embedding_id for aid in arxiv_ids],
        include=["embeddings"],
    )
    return arxiv_ids, np.array(result["embeddings"])
```

**Embedding 生成时机**：新论文加入 pool 时（`search` / `fetch_citations` / `fetch_related` action 的副作用），Executor 同步调 Gemini embedding API，写入 ChromaDB。Clusterer 只读。

## 派生视图：每簇的表征

HDBSCAN 给出 `labels_`（-1 为 noise，其余为 cluster id）。Clusterer 对每簇再算：

### Centroid & Representative
```python
def compute_cluster_representatives(cluster_members_emb, cluster_members_ids, n=5):
    """返回 (centroid_paper_id, top_n_representative_ids)"""
    centroid = cluster_members_emb.mean(axis=0)
    # 按余弦距离排序
    distances = cosine_distances(cluster_members_emb, centroid.reshape(1, -1)).flatten()
    sorted_idx = np.argsort(distances)
    centroid_paper_id = cluster_members_ids[sorted_idx[0]]
    top_n = [cluster_members_ids[i] for i in sorted_idx[:n]]
    return centroid_paper_id, top_n
```

### Density 分类
```python
def classify_density(hdbscan_probabilities: np.ndarray) -> str:
    """HDBSCAN 给每个点一个成员概率"""
    mean_prob = hdbscan_probabilities.mean()
    if mean_prob > 0.8:
        return "dense"
    elif mean_prob < 0.4:
        return "sparse"
    else:
        return "mixed"
```

### Shared benchmarks / top authors / year range
从 state.paper_pool 过滤到簇成员，汇总字段：

```python
def compute_cluster_metadata(cluster_members: List[PaperRecord]):
    benchmarks = Counter()
    for p in cluster_members:
        if p.skim:
            benchmarks.update(p.skim.benchmarks)
    shared_benchmarks = [b for b, cnt in benchmarks.most_common(5) if cnt >= 2]

    authors = Counter()
    for p in cluster_members:
        authors.update(p.authors[:3])  # 只数前 3 作者
    top_authors = [a for a, _ in authors.most_common(5)]

    years = [p.published.year for p in cluster_members]
    year_range = (min(years), max(years))

    return shared_benchmarks, top_authors, year_range
```

`shared_benchmarks` 要求至少在 2 篇论文里出现才算"共享"——单篇的 benchmark 不代表簇的共性。

## LLM 批量 Labeling

**关键设计**：所有簇的 slug/label **一次 LLM 调用**全部生成，让 LLM 同时看到：
- 本次所有待命名簇的代表论文
- 上次快照的 slugs 和它们的代表论文

好处：LLM 能自然保证 slug 不碰撞 + 智能决定是否继承上次 slug。

### Prompt 结构

```markdown
# Cluster Labeling

You are labeling research paper clusters produced by HDBSCAN.
Your job: for each cluster, produce a canonical `slug`, a human-readable
`display_label`, a one-sentence `description`, and indicate whether it
inherits from a previous-snapshot cluster.

## Slug Format (STRICT)
- Lowercase ASCII letters, digits, and hyphens only
- 1 to 3 tokens separated by hyphens
- Examples: `zero-shot-objnav`, `vln-ce`, `slam-classical`, `llm-planner`
- Bad: `ZeroShotNav`, `zero_shot_nav`, `zero-shot-object-goal-navigation`

## Stability Rule
If a new cluster's representative papers overlap ≥ 50% with one of the
previous-snapshot clusters, REUSE that previous slug (do not invent a
new one) and set `inherited_from_previous_slug` to the old slug.
Otherwise generate a new slug and set it to null.

## Uniqueness Rule
All slugs in your output must be distinct. If two new clusters would
naturally get the same slug, disambiguate the second with a differentiating
token (e.g., `vln` vs `vln-ce`).

## Previous Snapshot Slugs (for continuity)

{for each prev cluster:}
- slug: `{prev.slug}` ({prev.size} papers)
  representatives:
    - {arxiv_id}: {title}
    - ...

## New Clusters to Label

{for each new cluster:}
### Cluster {index} ({size} papers)
representatives:
  - {arxiv_id}: {title}
    abstract_excerpt: {first 300 chars}
  - ...
shared_benchmarks: {list}
top_authors: {list}
year_range: {y1}-{y2}

## Output

JSON array, one entry per new cluster, in the same order:

[
  {
    "slug": "...",
    "display_label": "...",
    "description": "One sentence on what this cluster represents",
    "inherited_from_previous_slug": "..." or null
  },
  ...
]
```

### Output 校验

LLM 输出经过：
1. **JSON schema 校验**（pydantic）
2. **Slug 正则校验**：`^[a-z0-9]+(-[a-z0-9]+){0,2}$`，不合法 → 截断 / 归一化（如替换 `_` 为 `-`、小写化）。两次尝试仍不合法 → fallback 为 `cluster-{index}`
3. **唯一性校验**：本次输出的 slug 彼此不重复，也不和 **未变更的** 继承 slug 冲突
4. **继承合法性校验**：若 `inherited_from_previous_slug` 非 null，必须真实存在于上一 snapshot

Fallback（LLM 输出有 bug 时）：
- 保留当前聚类结果
- Slug 用 `cluster-{n}`
- 标 warning 进 log 和 state.metadata
- 不中断 Explorer（不是 fatal error）

## Slug 继承的 Jaccard 校验（兜底）

LLM 应该自己判断继承，但我们额外做数值校验防止它乱继承：

```python
def validate_inheritance(new_cluster_ids: Set[str],
                         prev_snapshot: ClusterSnapshot,
                         claimed_inherit: str) -> bool:
    """claimed_inherit 是 LLM 声称继承自的旧 slug。用 Jaccard 验"""
    if claimed_inherit is None:
        return True
    prev_cluster = next((c for c in prev_snapshot.clusters if c.slug == claimed_inherit), None)
    if prev_cluster is None:
        return False
    prev_ids = set(prev_cluster.paper_ids)
    jaccard = len(new_cluster_ids & prev_ids) / len(new_cluster_ids | prev_ids)
    return jaccard >= 0.3    # 宽松阈值，避免误拒
```

Jaccard < 0.3 但 LLM 声称继承 → 视为 LLM 判断错误，强制改为 `inherited_from_previous_slug=None` 并重新生成新 slug（走 fallback 或重调 LLM 一次）。

## 失败模式与处理

| 场景 | 处理 |
|---|---|
| pool_size < 20 | 跳过聚类，snapshot 保持上次的；action result 返回 `insufficient_papers` |
| HDBSCAN 全判为 noise | 不产生簇，snapshot.clusters = []，noise_paper_ids = all；Planner 会看到继续探索的信号 |
| HDBSCAN 只产 1 簇 | 正常情况，意图很窄时会这样；不特殊处理 |
| LLM labeling 失败（JSON 不符 / 超时） | 重试 1 次；仍失败 → 用 fallback slug（`cluster-{n}`），标 warning，继续 |
| Embedding 拉取失败（ChromaDB 问题） | Q8 路径，fail fast 退出 |

## ClusterSnapshot 构造

```python
@dataclass
class ClusterSnapshot:
    snapshot_id: str                        # uuid
    generated_at: datetime
    generated_after_turn: int
    n_papers_at_time: int
    algorithm: str = "hdbscan"
    params: dict                            # 存本次用的 HDBSCAN params
    clusters: List[Cluster]
    noise_paper_ids: List[str]
    prev_snapshot_id: Optional[str]

def build_snapshot(
    pool: Dict[str, PaperRecord],
    hdbscan_result,
    llm_labels: List[LabelResult],
    prev_snapshot: Optional[ClusterSnapshot],
    turn: int,
) -> ClusterSnapshot:
    ...
```

## Structural Change Rate（派生）

不存盘，现场算：

```python
@property
def is_cluster_stable(state) -> bool:
    if state.cluster_snapshot is None or state.cluster_snapshot.prev_snapshot_id is None:
        return False
    curr_slugs = {c.slug for c in state.cluster_snapshot.clusters}
    prev_slugs = state._load_prev_snapshot_slugs()  # 从 checkpoint 史里找
    jaccard = len(curr_slugs & prev_slugs) / max(len(curr_slugs | prev_slugs), 1)
    return jaccard > 0.8
```

给 Spec 的饱和判断用。

## 运行时开销估计

| 步骤 | 时间（pool=200） |
|---|---|
| 拉取 embeddings | 50–100ms |
| HDBSCAN (768-dim × 200) | 200–500ms |
| 代表论文 / counters 派生 | 50ms |
| LLM batch labeling（Flash） | 3–8s |
| 写入 state | 10ms |
| **总计** | **4–10s/refresh** |

典型 run 5–10 次 refresh，聚类部分总耗时 1 分钟左右。

## 测试

### 确定性测试（纯算法部分）

```python
def test_hdbscan_produces_expected_clusters():
    """给定固定 embedding fixture，HDBSCAN 应产生期望簇"""
    embeddings = load_fixture_embeddings("three_clear_clusters.npy")
    labels, probs = run_hdbscan(embeddings)
    assert len(set(labels)) - (1 if -1 in labels else 0) == 3

def test_representative_selection_is_deterministic():
    emb = np.array([[1,0,0], [0.9,0.1,0], [0.7,0.3,0], [-1,0,0]])
    ids = ["a", "b", "c", "d"]
    centroid_id, reps = compute_cluster_representatives(emb[:3], ids[:3], n=3)
    assert reps == ["a", "b", "c"]  # 按距离中心近→远
    assert centroid_id == "a"

def test_insufficient_pool_returns_empty():
    """pool 15 篇时 cluster_refresh 返回 insufficient_papers"""
    state = make_state(pool_size=15)
    result = await clusterer.refresh(state)
    assert result.status == "insufficient_papers"
    assert state.cluster_snapshot is None  # 不更新
```

### 非确定性测试（LLM labeling 部分）

按 08 的三档测试法：

```python
# T1 结构化
def test_slug_format_valid(labeling_fixtures):
    for fix in labeling_fixtures:
        result = label_clusters(fix.clusters, fix.prev_snapshot)
        for label in result:
            assert re.match(SLUG_PATTERN, label.slug)

# T1 唯一性
def test_slugs_unique_in_batch():
    result = label_clusters(mock_two_similar_clusters())
    slugs = [l.slug for l in result]
    assert len(slugs) == len(set(slugs))

# T2 继承行为
@pytest.mark.llm
def test_high_overlap_reuses_slug():
    """papers 90% overlap 时应继承旧 slug"""
    fix = load("high_overlap_with_prev.py")
    results = run_n_times(lambda: label_clusters(fix.clusters, fix.prev), n=5)
    inherit_rate = sum(1 for r in results if r[0].inherited_from_previous_slug == "vln-ce") / 5
    assert inherit_rate >= 0.8   # 至少 80% 时候继承

# T2 语义合理
@pytest.mark.llm
def test_slug_reflects_content():
    """VLN 论文组应产出 vln-* 类 slug"""
    fix = load("vln_cluster.py")
    results = run_n_times(lambda: label_clusters(fix.clusters, None), n=5)
    vln_like = lambda r: "vln" in r[0].slug or "navigation" in r[0].slug
    assert_pass_rate([r[0] for r in results], vln_like, STRONG_PREFERENCE_RATE)
```

### Fixture 样例

- `three_clear_clusters.npy`：人工构造的三簇 embedding（单元测试算法用）
- `high_overlap_with_prev.py`：新 cluster 与 prev 论文重合 90%，测继承
- `low_overlap_with_prev.py`：重合 20%，测不继承
- `collision_potential.py`：两个新 cluster 都偏 VLN，测唯一性
- `single_cluster_narrow_intent.py`：意图很窄，聚出 1 簇
- `all_noise.py`：embedding 完全散乱，期望全是 noise

## 开放点（实装时再定）

- **Snapshot 数量上限**：checkpoint 里要保留所有历史 snapshot 吗？每次 diff 只需要上一个；建议保留 `snapshot_{last-1}` 作 diff 参考，更老的进 log 文件
- **Representative 数量 n**：默认 5，若 field_map 渲染需要更多可调
- **Benchmark counter 的 alias 归一化时机**：在 skim_abstract 时做，还是 cluster 派生时做？倾向 skim 时做，派生时直接读
- **多 run 的 ChromaDB collection 策略**：已在 05 OP-4 记录，方案 A（每 run 一 collection）
