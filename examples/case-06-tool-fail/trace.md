# 用例 case-06-tool-fail（验收点 A6）

# Trace — case-06-tool-fail · 任务 1

- 状态: **COMPLETED** | 步数: 2/8 | LLM: mock
- Mock 边界：本 Trace 由离线确定性策略（src/mock_policy.py）驱动，只验证流程与状态处理，不证明真实模型的决策质量。

## Step 1 — `search_docs`
**决策依据**: [Mock规则] 尚无观察：按问题主题发起首次检索（问题含制度用语则直接用制度用语）
**工具参数**: `{"query": "培训 学时"}`
**返回摘要**: `{"ok": false, "error": "知识库检索失败（故障注入）：query 含“培训”，检索服务暂时不可用，请稍后重试"}`

## Step 2 — `finish`
**决策依据**: [Mock规则] 观察到工具返回 ok=false（故障注入）→ 按护栏停止并报 TOOL_FAILED，不编造答案

> 候选人批注（可选，建议写一句人话观察，例如哪一步模型差点走错被护栏拦住）：
> 
# Trace — case-06-tool-fail · 任务 2

- 状态: **COMPLETED** | 步数: 3/8 | LLM: mock
- Mock 边界：本 Trace 由离线确定性策略（src/mock_policy.py）驱动，只验证流程与状态处理，不证明真实模型的决策质量。

## Step 1 — `search_docs`
**决策依据**: [Mock规则] 尚无观察：按问题主题发起首次检索（问题含制度用语则直接用制度用语）
**工具参数**: `{"query": "差旅 住宿标准"}`
**返回摘要**: `{"ok": true, "query": "差旅 住宿标准", "results": [{"doc_id": "D04", "title": "差旅费用标准", "version_date": "2025-03", "score": 6}]}`

## Step 2 — `read_doc`
**决策依据**: [Mock规则] 检索命中 1 篇 → 逐篇 read_doc 核对原文（先读 D04）
**工具参数**: `{"doc_id": "D04"}`
**返回摘要**: `{"ok": false, "error": "读取文档失败（故障注入）：D04 存储服务暂时不可用"}`

## Step 3 — `finish`
**决策依据**: [Mock规则] 观察到工具返回 ok=false（故障注入）→ 按护栏停止并报 TOOL_FAILED，不编造答案

> 候选人批注（可选，建议写一句人话观察，例如哪一步模型差点走错被护栏拦住）：
> 