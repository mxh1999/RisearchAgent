# Onboard 重设计：总览

> 讨论中的设计文档。尚未定稿，**不要据此开发**。

## 背景

当前 `src/onboard/` 是一个 "结构化访谈 + 搜索辅助" 的对话系统，基于 Gemini Pro + AFC：
- 多轮一问一答，每轮用户对 3–5 篇论文即时反馈
- LLM 自由调用 search / fetch / read / save 四个 tool
- 最终产出一段 150–250 字的 `research_profile` + `topics` + `relevance_threshold` 写入 `config.yaml`

## 问题诊断（设计层面，非实现层面）

1. **信息流向反了**：假设用户已知道自己要什么；但目标用户是"新研究生"，他们恰恰不知道领域长什么样
2. **产物错位**：产物是 profile 段落，应该是**有证据的领域地图（field map）**
3. **交互节奏错位**：乒乓式对话，用户是 bottleneck；应该 Agent 独立勘探 → 汇报
4. **探索策略缺失**：LLM 即兴搜索，没有扇出策略、饱和判据、覆盖检查
5. **任务耦合**："理解领域" 和 "配置 tracker" 两件事混在一起，两头都不到位
6. **无状态、无证据**：产物不可审计，refine 模式只能再聊一遍

## 目标形态：Deep-research 式 Onboard

```
Intent (2 min, 用户)
  → Explorer (10–15 min, Agent 独立勘探, 产出 field_map.md + state.json)
  → User reviews field_map.md, 勾选 sub-areas/benchmarks
  → Configure (派生 config.yaml + seed SOTA from anchor papers)
```

两个核心变化：
- **Explorer 阶段异步、自主**：不需要用户陪跑
- **产物是 field map**：带引用的领域地图，用户在地图上做决策

## 与 RTI 的关系（yrc-better/RTI）

RTI 是**depth-research 工具**（深读单篇），与我们的**breadth-exploration 工具**互补：

- Explorer 产出 field map → 用户挑 1–2 篇重点 → RTI 做深度解读
- 两者不应互相替代

## 文档结构

- `00-overview.md` — 本文件
- `01-explorer-design.md` — Explorer agent 的核心设计
- `02-clustering.md` — 聚类在 Explorer 中的角色与使用
- `03-spec-based-planner.md` — 基于 AgentSpec 思想的 planner 设计
- `04-open-design-questions.md` — high-level 设计决议（10 Q 全部已敲定）
- `05-state-schema.md` — ExplorationState 的完整字段 schema
- `06-action-system.md` — 9 种 action 的类型契约、校验分层、执行模型
- `07-spec-rules.md` — Spec 规则层 DSL、11 条 v1 规则、评估器与测试策略
- `08-planner-prompt.md` — Planner 的 prompt 模板、I/O 契约、三档测试方法
- `09-clusterer.md` — HDBSCAN 参数、slug 批量生成与继承校验、失败模式
- `10-synthesize.md` — state → field_map.md 的两阶段合成（LLM + 模板渲染）
- `11-citation-provider.md` — Semantic Scholar 集成 + 降级抽象 + 速率限制
- `12-configure.md` — Configure 命令模式、派生 config.yaml、seed SOTA

## 核心设计原则

**Agent 的目标是替用户梳理，而不是逼用户做选择。**
用户未必了解该领域——事实上 onboard 的目标用户正是"不了解"的新研究生。所以：
- 所有阶段都要给出 **合理默认值**，用户只在想调时才调
- Configure 应该感觉像"review 并微调"，而不是"填 10 个字段"
- Agent 遇到模糊时应做出合理选择并解释理由，**不要轻易反问用户**
- 向用户提问应是稀少的、有高价值的，不是对话式的频繁确认

**硬性与弹性分层：**
- Spec 层只管硬性不变量（数值比较、计数器、字段存在性等可符号化的判断）
- Planner 层负责所有弹性决策（方向选择、query 生成、策略调整）
- Coverage Audit 负责语义深审（方向是否偏离、覆盖是否合格）
- Configure 阶段负责用户品味（筛选、阈值、标签）
- **弱模型不 veto 强模型**：spec 不引入 LLM predicate（架构约束，永久）

## 当前状态

**已有共识**：
- 分 4 阶段（Intent / Explore / Synthesize / Configure）
- Explorer 要独立运行、有 exploration state、有饱和停止条件
- 产物是 field map（带引用）
- 聚类用于驱动 planner、支撑停止条件、塑造产物
- Planner 采用 spec-based 模式：LLM 自由提议 + 规则在运行时校验
- Synthesize 独立于 Explore（不合并）
- Synthesize → Configure 之间有**隐式反馈回环**（方案 C）：用户可选继续 Configure / 反馈后增量 re-explore / 放弃
- Refine 不是独立模式，而是三阶段可单独触发的自然产物
- Configure 允许簇级轻量编辑（拆/合/改名/删），但不触发重探索

**待敲定的 high-level 问题**：见 `04-open-design-questions.md`
