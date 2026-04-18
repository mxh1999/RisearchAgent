# Spec-based Planner 设计

## 背景概念

参考 **AgentSpec**（[arxiv 2503.18666](https://arxiv.org/abs/2503.18666)）的 runtime constraint enforcement 思想：

> **LLM 自由提议 action，规则在运行时拦截/改写/放行**

三要素：
- **Trigger**：条件激活检查
- **Predicate**：逻辑判断（读 state + action）
- **Enforcement**：`allow` / `block` / `rewrite` / `require_justification`

## 为什么用这个模式（而非 rule-first）

- **保留 LLM 创造力**：LLM 可提议我们没预想过的 action 组合（如 "author X 横跨两簇，fetch 他近期工作"）
- **规则可增量迭代**：看到不良行为 → 加规则，**不改 prompt**
- **职责分离**：
  - Prompt = "你是什么、目标是什么、怎么思考"（激励）
  - Spec = "绝对不能做什么、何时必须做什么"（约束）
- **可审计**：trace 里能看到 "哪条规则、为什么 block、LLM 原意图"
- **规则可 LLM 生成**：AgentSpec 论文提到用 o1 从不良行为自动生成新规则（95% 精度），可做规则库自举

## 循环结构

```
loop:
  proposal = llm_planner.propose(state, prompt)
  verdict  = spec.evaluate(proposal, state)
  if verdict == allow:
      execute(proposal); update(state)
  elif verdict == block:
      llm_planner.re_propose(state, verdict.feedback)
  elif verdict == rewrite:
      execute(verdict.rewritten_action); update(state)
```

## 初版规则草案（8–10 条）

### 探索质量类

```
rule query_diversity:
  trigger:   action.type == search
  predicate: cosine_sim(action.query_embedding,
                        any_of(state.recent_queries[-3:].embedding)) > 0.92
  enforce:   block + feedback("query too similar to recent, try another angle")
```

```
rule query_must_be_specific_after_warmup:
  trigger:   action.type == search
  predicate: state.pool_size > 50
             and action.targeted_cluster is None
             and similar_to_user_intent(action.query)
  enforce:   block + feedback("pool is large, search should target a specific cluster or gap")
```

### 预算 / 资源类

```
rule read_paper_budget:
  trigger:   action.type == read_paper
  predicate: state.read_count >= 3
  enforce:   block + feedback("deep-read budget exhausted; only synthesize or search")
```

```
rule time_budget:
  trigger:   any action
  predicate: state.elapsed_seconds > 900
  enforce:   force_action(synthesize_partial)
```

### 终止条件类

```
rule no_premature_stop:
  trigger:   action.type == stop
  predicate: state.coverage_audit.unanswered_questions != []
  enforce:   block + feedback(list_of_unanswered_questions)
```

```
rule saturation_required_to_stop:
  trigger:   action.type == stop
  predicate: state.new_paper_ratio_last_2_rounds > 0.10
  enforce:   block + feedback("not saturated, new_paper_ratio=X, keep exploring")
```

### 覆盖度类

```
rule classic_baseline_coverage:
  trigger:   action.type == synthesize_full
  predicate: any(cluster.year_range.min > 2022 for cluster in state.clusters)
  enforce:   rewrite → search(cluster.label, year: 2018-2022)
             + feedback("cluster c_i missing classic baselines, search first")
```

### 防循环类

```
rule no_repeated_exact_action:
  trigger:   any action
  predicate: action == state.history[-1]
  enforce:   block + feedback("identical to previous action, try something different")
```

## 实现原则

1. **Predicate 混合符号和 LLM**
   - 符号 predicate（`pool_size > 50`）便宜、确定 —— **绝大多数用这种**
   - LLM predicate（`similar_to_user_intent`）只在语义判断上用 —— **少用，防噪声**

2. **Feedback 是一等产物**
   Block 必须附上 "为什么 + 建议方向"。规则在**教** LLM 行动，不是对抗。

3. **规则版本化**
   `spec/v1.yaml`、`v2.yaml`，A/B 测试。新规则上线前能回放历史 trace 看它会 block 什么。

4. **紧急阀门少用**
   `rewrite` / `force_action` 越少越好。绝大多数用 `block + feedback`，让 LLM 自己修正，保留主动权。

## 警惕的坑

1. **规则过多 → LLM 循环卡死**
   "blocked → retry → blocked"。对策：每 action 最多 retry N 次，超过 escalate 或降级

2. **LLM-based predicate 雪崩**
   所有 action 过一遍 LLM predicate → 指数级 token 消耗。**符号优先**

3. **规则冲突**
   两条同时触发建议矛盾。需要优先级（声明顺序或显式 priority）

4. **过度约束 = 回到 rule-based**
   Spec 写太死，LLM 每步被 rewrite → 失去意义。**宁可少，不要多**。起手 5–8 条高价值规则

## 演进路线

1. 冻结 `ExplorationState` schema（规则输入来自这里）
2. 写第一版 spec（8–10 条），只覆盖预算、饱和、覆盖三类
3. 跑 3 次 Explorer（不同种子意图），收集 trace
4. 看规则触发频次、LLM 自行解决的情况 → 迭代 spec
5. 后续可做：LLM 自动从 trace 生成新规则

## 参考

- [AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents](https://arxiv.org/abs/2503.18666)
- [Open Agent Specification Technical Report](https://arxiv.org/pdf/2510.04173v1)
