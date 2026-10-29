# 用例 case-01-direct-answer（验收点 A1）

# Trace — case-01-direct-answer · 任务 1

- 状态: **COMPLETED** | 步数: 3/8 | LLM: mock
- Mock 边界：本 Trace 由离线确定性策略（src/mock_policy.py）驱动，只验证流程与状态处理，不证明真实模型的决策质量。

## Step 1 — `search_docs`
**决策依据**: [Mock规则] 尚无观察：按问题主题发起首次检索（问题含制度用语则直接用制度用语）
**工具参数**: `{"query": "年假"}`
**返回摘要**: `{"ok": true, "query": "年假", "results": [{"doc_id": "D03", "title": "员工年假管理制度", "version_date": "2024-11", "score": 2}]}`

## Step 2 — `read_doc`
**决策依据**: [Mock规则] 检索命中 1 篇 → 逐篇 read_doc 核对原文（先读 D03）
**工具参数**: `{"doc_id": "D03"}`
**返回摘要**: `{"ok": true, "doc_id": "D03", "title": "员工年假管理制度", "version_date": "2024-11", "excerpt": "第四条 年假天数：员工入职满 1 年可休 5 天年假，满 5 年可休 10 天年假，年假当年有效，经 OA 审批后安排。"}`

## Step 3 — `finish`
**决策依据**: [Mock规则] 唯一命中且已读原文、无冲突 → 依据该文档回答并附原文引用

> 候选人批注（可选，建议写一句人话观察，例如哪一步模型差点走错被护栏拦住）：
> 