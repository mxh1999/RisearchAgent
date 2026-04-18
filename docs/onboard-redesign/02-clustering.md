# 聚类在 Explorer 中的角色

## 核心作用：给 agent 一个随时能看的领域结构快照

聚类**不是**为了精确分类，**是**为了让 Explorer、Synthesizer、用户三方都不再面对一坨扁平的论文池，而是面对一张有结构的地图。精度 80% 够用。

## 三重效果

### A. 循环内：驱动 Explorer 自己

**1. Planner 选 action 的依据（结构化决策）**

| 观察状态 | Planner 的 action |
|---|---|
| 簇 c2 只有 4 篇，都 2024 | `search(c2.label, year: 2019-2022)` 找经典基线 |
| 簇 c0 的 benchmark_counter 空 | `read_paper(c0.centroid)` 精读一篇 |
| noise 里出现 6 篇语义相近的 | `search(noise_group.inferred_label)` 可能是新子区 |
| 簇 c1 全是同一个作者 | `search(author: X)` 看该组其他工作 |
| 所有簇尺寸 > 15 且稳定 | `synthesize_partial()` |

**2. 生成针对性 query**

用户意图 "embodied navigation" 宽泛。针对 c2 扩展时，query 生成器只读 c2 代表论文 + 标签，产出窄 query：
> `"LLM-based high-level planner" AND ("object goal navigation" OR "embodied agent")`

聚类把宽问题切成可定向追踪的窄问题。

**3. 停止条件的数值信号**

- 新论文落入已有簇的比例（> 90% 持续 2 轮 → 饱和）
- 簇结构稳定度（簇数不变、成员变动 < 10% → 稳定）
- 是否还在产生新噪声簇（连续 2 轮无新噪声子群 → 无新子领域）

**客观数值，不问 LLM 主观判断。**

### B. 合成时：塑造产物

**4. Field map 的 Sub-areas 章节直接来自簇**

一个簇 = 一个 section。Synthesizer 不用从 147 篇 abstract 自己 "理解领域分几支"，只需对每个簇（22 篇）写一段描述——任务降维，质量天花板高一个台阶。

**5. Benchmark 归属到子区**

无聚类：`HM3D 出现在 37 篇` —— 信息量低
有聚类：`子区 A (ObjNav): HM3D (37/40)，子区 B (VLN): R2R (28/35)` —— 可行动

**6. Anchor paper 按每簇选，不按全局选**

全局 top-10 可能全来自最火子区，其他子区 SOTA 表空。按簇 top-2-3 覆盖均衡。

**7. Coverage 自审结构化**

| 问题 | 从哪答 |
|---|---|
| 领域分几支？ | `clusters[].label` |
| 每支主导 benchmark？ | `clusters[].shared_benchmarks` |
| 每支经典基线？ | `clusters[].year_range` + 高引 |
| 每支代表作者？ | `clusters[].top_authors` |

任一字段不达标不能停。

**8. 派生 config.yaml topics**

```
cluster → topic:
  name:       cluster.label
  query:      generate_query_from(cluster.representative_papers)
  categories: dominant(cluster.papers.categories)
  profile:    cluster.description
```

**9. 校准 relevance_threshold**

Explorer 结束后自然分层的论文池：
- 簇心 → 毫无疑问相关（10）
- 簇边缘 → 中等（6–7）
- 噪声 → 低（3–4）

跑一次 RelevanceJudge 反推 threshold 合理值。

### C. 用户交互：让操控有颗粒度

**10. 用户在簇级别编辑**

```
☑ Zero-shot Object Goal Navigation (22)
☐ SLAM + classical planning (12)
☑ VLN (35) [✂ 拆分]
☑ LLM-as-planner (18)
```

决策单元的粒度匹配人的认知粒度。

**11. Refine 模式的 diff 有意义**

- 簇 c0 从 22 → 45（升温）
- 新簇 c5 出现：Video-language navigation（新支）
- 簇 c2 从 12 → 13（冷门）

diff 直接对应 "领域发生了什么变化"。

## 具体方法

- Embedding：Gemini embedding（项目已有能力）
- 算法：HDBSCAN 或层次聚类，**不预设 K**
- LLM 后处理：给每簇取标签 + 描述 + 判断是否合并相邻簇

## 与其他信号交叉验证

真正的子区应在三维度都有聚集：
- Embedding 邻近
- Benchmark 重合
- 作者/机构重合

三者都命中 → 强证据；只有 embedding 聚但 benchmark 全散 → 可能是假阳性。

## 不做什么

- 不追求最优簇数
- 不强行把每篇归类（噪声保留）
- 不在簇内自动子聚类（2 层够用）
- 不用 topic modeling（LDA 类），embedding + 聚类效果好得多

## 产物结构

```json
{
  "generated_at": "...",
  "n_papers": 147,
  "clusters": [
    {
      "id": "c0",
      "label": "Zero-shot Object Goal Navigation",
      "description": "...",
      "size": 22,
      "centroid_paper": "2312.xxxxx",
      "representative_papers": ["2401.xxxxx", ...],
      "shared_benchmarks": ["HM3D-ObjNav"],
      "top_authors": [...],
      "year_range": [2022, 2025],
      "density": "dense"
    }
  ],
  "noise": ["2304.xxxxx", ...]
}
```
