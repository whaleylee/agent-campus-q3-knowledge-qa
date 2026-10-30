# 用例 case-01-direct-answer（验收点 A1）

# Trace — case-01-direct-answer · 任务 1

- 状态: **COMPLETED** | 步数: 3/8 | LLM: mock
- Mock 边界：本 Trace 由离线确定性策略（src/mock_policy.py）驱动，只验证流程与状态处理，不证明真实模型的决策质量。

## Step 1 — `search_docs`
**决策依据**: [Mock规则] 尚无观察：发起首次检索（无历史用问题原话；带历史从知识库关键词反查检索词）
**工具参数**: `{"query": "入职满一年有多少天年假"}`
**返回摘要**: `{"ok": true, "query": "入职满一年有多少天年假", "results": [{"doc_id": "D03", "title": "员工年假管理制度", "version_date": "2024-11", "score": 2}]}`

## Step 2 — `read_doc`
**决策依据**: [Mock规则] 检索命中 1 篇 → 逐篇 read_doc 核对原文（先读 D03）
**工具参数**: `{"doc_id": "D03"}`
**返回摘要**: `{"ok": true, "doc_id": "D03", "title": "员工年假管理制度", "version_date": "2024-11", "excerpt": "第四条 年假天数：员工入职满 1 年可休 5 天年假，满 5 年可休 10 天年假，年假当年有效，经 OA 审批后安排。"}`

## Step 3 — `finish`
**决策依据**: [Mock规则] 唯一命中且已读原文、无冲突 → 依据该文档回答并附原文引用

> 候选人批注：只命中 D03 一篇，读完原文就直接回答了，引用和原文逐字一致，没有多余动作。
