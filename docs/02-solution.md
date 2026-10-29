# 02 方案设计 —— 企业知识问答 Agent

> 需求见 [01-requirements.md](01-requirements.md)；分题方案与裁决落点见 [00-plan.md](00-plan.md)。

## 1. 调用流程

```
用户问题（可带 [历史] 对话）
        │
        ▼
┌────────────────────────── ReAct 循环（src/agent.py，上限 8 步）──────────────────────────┐
│                                                                                          │
│  模型输出 JSON 动作 ──► 执行工具 ──► 观察结果回填对话 ──► 模型依据观察决定下一步或 finish      │
│                                                                                          │
│  search_docs(query)──0 命中──► 改写检索词（data/terms.json / keywords 反查）──► 再查一次    │
│        │ 命中                                                                            │
│        ▼                                                                                │
│  read_doc(doc_id) ──逐篇读完──► 归一化文本对比 ──不一致──► CONFLICT_NEED_CONFIRM（双引用）  │
│        │                                ──一致──► ANSWERED（全部引用）                    │
│        └─唯一命中──► ANSWERED（单引用）                                                    │
│  工具 ok=false ──► TOOL_FAILED（不编造）    问题含数值+带历史──► 数值比对定位（ANSWERED）     │
└──────────────────────────────────────────────────────────────────────────────────────────┘
        │ finish
        ▼
  finish_validator（src/tools.py::validate_citations）：引用逐字回查观察记录，违规降级 INVALID_CITATION
```

## 2. 动态决策点（模型/策略依据观察结果变招）

| 观察到 | 决策 | 实现位置 |
|---|---|---|
| 首查 0 命中 | 按外置改写表 + keywords 反查改写，再查一次（只改写一次） | `mock_policy._rephrase` |
| 改写后仍 0 命中 | OUT_OF_SCOPE，报已尝试的检索词，不编造 | `mock_policy.decide` |
| 命中多篇 | 逐篇 read_doc 核对原文 | `mock_policy.decide` |
| 多篇支撑句文本不一致 | CONFLICT_NEED_CONFIRM，列双方引用请求确认 | `mock_policy._conclude` |
| 多篇文本一致 / 唯一命中 | ANSWERED，引用原文 | `mock_policy._conclude` |
| 问题带历史且含数值指代 | 数值与已读原文比对，唯一命中即定位引用 | `mock_policy._locate_by_numbers` |
| 工具 ok=false | TOOL_FAILED 终态 | `mock_policy.decide` |

四条异构执行路径可从 examples 直接观察：case-02（冲突）、case-04（改写）、case-05（追问定位）、case-07（步数耗尽）。

## 3. 关键设计判断

**为什么冲突判定不用"提取数值再比较"？**
最初实现用正则抓"N 天"比较取值，评审把文档改成"15 个工作日"就会漏判——漏判冲突会导致单边作答，踩"冲突不得择一"的一票否决红线。现改为：两段支撑句归一化（去空白标点）后直接文本对比，不一致即冲突。单位、币种、比例任意措辞都适用。代价是"措辞不同但语义相同"会误报冲突，此时输出仍是"列双引用请确认"，不产生错误答案（已知限制记入 docs/03）。

**为什么冲突不按版本日期裁决？**
题面明确 D01/D02"未给适用范围与优先级"。版本新旧是数据属性不是效力依据，制度效力归属制度本身，Agent 无权替员工认定。故输出永远是"列冲突 + 双引用 + 请求确认"。

**为什么检索"对措辞敏感"是特性而非缺陷？**
口语问法 0 命中是 A4（检索改进）的前提：正是首查失败才产生"改写再查"的决策路径。命中与否完全由 `docs.json` 的 keywords 决定，替换知识库即改变行为（`test_swapped_data_changes_tool_results` 验证）。

**为什么改写词表外置到 data/terms.json？**
硬编码"打卡→考勤"意味着换一个口语领域就失效（防背题改造点）。外置后加词条即扩展行为，配合 keywords 反查兜底，`test_rephrase_table_is_external_data` 用一张"食堂→后勤"的表验证了这一点。

**为什么 finish 校验器逐字比对、连标点都不放过？**
"错误引用"是本题一票否决红线。逐字比对（仅空白归一化）宁可误拦不可错引——被拦的输出状态是 INVALID_CITATION 且说明原因，评委可复核；放过一条编造引用则整题失分。取严不取宽。

**为什么不用 LangGraph/ADK 等框架？**
本题的展示价值就在那 ~100 行 ReAct 循环本身（动作 JSON → 执行 → 观察回填 → 变招）。框架会把决策循环包进黑盒，评委看到的是框架能力而非 Agent 决策；且为 3 小时规模的题引入重依赖，安装与版本风险大于收益。循环在 `src/agent.py`，四项目共用同一契约（见仓库根 CONVENTIONS.md）。

## 4. 与验收点的对应

- A1 唯一命中直答：`_conclude` 唯一分支；A2 冲突：归一化对比分支；A3 资料外：两次 0 命中分支
- A4 检索改进：`_rephrase`；A5 追问：`_locate_by_numbers`（数据比对，不匹配问句模板）
- A6 工具失败：ok=false 分支；步数上限：`agent.run_agent` 循环上限 + `INCOMPLETE_MAX_STEPS`
- 红线防线：`validate_citations`（引用逐字回查）
