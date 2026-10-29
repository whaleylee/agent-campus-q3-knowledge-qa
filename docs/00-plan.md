# 00 方案 · 企业知识问答 Agent（题 3）

> 本题独立执行方案。需求全文见 [01-requirements.md](01-requirements.md)；统一架构契约见 [../../CONVENTIONS.md](../../CONVENTIONS.md)；争吵与仲裁背景见 [../../执行方案.md](../../执行方案.md) 第 2 节。
> 当前状态：src/tests/examples 已建成，pytest 24 绿；但 README 还写"未开始实现"（硬伤）、缺 docs/02~05、追问与改写是正则"背题"、无 git。执行顺序排第一。

## 1. 目标

帮员工找到制度问题的可靠答案：检索 → 读原文 → 唯一命中则带引用作答，多篇冲突则列双引用请求确认（不按版本日期裁决），资料外直说不知道。引用必须逐字来自工具返回。

## 2. 验收点与用例（7 个）

| # | 验收点 | 注入 | 预期 | 用例 |
|---|---|---|---|---|
| A1 | 明确答案 | 问年假（D03 唯一命中） | ANSWERED，引用 D03+原文 | case-01-direct-answer |
| A2 | 文档冲突 | 问报销期限（D01 30 天 / D02 15 天，均无适用范围） | CONFLICT_NEED_CONFIRM，双引用，请求确认适用制度，不择一作答 | case-02-conflict |
| A3 | 资料外问题 | 知识库无此内容 | OUT_OF_SCOPE，说明缺口，不编造 | case-03-out-of-scope |
| A4 | 改写相似问题 | 口语"在哪儿打卡"首查 0 命中 | 改写为制度用语再查命中 D05 → ANSWERED；trace 有两次不同 query | case-04-rephrase |
| A5 | 上下文追问 | task 带对话历史，问"那 15 天那份是哪份文件" | 结合历史定位 D02，ANSWERED 引用正确 | case-05-followup |
| A6 | 工具失败 | faults 指定 query 或 doc_id 失败 | TOOL_FAILED，明确失败，不编答案 | case-06-tool-fail |
| 补 | 步数上限 | max_steps=1 跑 case-01 | INCOMPLETE_MAX_STEPS | case-07-max-steps |
| 专项 | 替换文档内容 | 评委改 docs.json 内容 | 检索/答案随数据变（test_swapped_data 专项测试，防硬编码） | tests 内建 |

## 3. 设计

### 3.1 底座

六件套 + 双轨 LLM。本题 max_steps=8。docs.json 每次调用重读（替换内容即生效）。

### 3.2 工具

| 工具 | 签名 | 职责与要点 |
|---|---|---|
| search_docs | (query) | 关键词计分：每篇文档 keywords（title+内容自动抽取，manual 只兜底）与 query 计分；口语问法计 0 分不中（措辞敏感是特性，A4 依赖它） |
| read_doc | (doc_id) | 返回 doc_id/title/version_date/原文 excerpt |

### 3.3 防线（finish_validator，本题灵魂）

每条 citation：excerpt 必须逐字出现在本次 trace 的 read_doc 观察里（仅空白归一化），doc_id 必须本次读过；违规 → INVALID_CITATION 并丢弃该引用。防"无依据回答/错误引用"一票否决。单测构造编造引用验证被拦。

### 3.4 冲突判定（裁决 5 改造，去正则化）

不再用"N 天"正则。改为：同一 query 命中 ≥2 篇 → 逐篇 read_doc → 对两段 excerpt 做归一化文本对比（同问关键词、答案文本不同 → 冲突）→ 列双引用请示。"30 天/15 天"字样只允许存在于 data/docs.json，代码里不出现。

### 3.5 改写泛化（裁决 5 改造）

同义改写表外置 data/terms.json（口语词→制度词映射，可扩展）；未命中映射时从命中文档的关键词反查生成新 query。单轮改写后仍 0 命中 → OUT_OF_SCOPE，边界如实入 docs。

### 3.6 数据

docs.json（D01 报销制度 v2025-01"30 天" / D02 报销补充规定 v2025-06"15 天"，都不写适用范围；D03 年假；D05 考勤 OA）、terms.json（新增）、faults.json、cases/。业务味命名，无真实公司名。

## 4. 争吵裁决落点（本题相关）

| 对峙 | 裁决 | 本题动作 |
|---|---|---|
| A5 追问正则匹配"哪份|那份"是固定分支（q1 攻） | 攻方胜 | 追问改从历史 assistant 回答的引用里解析指代，不匹配预设句式 |
| _rephrase 只认五个主题，替换文档即穿帮（q1 攻） | 攻方胜 | §3.5 改写表外置 + 关键词反查 |
| 冲突靠"N 天"正则，"15 个工作日"漏判踩一票否决（q2 攻） | 攻方胜 | §3.4 归一化文本对比 |
| README 写"未开始实现"（自认硬伤） | 立即修 | 执行第一步 |
| real 下首查可能直接命中、逐字比对误伤（自认） | 记录边界 | docs/03 标注"当前材料全为 Mock"；比对仅空白归一化 |

## 5. 执行步骤与验收门

| 步骤 | 内容 | 验收门 | 预计 |
|---|---|---|---|
| 3.1 | README 重写：真实状态、三步复现链（install→pytest→run_examples）、Mock 边界、评委替换 docs.json 指引（引 test_swapped_data） | 命令逐条可跑 | 0.5h |
| 3.2 | 冲突判定去正则化（§3.4） | 改造后全部用例仍绿（含"15 个工作日"变体测试） | 1.5h |
| 3.3 | 追问去句式匹配 + 改写泛化（§3.5，terms.json） | 换措辞不再依赖预设主题 | 1.5h |
| 3.4 | case-07 超限用例 + 测试 | INCOMPLETE_MAX_STEPS trace 入 examples | 0.5h |
| 3.5 | docs/02~05：02 含"冲突不按版本日期裁决"设计判断节 + 引真实文件名；03 逐用例摘 output.json 实值；04/05 空位+用时表 | 03 数字与 output.json 一致 | 1.5h |
| 3.6 | git init + 阶段 commit | git log 可查 | 0.5h |

## 6. 风险与对策

- **real 模式 A4 不复现**（真模型首查就用制度用语）：检索命中由数据关键词决定而非 mock 拍板，docs/03 如实标注；有 key 后补 real 冒烟。
- **逐字比对过严**：仅做空白归一化，标点差异如实拦（宁可误拦不可错引——这是红线取向，写进 docs/02）。
- **冲突对比的边界**：两段 excerpt 措辞差异但语义相同会误报冲突——如实入 docs/03 已知限制。
