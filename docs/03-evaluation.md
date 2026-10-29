# 03 评估 —— 测试预期 vs 实际结果

> 产物来源：`PYTHONUTF8=1 python run_examples.py`（Mock 模式）生成的 `examples/<case_id>/output.json`。
> **Mock 边界**：以下全部结果由离线确定性策略（`src/mock_policy.py`）生成，只验证流程与状态处理，不证明真实模型的决策质量；真实模型路径未验证（当前环境无 API key，接入方式见 README）。

## 1. 用例结果总表（pytest 28 通过；运行时间 2026-10-29）

| 用例 | 验收点 | 预期 | 实际（examples/*/output.json） | 一致 |
|---|---|---|---|---|
| case-01-direct-answer | A1 明确答案 | ANSWERED，引用 D03 原文 | 3 步 COMPLETED / ANSWERED，引用 D03 excerpt 逐字 | ✅ |
| case-02-conflict | A2 文档冲突 | 双引用 + 请求确认，不择一 | 4 步 CONFLICT_NEED_CONFIRM，D01+D02 双引用，answer 列双方原文并写明"无法替您选择其一（也不能仅凭版本日期新旧裁决）" | ✅ |
| case-03-out-of-scope | A3 资料外 | 零引用零编造，报缺口 | 3 步 OUT_OF_SCOPE，answer 空、citations 空、info_gap 列出已尝试检索词 | ✅ |
| case-04-rephrase | A4 改写相似问题 | 首查 0 命中→改写→命中 | 4 步 ANSWERED；两次 query 分别为"在哪儿打卡"（0 命中）与"考勤 系统"（命中 D05） | ✅ |
| case-05-followup | A5 上下文追问 | 定位 D02 并引用 | 4 步 ANSWERED，"取值（15）出自《费用报销补充规定》（D02，版本 2025-06）" | ✅ |
| case-06-tool-fail | A6 工具失败 | 两种失败均明确上报 | 任务1 检索失败（query 含"培训"）2 步 TOOL_FAILED；任务2 读取 D04 失败 3 步 TOOL_FAILED；均零编造 | ✅ |
| case-07-max-steps | 补充：步数上限 | 明确未完成状态 | 1 步 INCOMPLETE_MAX_STEPS，final=None | ✅ |

覆盖核对：正常（case-01）/ 信息或资料不足（case-03）/ 工具失败（case-06）三场景齐备；≥2 条"观察→变招"路径 = case-02（读到不一致→请确认）与 case-04（0 命中→改写）；另 case-05（数值比对定位）、case-07（步数耗尽）为补充路径。

## 2. 红线专项测试

| 防线 | 测试 | 结果 |
|---|---|---|
| 编造引用拦截（finish 校验器） | `test_fabricated_citation_is_intercepted`：finish 带改动数字的假 excerpt → INVALID_CITATION、引用清空 | ✅ 拦截 |
| ANSWERED 零引用拦截 | `test_validator_intercepts_answered_without_citations` | ✅ 拦截 |
| 未读文档引用拦截 | `test_validator_rejects_unread_doc_id` | ✅ 拦截 |
| 答案不硬编码（替换知识库） | `test_swapped_data_changes_tool_results`：换 docs.json 后检索/读取随之变 | ✅ 通过 |
| 冲突判定不依赖"N 天"措辞 | `test_conflict_detection_survives_unit_wording_change`：D02 改"15 个工作日"仍判冲突 | ✅ 通过 |
| 改写词表外置 | `test_rephrase_table_is_external_data`：换"食堂→后勤"表即改写新领域 | ✅ 通过 |
| 追问定位不依赖问句模板 | `test_followup_locate_survives_question_rewording`：换问法仍定位 D02 | ✅ 通过 |

## 3. 失败与已知限制

1. **真实模型路径未验证**：全部材料为 Mock 生成。Mock 的改写/冲突分支是确定性策略，真实模型可能首查即用制度用语（A4 不复现）或转述引用（被校验器拦截为 INVALID_CITATION）。接入 key 后需补 real 冒烟记录。
2. **冲突误报可能**：两份文档措辞不同但语义相同时会误报冲突；此时输出为"双引用 + 请确认"，不会给出错误答案，但会多一轮确认。
3. **追问定位依赖数值可比对**：追问若不含数值（如"那另一份呢"）会落入冲突/一致常规路径，回答仍是双引用清单，非精确定位。
4. **检索是关键词计分**：非向量检索，同义但不含关键词的问法需走改写路径；这是刻意设计（A4 依赖），但意味着真实知识库需要配好 keywords。

## 4. 测试命令

```bash
PYTHONUTF8=1 python -m pytest -q          # 28 passed
PYTHONUTF8=1 python run_examples.py       # 重建 examples/，7 用例
```
