# 用例 case-07-max-steps（验收点 补充：执行步数上限）

# Trace — case-07-max-steps · 任务 1

- 状态: **INCOMPLETE_MAX_STEPS** | 步数: 1/1 | LLM: mock
- Mock 边界：本 Trace 由离线确定性策略（src/mock_policy.py）驱动，只验证流程与状态处理，不证明真实模型的决策质量。

## Step 1 — `search_docs`
**决策依据**: [Mock规则] 尚无观察：发起首次检索（无历史用问题原话；带历史从知识库关键词反查检索词）
**工具参数**: `{"query": "入职满一年有多少天年假"}`
**返回摘要**: `{"ok": true, "query": "入职满一年有多少天年假", "results": [{"doc_id": "D03", "title": "员工年假管理制度", "version_date": "2024-11", "score": 2}]}`

> 候选人批注：把步数上限压到 1，第一步检索用完预算就停，状态是明确的 INCOMPLETE_MAX_STEPS，什么结论都没给——上限不是摆设。
