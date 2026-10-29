# 企业知识问答 Agent（题 3）

帮助员工找到制度问题的可靠答案：每个结论都有文档原文支撑；文档冲突时列出双方引用请求确认，不擅自裁决；资料外与工具失败时如实说明，不编造。

## 评审入口（三步复现）

```bash
pip install -r requirements.txt
PYTHONUTF8=1 python -m pytest -q                # 28 个测试，应全绿
PYTHONUTF8=1 python run_examples.py             # 一键重跑全部用例，重建 examples/
```

单用例运行：

```bash
PYTHONUTF8=1 python src/cli.py --case data/cases/case-02-conflict.json
```

产物在 `examples/<case_id>/`：`output.json`（最终输出）、`trace.json`、`trace.md`（含每步工具参数、返回摘要与决策依据）。

**核验"答案不硬编码"（对应审核要点：替换文档内容）**：直接编辑 `data/docs.json`（改措辞、改数值、删文档）后重跑任一用例，检索与回答随之改变；`tests/test_tools.py::test_swapped_data_changes_tool_results` 亦覆盖此场景。

## 模型接入

- 默认离线 Mock：`--llm mock` 或 `--llm auto`（无 key 时自动回落）。Mock 是 `src/mock_policy.py` 里的确定性决策函数，它同样解析工具观察结果再选动作，因此离线也能演示"观察→变招"。
- **Mock 边界**：Mock 只验证流程与状态处理，不证明真实模型的决策质量。当前 `examples/` 全部产物由 Mock 生成，真实模型路径未验证。
- 接真实模型：复制 `.env.example` 为 `.env`，填 `LLM_API_KEY`（可选 `LLM_BASE_URL`、`LLM_MODEL`，OpenAI 兼容接口），然后 `--llm real`。

## 用例与验收点对照

| 用例 | 验收点 | 结果（Mock） |
|---|---|---|
| case-01-direct-answer | A1 明确答案 | ANSWERED，引用 D03 原文 |
| case-02-conflict | A2 文档冲突 | CONFLICT_NEED_CONFIRM，D01/D02 双引用 + 请求确认 |
| case-03-out-of-scope | A3 资料外 | OUT_OF_SCOPE，零引用零编造 |
| case-04-rephrase | A4 改写相似问题 | 首查"在哪儿打卡"0 命中 → 改写"考勤 系统"命中 D05 |
| case-05-followup | A5 上下文追问 | 结合历史定位 D02 并引用原文 |
| case-06-tool-fail | A6 工具失败 | 检索失败/读取失败均 TOOL_FAILED，零编造 |
| case-07-max-steps | 补充：步数上限 | INCOMPLETE_MAX_STEPS，明确的未完成状态 |

详细预期 vs 实际见 [docs/03-evaluation.md](docs/03-evaluation.md)。

## 防线设计（代码级，不靠模型自觉）

`src/tools.py::validate_citations`（finish 校验器）：每条引用的 `doc_id` 必须本次读过、`excerpt` 必须逐字出现在本次 `read_doc` 观察里，违规即丢弃并降级 `INVALID_CITATION`——直接封死"无依据回答 / 错误引用"两条关键缺陷。冲突判定是归一化文本对比而非数值正则（`src/mock_policy.py`），改写词表外置在 `data/terms.json`。设计与取舍详见 [docs/02-solution.md](docs/02-solution.md)。

## 目录

```
src/          llm.py（双轨模型）· agent.py（ReAct 循环）· tools.py（检索/读取/校验器）
              prompts.py · mock_policy.py（确定性决策）· cli.py
tests/        test_tools.py（检索敏感度/故障/校验器/数据可替换）· test_acceptance.py（验收点断言）
data/         docs.json（知识库，可直接替换）· terms.json（改写表）· faults.json（故障注入）· cases/
examples/     每用例 output.json / trace.json / trace.md
docs/         00 方案 · 01 需求 · 02 方案设计 · 03 评估 · 04 AI 使用 · 05 复盘
```
