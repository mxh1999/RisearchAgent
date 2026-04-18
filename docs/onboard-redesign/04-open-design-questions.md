# 待敲定的 High-level Design Questions

> 这些是还未形成共识的设计选择。应**先于任何 low-level 实现** 决策。

## Q1. Onboard 的四阶段边界是否成立？✅ 已敲定

```
Intent → Explore → Synthesize → Configure
                         ↓
                    [反馈回环：可跳回 Explore 增量]
```

**决议**：
- 四阶段边界成立
- Synthesize 独立于 Explore（失败成本不对称 / 迭代速度不对称 / 受众不同）
- Synthesize → Configure 间采用**隐式反馈回环**（方案 C）：用户可选 Configure / 反馈后增量 re-explore / 放弃。不升格为独立 Review 阶段
- Refine 不是独立模式，而是三阶段可单独触发的自然产物
- Configure 允许簇级轻量编辑，不触发重探索

**核心原则（从 Q1 讨论中浮现）**：
> Agent 的目标是替用户梳理，不是逼用户做选择。用户未必了解该领域。

影响后续所有 Q：给默认值 > 问用户。

## Q2. Explorer 的自主度 ✅ 已敲定

自主度拆为三个独立维度：

| 维度 | 决议 |
|---|---|
| **A. 是否打扰用户** | **零打扰**。Explorer 不问任何问题；系统性故障（网络/配额/API）报错退出并保留 checkpoint |
| **B. 是否可观察** | **可观察但不展示中间结论**。只显示过程指标（数量 / 饱和度 / 耗时 / 当前 action 名），不展示簇内容、具体论文、临时判断 |
| **C. 是否可干预** | **只支持 Cancel**（Ctrl+C 落盘退出）；不支持 Pivot。方向调整走 Q1 反馈回环 |

核心原则：**不用片面结论打扰用户，用户的选择在 Configure 阶段统一做**。

## Q3. 用户种子论文（Intent 阶段）✅ 已敲定

**决议：方案 C，可选接受种子论文**。

**UI 态**：默认只问意图，种子论文是可选 advanced input。措辞要让用户明确"不填是正常的"，避免心理上推向"该填点什么"。

**Explorer 启动策略**：
- 无种子：从 LLM 改写的初始 query 起步
- 有种子：`fetch_citations(seeds)` 作为首个 action，用引用图启动

**关键校准（从讨论中浮现）**：
> 按经验，用户给的种子多是 **他最近在读的论文**，而非领域经典论文。

这意味着：
- **不要把种子当 classic baseline / authoritative representative 对待**
- 种子的价值是：① 用户当前兴趣锚点 ② 引用图起点（种子的 references 更可能是经典）③ 判断用户所在层次
- Anchor paper / classic baseline 的识别**另走高引 + 时间分布 + 共引**信号，不直接用种子
- Field map 里把种子标为 "User-provided anchors"，与自动识别的 "Classic baselines" 明确分开展示

**种子轻度验证**：LLM 判断 abstract 与意图的匹配度。不匹配者在 field_map 里说明（"X 与意图匹配度低，未作为扩展锚点"），但不中断执行——用户可能有我们不知道的上下文。

## Q4. 单次 Explorer 覆盖多少 topic ✅ 已敲定

**决议：方案 C，一次一个 pool，让聚类自然分离**。

- Explorer 永远跑一个 pool，不拆意图
- 聚类自然分出子区，每簇 → 一个 config topic
- 主 pipeline 本来就支持多 topic，Configure 阶段天然对接（簇 ↔ topic 1:1）

**分裂警报机制**：
聚类发现顶层簇语义距离过大（或 LLM 判属不同领域）时，在 field_map 末尾加 Note：
> ⚠️ Your intent appears to span disjoint areas: **A** and **B**. Consider separate profiles.

不中断、不弹窗、不自动拆。保持 Q2 的零打扰原则。极宽意图（"all of ML"）的 budget 问题属使用层面，不由设计解决。

## Q5. 外部数据源依赖 ✅ 已敲定

**决议：方案 C（默认用外部源 + 优雅降级），v1 选 Semantic Scholar**。

关键事实：
- Google Scholar **无官方 API**，`scholarly` 等非官方爬虫会被 Google 封 IP，不适合自动化场景
- "自建共引估计"实际仍需外部源（ArXiv 不给 references），不是独立方案
- Semantic Scholar 与 Google Scholar 的 CS 覆盖最接近

设计要点：
- 所有外部调用走 `CitationProvider` 抽象，后续可加 OpenAlex 作为替代 provider
- 无 key 也能运行（1 req/s 对单次 Explorer 的几百次调用够用）；有 key（免费申请 1 分钟）质量更好
- 查询在单次 Explorer run 内 memoize，避免速率瓶颈
- Field map 在外部源不可用时明确标注"能力受限"
- Spec 规则条件化：有引用数据时激活 citation-based 规则；无则跳过

## Q6. Planner 的 LLM 选择 ✅ 已敲定

**决议：按关键性分层 + dev mode 开关**。

| 层 | 模型 | 触点 |
|---|---|---|
| 🔴 高关键，低频 | **Pro** | Planner propose、Synthesize、Self-audit |
| 🟡 中关键，中频 | **Flash 起步**，质量不够再升 Pro | Cluster 标签、Query 生成 |
| 🟢 低关键，高频 | **Flash** | Abstract skim、Seed 验证、大部分 spec predicate |

**LLM tier 配置**（支持开发迭代）：
- `production`：分层，默认
- `budget`：Planner 也用 Flash
- `dev`：全部 Flash，最便宜（规则逻辑调试用）

**Spec predicate 原则**：优先符号化（如 embedding cosine distance）；LLM predicate 只在语义判断无法符号化时用，一律 Flash。

成本参考：production ~$1.5–2.5/run，dev ~$0.15–0.25/run。

## Q7. 进度展示方式 ✅ 已敲定

**决议：范式 C（dashboard + 日志文件 + verbose flag）**。

- **前台**：`rich` dashboard（就地刷新），只展示过程指标
- **后台**：完整事件流写 `data/explore/logs/<run_id>.log`
- **`-v` flag**：事件流同时镜像到 stderr，开发期调 spec 规则用
- **新增依赖**：`rich`（也可用于其他 CLI 命令的漂亮输出）

**Cancel 行为**：捕获 SIGINT → 落盘 state → 输出 resume 命令。

**异常提示**：外部源降级、饱和缓慢、规则死锁等**只在 dashboard 加警告行**，不中断、不弹窗。

**系统故障**（API 失败 / quota）：保存 state → 退出 → 输出 resume 命令。

## Q8. Explorer 失败的恢复策略 ✅ 已敲定

**Checkpoint**：每个 action 后落盘 JSON（`state/<run_id>.json`），内容含 paper_pool / clusters / counters / query_log / recent_history / coverage_report / metadata。不存 LLM 对话（单独 log 文件）。

**Resume 语义**：加载 state 从下一 action 继续，非重放。

**统一命令**：
```
python run.py explore --resume <run_id>                    # 中断恢复
python run.py explore --resume <run_id> --feedback "..."  # 反馈 refine
```
Refine 不是独立命令，就是 `--resume --feedback`。

**失败处理**：
| 失败类型 | 处理 |
|---|---|
| SIGINT | 落盘 → clean exit → 提示 resume |
| API quota 耗尽 | 落盘 → 报错退出 → 提示 resume |
| 网络瞬时故障 | 指数退避重试 N 次；失败后同上 |
| LLM 超时 | 重试 1–2 次；失败后同上 |
| **LLM JSON malformed** | **结构性问题，不重试不跳过，直接落盘 + 诊断信息退出** |
| Rule deadlock | 阶梯：3 次 block → 强 feedback；5 次 → 强 synthesize_partial；8 次 → 退出报规则问题 |
| 未预期异常 | try/finally 落盘 + stack trace → 退出 |

**核心原则**：任何失败路径先尝试保存 state（`finally` 块）。

**文件结构**：
```
data/explore/
├── state/<run_id>.json
├── logs/<run_id>.log
└── field_maps/<run_id>.md
```
默认保留最近 10 个 run，`run.py explore --cleanup` 手动清理。

## Q9. Field Map 的呈现介质 ✅ 已敲定

**Field map 格式**：Markdown 文件，写入 `data/explore/field_maps/<run_id>.md`。

**展示方式**：Synthesize 完成后用 `rich` 在终端渲染 Markdown，同时保存文件。用户也可用自己的编辑器打开。

**Configure 交互形态**：
```
╭─ Field Map Summary ──────────────────────────────╮
│ 5 clusters, 147 papers surveyed                  │
│ Suggested: track all clusters                    │
│ Suggested threshold: 6                           │
╰──────────────────────────────────────────────────╯

[Enter] accept defaults and write config.yaml
[e] edit, [q] quit
```

- **默认 Enter 接受 agent 建议 → 0 操作完成 onboard**（对齐核心原则）
- 输 `e` 进入命令模式：`select / rename / merge / split / drop / threshold / show / accept`
- 纯 `rich`，不引入 questionary / GUI / Web UI

## Q10. 和现有 onboard 的共存 ✅ 已敲定

**决议：方案 A（直接替换）**。项目在测试阶段、无用户，不需要兼容包袱。

**代码组织**：
- 新代码按阶段分目录：`src/explore/` + `src/synthesize/` + `src/configure/`
- 旧 `src/onboard/` 在新系统**跑通至少一次**后删除（之前保留作为兜底）
- 新代码零复用旧 onboard；只复用底层组件（`GeminiClient` / `ArxivScraper` / `PDFDownloader` / `DeepReader` / ChromaDB）

**CLI 形态**：
```bash
python run.py onboard             # wrapper = explore → synthesize → configure
python run.py explore [--resume] [--feedback "..."]
python run.py synthesize
python run.py configure
```
`onboard` 是薄包装，实际逻辑在三个子命令里。Refine 场景通过单阶段命令触发。

**"做完"判据**（不是切换判据，是毕业判据）：
1. ≥ 5 次真跑，field_map 人工检查合格
2. 三阶段有基本单元测试（state schema、spec 规则、合成模板）
3. 有 `docs/explore-usage.md`

---

## 讨论优先级建议

按对整体架构影响的大小排：

1. **Q1（阶段边界）** —— 决定了所有其他设计 ✅
2. **Q2（自主度）** —— 决定了整个交互形态 ✅
3. **Q10（共存策略）** —— 决定开发路径 ✅
4. **Q3（种子论文）** —— 影响 Intent 接口 ✅
5. **Q4（多 topic）** —— 影响 state schema ✅
6. **Q5（外部数据源）** —— 影响能力上限 ✅
7. Q6–Q9（局部决策） ✅

---

## 全部已敲定 ✅

10/10 high-level 问题已有决议。进入 low-level 设计阶段。
