# Systematic Coverage Problem & Survey-First Bootstrapping

> **状态**：问题陈述 + 设计思路 + 渐进路线图。**不是定稿 spec**；v0.1 spike 跑出真实数据后再写完整 design。
>
> **前序**：见 06-action-system / 07-spec-rules / 09-clusterer / 10-synthesize。本文是这些已落地模块的"上层修补思路"。

## 1. 问题陈述

### 1.1 现象

实跑 `intent="embodied navigation"`、`seed=[2604.14141, 2507.04047]`、`action_budget=200`、`time_budget=3600s`、`enable_read=true`，得到：

| 维度 | 结果 |
|---|---|
| pool | 408 papers |
| sub-areas | 5 |
| dominant benchmarks | 5（`HM3D=3, MP3D=2, KITTI=1, TUM=1, Habitat=1`） |
| classic baselines | 3（全是 SLAM 方向） |

**症结**：5 个 sub-area 中 3 个是 SLAM/3D-recon（`streaming-3d-reconstruction` / `gaussian-splatting-slam` / `dynamic-rgbd-slam`），不是 embodied navigation。canonical benchmarks（R2R / RxR / REVERIE / CVDN / VLN-CE / GOAT-Bench）几乎全部缺失——其中 GOAT-Bench、HM3D-OVON、ObjectNav Revisited 三篇**已经在 pool 里**但**没有被 skim**。

### 1.2 把预算 8× 后还是同样的失败

`action_budget=25 → 200` 增加了**深度**（每个方向爬得更深、有了 GS-SLAM 等经典）但**宽度**几乎没变：5 个 sub-area 的方向分布和预算 25 时一致。Coverage 报告反复显示同样的 gap，但 planner 从未自我怀疑"是不是大方向跑偏了"。

> 加预算让 planner 更勤奋地填错答案，并没有让它怀疑自己是不是答错了题。

### 1.3 根因（设计层面）

1. **种子论文（2604.14141, 2507.04047）含 3D 重建/grounding 元素** → embedding 把 cluster 中心拉到 3D-recon 一侧
2. **第一次聚类形成后，coverage_audit 报告"streaming-3d-recon 缺 classic baselines"** → planner 用剩余预算补这些 cluster 的 gap（合规！）
3. **没有任何机制**提醒 planner："你最初的 intent 是 navigation，VLN/ObjectNav 那边一篇 R2R/REVERIE 都没爬到"

也就是说：**planner 的探索目标会随 cluster 形成漂移到 cluster 维度，丢失 intent 维度**。当前架构里，intent 只在 Stage 0 用一次（生成首批 query），之后就再没出现过——planner 从此忘记 intent 的存在。

## 2. 借鉴：主流 deep-research / survey agent 的 cold-start 模式

调研了 STORM、Co-STORM、SurveyForge、AutoSurvey、OpenAI/Gemini/Perplexity Deep Research。共同模式：

> **没有任何系统让 LLM 直接列 canonical benchmarks/baselines**。全部都"先调研结构再展开"。

| 系统 | 关键机制 | 我们能借鉴 |
|---|---|---|
| **STORM** | 检索 Wikipedia 上**相似主题**的文章，挖"perspectives"驱动独立对话 | "survey-before-outline" 思想 |
| **Co-STORM** | 圆桌制 + Moderator 专门发掘"被搜到但没讨论"的内容；动态思维导图作为 coverage 对象 | **Moderator pattern**——用 retrieved-but-undiscussed 当 gap signal |
| **SurveyForge** ⭐ | 双库：60 万 paper + 2 万人写的 **survey outlines**；冷启动时检索邻近主题的 survey 大纲作为 few-shot exemplar | **survey-grounded anchor**：直接挖现有 survey paper 的章节当 taxonomy |
| **OpenAI/Gemini/Perplexity DR** | 先 clarify + 出 plan，让用户编辑确认 → 锁定 plan 当合约 | **plan-as-contract**：anchor 列表是这次 run 的合约 |
| **Microsoft AI Co-Scientist** | hypothesis generation 场景，Elo 锦标赛 | 不直接相关 |

**最核心的洞察**（SurveyForge）：人类专家写的 survey 已经替我们做了 anchor discovery。我们要做的不是让 LLM 凭空猜，而是**找到 1-3 篇该领域的 survey paper、挖它们的章节标题**。

## 3. 设计原则

1. **Intent 必须有持久存在感**——不能只在 Stage 0 出现一次。Anchor coverage table 注入每一次 planner prompt
2. **Anchor 来自外部 evidence，不是 LLM 内部知识**——优先 survey paper > seed paper intro > LLM best-effort（带 confidence 标记）
3. **Anchor 是 plan 但不是死契**——可被 Moderator 发现的新方向 evolve（新增 anchor）；用户砍掉的方向用 probe 机制远程哨兵
4. **不引入新阶段**——在现有 Intent → Explore → Synthesize → Configure 框架内实现，避免破坏 Q1 已敲定的边界
5. **rule 数克制**——不每个 case 加一条 rule；尽量让信号通过 prompt 注入流向 planner，spec 只负责硬阈值

## 4. 渐进路线图

每一步都能跑一次"embodied navigation"基线 + 1-2 个其他 intent，**用真实数据验证**再进入下一步。避免一次写 16 条 rule 才发现某条根本没必要。

### v0.1: Survey-grounded first-batch queries（不锁死 anchor）

**目标**：只改 Stage 0，看是否仅此一项就修复路径漂移。

**改动**：
- 新增 `src/explore/survey_bootstrap.py`：用 intent 在 ArXiv 搜 `"<intent>" survey OR review OR taxonomy`，按 `recency × log(citation) × title_fit` 排序取 top 3-5 篇
- 抽 abstract（必做）+ section heading（best-effort）→ LLM 聚合出"候选 sub-area 清单"
- 用清单生成首批 N 个 search query（每个 sub-area 一个 query），注入 explorer 的 turn 0
- **不引入 anchor 状态、不改 prompt、不加 rule**

**验证**：跑 embodied navigation，看：
- canonical benchmark（R2R / REVERIE / GOAT 等）是否进 pool
- sub-area 分布是否更平衡
- 总耗时是否仍可控（增加 30-90s）

**成功判据**：embodied navigation 跑出来 dominant_benchmarks 至少包含 R2R / REVERIE / GOAT 中两个，sub-area 中 navigation 类 ≥ 60%。

**如果 v0.1 已经够好**：v0.2/0.3 可能不需要——这是渐进路线的好处。

### v0.2: Anchor coverage table 注入 prompt（B 的核心）

**目标**：让 intent 维度在每一次 planner 决策时都可见。

**改动**：
- v0.1 的"候选 sub-area 清单"升格为正式 `Anchor` 对象（pydantic schema）
- Stage 0 加用户确认 UI（add/drop/edit/toggle）
- `state.anchors` 作为 frozen 状态
- 每次 planner prompt 注入 anchor coverage table（"VLN: 12 papers, R2R seen; ObjectNav: 0 papers, missing HM3D-ObjectNav..."）
- **不加新 rule**（继续观察 LLM 看到 coverage table 后的自然行为）

**验证**：相比 v0.1 看 anchor 覆盖率提升幅度，看 LLM 是否自发去补漏的 anchor。

### v0.3: Spec rule + Moderator + Synthesizer 改动

**目标**：当 v0.2 的"软提示"不够时，补硬约束。

**改动**：
- 加 `anchor_coverage_required_before_stop`（block on stop, escalate after 3 retries）
- 加 Moderator gap detector（详见 §6.1）
- Synthesizer 默认以 anchor 为骨架（详见 §6.2）
- 配套 rule + 测试

**验证**：相比 v0.2 看 stop 时机是否更合理、漏发现的方向是否被补。

## 5. 已敲定的设计选择

### 5.1 Concern 1（鸡生蛋）：周期性 probe search

> 用户砍掉的低 confidence anchor、或 LLM 在 Stage 0 漏掉的方向，Moderator 永远等不到 ≥3 篇支持触发。

**决议**：用**周期性 probe search** 当远程哨兵。

机制：
- Stage 0 a-5 用户编辑后，**保留两份清单**：
  - `active_anchors`：用户保留的（驱动主探索）
  - `dormant_anchors`：用户砍掉的 + Stage 0 低 confidence 但 LLM 提过的（不驱动主探索，但记着）
- 每隔 N turn（比如 N=20），spec rule force 一次 `search` action with query = 某个 dormant anchor 的 alias，**只爬不主动深挖**
- 如果 probe 拉回的论文里有 ≥K 篇被 cluster 收编（不是 noise），说明这个方向真实存在 → 自动升格为 active anchor + 通知用户（写到 state metadata，synthesize 时显示）

这个机制和"agent 不是一次 onboard 完了就结束、以后定期搜索最新 paper 更新"的产品定位是一致的——probe 是 onboard 内的小型 future-update。

### 5.2 Concern 5（anchor vs cluster 冲突）：新增 anchor

> Synthesizer 默认以 anchor 为骨架——但如果 HDBSCAN 跑出一个 anchor 没覆盖的 cluster（比如 80 篇 NeRF-based mapping）怎么办？

**决议**：**新增 anchor**。

机制：
- Synthesizer 在生成 FieldMap 之前先运行 `reconcile_anchors_with_clusters(state)`
- 对每个未被任何 active anchor 覆盖的 cluster：
  - 若 size ≥ M（比如 5 篇）→ 升格为新 anchor，标 `provenance="cluster-discovered"`
  - 若 size < M → 标"附加发现"放 FieldMap 末尾的 `Notes` 段，不形成正式 sub-area
- 升格的新 anchor 写回 state，下次 refine run 时纳入 active

这样 anchor 既不是"用户输入即真理"也不是"cluster 即真理"——是两者的 reconcile。

## 6. Open Questions / Known Risks

### 6.1 Moderator 的精确定义

**Retrieved terms** 来自 (a) `paper.skim.benchmarks`，(b) abstract 上的 NER-style lexical 抽取（大写专名 + 数字 + 长度阈值）。

**Discussed terms** = `∪ active_anchors.canonical_benchmarks ∪ already-skimmed benchmarks`。

**Gap term** = `retrieved \ discussed`，加：
- 频次阈值（≥ 3 篇独立支持）
- LLM-confirm 一次（这真是个 benchmark/concept 名吗）
- 与 dormant anchor 的合并逻辑

**还没想清楚的**：
- 频次阈值 3 是不是太低 / 太高（要数据）
- LLM-confirm 的成本（per-run 一次 batch Flash）和缓存策略
- gap term 升格为新 anchor 的条件（vs 只是触发一次 search）

### 6.2 Synthesizer 的 conflict resolution

§5.2 决定"未被覆盖的大 cluster 升格为新 anchor"，但**升格后的 sub-area 在 FieldMap 里怎么标注**还没定：

- 选项 A：和原 anchor 平级展示（用户看不出区别）
- 选项 B：单独章节"Discovered during exploration"
- 选项 C：A 的样式 + tag 标记 `[discovered]`

倾向 C，留给 v0.3 实现时定。

### 6.3 PDF heading 提取的可行性没验证

v0.1 假设我们能从 survey PDF 稳定抽 h1/h2。当前 `deep_reader.py` 用 PyMuPDF + LLM-based section parsing 整篇一起喂——**不是 heading-only 模式**。靠字号启发式 derive heading 在不同排版下未必稳。

**v0.1 实施前必须做的 5 分钟 spike**：抓 1-2 篇真 embodied nav survey PDF，看 PyMuPDF 输出能否可靠 derive h1/h2。如果不行，v0.1 退化到只抽 abstract（成本最低，但召回降一档）。

### 6.4 没 survey 的领域怎么办

降级链：
1. 找到 ≥1 篇 survey → survey-grounded mode（推荐路径）
2. 没 survey 但有 seed paper → seed paper intro mode（**质量明显下降**——intro 通常只引相关 5-10 篇，不构成领域全貌）
3. 都没 → LLM-best-effort mode（**整个机制退化为 LLM 凭空猜，标 low confidence**，实际上和当前没改一样）

**承认这个事实**：survey-first 不是万能解。在小众领域，agent 的能力上限就是 LLM 的训练知识，和今天没差别。

### 6.5 单 intent 验证不足

所有诊断数据来自 "embodied navigation" 一次跑。这个 intent **热门、广义、多 sub-area 并存**，可能让漂移问题特别明显。在 v0.1 spike 之前，建议跑 1-2 个其他 intent 验证 systematic 是否成立：

候选：
- `"implicit neural representations"`（中等广义）
- `"test-time training"`（窄但活跃）
- `"diffusion model alignment"`（窄）

这次跑下来如果某些 intent 几乎没有漂移问题，那 v0.1 的优先级和 ROI 都要重估。

## 7. 前置：先扫的基础 bug

在大改之前先收尾几个本周发现的小 bug：

1. **`time_budget` 没 spec rule 强制**：`action_budget=200` 跑 5605s，超了 3600s 配额 2000s。靠 `action_budget` 救了场。需要加一条 `time_budget_exceeded` rule（force stop）。
2. **`stop` 行为的 `claimed_reason` 校验**：planner 自己说 `budget_exhausted` 时如果 actions/time 都没满应该 force-allow 还是 block？目前是直接 force-allow。
3. **skim 抽出 `benchmarks=0` 频繁**：abstract 没显式提 benchmark 名时整个 paper 的信号丢失。是否应该改 prompt 让 skim 也吐"潜在 benchmark"（即使没明说）？

这些不影响本文设计但影响 v0.1 spike 的数据可信度。

## 8. 决策摘要

| 项 | 选择 |
|---|---|
| Doc 路线 | A（先轻量问题陈述 + 思路 + 路线图，不一次写到 v1.0 spec） |
| Anchor 来源 | survey paper section/abstract（首选）→ seed paper intro → LLM best-effort（降级链） |
| Anchor 是否锁死 | 半锁：active anchor 锁，dormant anchor 周期性 probe，新 cluster 可升格 |
| Anchor vs cluster 冲突 | 大 cluster 升格为新 anchor，小的进 Notes |
| Rule 数控制 | 渐进添加，能用 prompt 注入解决就不加 rule |
| 实现顺序 | v0.1 (Stage 0 改) → 真实数据验证 → v0.2 (anchor in prompt) → v0.3 (spec rule + Moderator) |
| 单点假设验证 | v0.1 之前跑 2 个其他 intent 确认 systematic |
| PDF heading 抽取 | v0.1 之前 5 分钟 spike 验证可行性 |

## 9. 不在本文范围

- Anchor 的具体 pydantic schema（v0.2 时定）
- Stage 0 的具体 prompt 模板（v0.1 实现时定）
- Moderator 的精确算法（v0.3 时定）
- Synthesizer 的新 sub-area 标注样式（v0.3 时定）
- 现有 11 条 rule 中是否有应该改写或废除的（v0.3 时定）
