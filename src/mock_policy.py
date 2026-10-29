# -*- coding: utf-8 -*-
"""MockLLM 的确定性决策策略：解析最后一条 OBSERVATION 与动作历史，依据观察结果变招。

决策树（与 docs/01 §5 的动态决策要求一一对应）：
- 尚无观察            → 首次检索：无历史用问题原话（口语首发可能 0 命中，正是检索改进路径的入口）；
                        带 [历史] 时追问常省略主题（如只问"那份是哪份文件"），从知识库 keywords 反查检索词
- 观察 ok=false       → 护栏 5：TOOL_FAILED 终态，不编造
- 检索 0 命中(首次)    → 护栏 2：按 data/terms.json 口语→制度用语表改写（表外置），或 keywords 反查兜底
- 检索(含改写)仍 0 命中 → OUT_OF_SCOPE，如实报资料缺口
- 检索命中            → 逐篇 read_doc 核对原文
- 多篇支撑句归一化后文本不一致 → 护栏 3：CONFLICT_NEED_CONFIRM，列双方引用请求确认。
  冲突判定是"文本对比"而非"提取数值"：不假设单位与句式，"15 个工作日"对"30 天"同样判冲突；
  数值与单位只允许出现在 data/docs.json，代码里没有任何取值或问句模板
- 文本一致或唯一依据   → ANSWERED，引用 read_doc 原文（逐字）
- 追问指代（带 [历史] 且问题含数值）→ 问题中的数值与【已读原文支撑句】直接比对：恰好一篇命中则定位该文档。
  不匹配"哪份/那份"等预设问句——问法换成"哪一个/哪个文件来着"结果不变

边界声明：本策略只验证 ReAct 流程与状态处理，不证明真实模型的决策质量；
真实模型路径下同样的分支由模型自己走。
"""
import json
import re

import tools as kb
from agent import extract_json

# 主题 → 供句子级摘录匹配的同义词（仅用于从 excerpt 里挑支撑句；0 句或多句命中时整段引用，
# 引用永远是 excerpt 的逐字子串，因此该表不影响引用可溯性）
_TOPIC_SYNONYMS = [
    ("报销期限", ["报销期限", "报销"]),
    ("年假", ["年假"]),
    ("考勤", ["考勤", "打卡"]),
    ("差旅住宿标准", ["差旅", "出差", "住宿"]),
    ("培训", ["培训"]),
    ("活动经费", ["活动经费", "团建"]),
]


def _task_of(messages):
    for m in messages:
        if m.get("role") == "user" and not str(m.get("content", "")).startswith("OBSERVATION: "):
            return m["content"]
    return ""


def _history(messages):
    """从消息里还原动作序列与观察序列（跳过无法解析的 assistant 输出，避免错位）。"""
    actions, observations = [], []
    for m in messages:
        content = str(m.get("content", ""))
        if m.get("role") == "assistant":
            try:
                decision = extract_json(content)
            except Exception:
                continue
            actions.append((decision.get("action", ""), decision.get("args") or {}))
        elif m.get("role") == "user" and content.startswith("OBSERVATION: "):
            try:
                observations.append(json.loads(content[len("OBSERVATION: "):]))
            except Exception:
                observations.append({})
    return actions, observations


def _current_question(task):
    return task.split("[当前问题]")[-1].strip() if "[当前问题]" in task else task.strip()


def _topic_of(task):
    for name, syns in _TOPIC_SYNONYMS:
        if any(s in task for s in syns):
            return name, syns
    return "", []


def _keyword_backoff(text):
    """关键词反查（数据驱动）：从 docs.json 的 keywords 里找出出现在 text 中的词拼成检索词。
    反查表就是知识库本身——替换 docs.json 即改变反查结果，代码里没有词表。"""
    hits = []
    for doc in kb.all_docs():
        for kw in doc.get("keywords", []):
            if kw and kw in text and kw not in hits:
                hits.append(kw)
    if not hits:
        return ""
    hits.sort(key=len, reverse=True)  # 长词优先，通常更具体
    return " ".join(hits[:2])


def _first_query(task):
    """首次检索词：无历史 → 问题原话（口语首发，保留措辞敏感的 0 命中入口）；
    带 [历史] → 追问省略主题，用 keywords 反查得到检索词。"""
    question = _current_question(task)
    stripped = question.rstrip("？?。！，, ")
    if "[当前问题]" not in task:
        return stripped
    return _keyword_backoff(task) or stripped


def _load_terms():
    try:
        payload = kb.load_rewrite_terms()
    except Exception:
        return []
    return payload.get("terms", [])


def _rephrase(task, last_query):
    """护栏 2 的改写（数据驱动，三层）：
    1) data/terms.json 口语→制度用语表：问句含口语词则换正式检索词（外置表，加词条即扩行为）；
    2) keywords 反查兜底；
    3) 去疑问词精简原话。
    """
    question = _current_question(task)
    scope = task if "[当前问题]" in task else question
    for entry in _load_terms():
        for spoken in entry.get("spoken", []):
            if spoken and spoken in scope:
                formal = str(entry.get("formal_query", ""))
                if formal and formal != last_query:
                    return formal
    backoff = _keyword_backoff(scope)
    if backoff and backoff != last_query:
        return backoff
    query = last_query
    for word in ("是什么", "多少", "怎么", "哪里", "哪儿", "吗", "呢", "？", "?", "。", "！"):
        query = query.replace(word, "")
    return query.strip()


def _normalize(text):
    """冲突对比用的文本归一化：去空白与标点，保留文字与数字。
    只用于判断"两段原文是否同一句话"，不参与引用（引用仍是逐字原文）。"""
    return re.sub(r"[\s，。；;、,.:：！!？?（）()【】\"'“”‘’]+", "", text)


def _numbers_in(text):
    """问题中出现的数值（域无关的指代线索：不绑定单位、不做句式假设）。"""
    return re.findall(r"\d+(?:\.\d+)?", text)


def _clause(excerpt, synonyms):
    """从 excerpt 挑出包含主题词的支撑句；0 句或多句命中时整段引用。返回值必为 excerpt 的逐字子串。"""
    sentences = [s for s in re.split(r"[。；;]", excerpt) if s.strip()]
    hits = [s for s in sentences if any(x in s for x in synonyms)]
    if len(hits) == 1:
        return hits[0]
    return excerpt


def _locate_by_numbers(question, doc_clauses):
    """追问指代解析（观察驱动）：问题中的数值与【本次已读原文的支撑句】直接比对。
    恰好一篇命中 → (doc_id, [命中数值])；无数值、0 篇或多篇命中 → None（交给常规冲突/一致逻辑，
    由已读到的原文决定回答内容）。"""
    nums = _numbers_in(question)
    if not nums:
        return None
    matched = {}
    for doc_id, clause in doc_clauses.items():
        hit_nums = [n for n in nums if n in clause]
        if hit_nums:
            matched[doc_id] = hit_nums
    if len(matched) == 1:
        doc_id, hit_nums = next(iter(matched.items()))
        return doc_id, hit_nums
    return None


def _finish(final, thought):
    return {"thought": thought, "action": "finish", "args": {}, "final": final}


def _conclude(task, read_docs, search_results):
    """所有命中文档已读完 → 依据读到的原文决定：追问定位 / 冲突确认 / 文本一致 / 唯一依据直答。"""
    topic, syns = _topic_of(task)
    ordered = [read_docs[r["doc_id"]] for r in search_results if r["doc_id"] in read_docs]
    if not ordered:
        ordered = [read_docs[k] for k in sorted(read_docs)]
    question = _current_question(task)
    clauses = {o["doc_id"]: _clause(o["excerpt"], syns) for o in ordered}

    # 1) 追问指代解析：问题里的数值与已读原文比对，唯一命中即定位（不匹配预设问句）
    if "[当前问题]" in task:
        located = _locate_by_numbers(question, clauses)
        if located:
            doc_id, hit_nums = located
            obs = next(o for o in ordered if o["doc_id"] == doc_id)
            answer = (f"结合上一轮对话，您问的取值（{'、'.join(hit_nums)}）出自《{obs['title']}》"
                      f"（{obs['doc_id']}，版本 {obs['version_date']}），原文：{clauses[doc_id]}")
            return _finish({"answer": answer,
                            "citations": [{"doc_id": obs["doc_id"], "version": obs["version_date"],
                                           "excerpt": clauses[doc_id]}],
                            "info_gap": None, "status": "ANSWERED"},
                           f"[Mock规则] 追问指代解析：问题中的数值 {'、'.join(hit_nums)} 与已读原文逐字比对，"
                           f"唯一命中 {doc_id} → 引用其原文作答")

    # 2) 多篇核对：支撑句归一化文本不一致（无适用范围/优先级）→ 冲突，列双方引用请求确认。
    #    不按版本日期裁决，也不做数值/单位假设。
    if len(ordered) > 1:
        citations = [{"doc_id": o["doc_id"], "version": o["version_date"], "excerpt": clauses[o["doc_id"]]}
                     for o in ordered]
        listing = "；".join(f"{o['doc_id']}《{o['title']}》（版本 {o['version_date']}）写明："
                           f"{clauses[o['doc_id']].rstrip('。；;')}" for o in ordered)
        if len({_normalize(c) for c in clauses.values()}) > 1:
            answer = (f"知识库中关于{topic or '该问题'}存在 {len(ordered)} 份规定且原文内容不一致：{listing}。"
                      f"上述文件均未写明适用范围与优先级，我无法替您选择其一（也不能仅凭版本日期新旧裁决），"
                      f"请确认您适用的制度后，我再据此给出结论。")
            return _finish({"answer": answer, "citations": citations,
                            "info_gap": f"{topic or '该主题'}存在无适用范围的冲突规定"
                                        f"（{'、'.join(o['doc_id'] for o in ordered)}），待用户确认适用制度。",
                            "status": "CONFLICT_NEED_CONFIRM"},
                           "[Mock规则] 多篇原文支撑句归一化对比不一致 → 冲突：列双方引用并请求确认，"
                           "不擅自择一、不按版本日期裁决")
        return _finish({"answer": f"知识库中 {len(ordered)} 份文档对{topic or '该问题'}的原文一致：{listing}",
                        "citations": citations, "info_gap": None, "status": "ANSWERED"},
                       "[Mock规则] 多篇原文支撑句归一化对比一致 → 可回答，引用全部支撑文档原文")

    # 3) 唯一依据 → 直接回答 + 逐字引用
    obs = ordered[0]
    answer = f"根据《{obs['title']}》（{obs['doc_id']}，版本 {obs['version_date']}）：{clauses[obs['doc_id']]}"
    return _finish({"answer": answer,
                    "citations": [{"doc_id": obs["doc_id"], "version": obs["version_date"],
                                   "excerpt": clauses[obs["doc_id"]]}],
                    "info_gap": None, "status": "ANSWERED"},
                   "[Mock规则] 唯一命中且已读原文、无冲突 → 依据该文档回答并附原文引用")


def decide(messages):
    """MockLLM 的 policy：依据观察历史在 检索/改写检索/读取/结束 之间确定性选择。"""
    task = _task_of(messages)
    actions, observations = _history(messages)
    last_obs = observations[-1] if observations else None

    # 尚无任何观察 → 首次检索
    if last_obs is None:
        return {"thought": "[Mock规则] 尚无观察：发起首次检索"
                           "（无历史用问题原话；带历史从知识库关键词反查检索词）",
                "action": "search_docs", "args": {"query": _first_query(task)}}

    # 观察 ok=false → 护栏 5：明确失败终态，不编造
    if last_obs.get("ok") is False:
        return _finish({"answer": "", "citations": [],
                        "info_gap": f"工具调用失败，已中止：{last_obs.get('error', '未知错误')}",
                        "status": "TOOL_FAILED"},
                       "[Mock规则] 观察到工具返回 ok=false（故障注入）→ 按护栏停止并报 TOOL_FAILED，不编造答案")

    searches = [args for act, args in actions if act == "search_docs"]
    read_docs, search_results = {}, []
    for obs in observations:
        if obs.get("ok") and "results" in obs:
            search_results = obs["results"]
        if obs.get("ok") and "doc_id" in obs and "excerpt" in obs:
            read_docs[obs["doc_id"]] = obs

    # 最近一次是检索
    if "results" in last_obs:
        if not last_obs["results"]:
            if len(searches) == 1:
                last_query = str(searches[-1].get("query", ""))
                new_query = _rephrase(task, last_query)
                if new_query and new_query != last_query:
                    return {"thought": "[Mock规则] 首次检索 0 命中（口语问法搜不中）→ 按 terms 表/关键词反查改写后再检索一次",
                            "action": "search_docs", "args": {"query": new_query}}
            tried = "、".join(f"“{a.get('query', '')}”" for a in searches)
            return _finish({"answer": "", "citations": [],
                            "info_gap": f"知识库中未找到与该问题相关的文档（已尝试检索：{tried}），属资料外问题，无法回答。",
                            "status": "OUT_OF_SCOPE"},
                           "[Mock规则] 检索（含改写）仍 0 命中 → 知识库无此资料，如实报 OUT_OF_SCOPE，不编造")
        pending = [r["doc_id"] for r in last_obs["results"] if r["doc_id"] not in read_docs]
        if pending:
            return {"thought": f"[Mock规则] 检索命中 {len(last_obs['results'])} 篇 → 逐篇 read_doc 核对原文（先读 {pending[0]}）",
                    "action": "read_doc", "args": {"doc_id": pending[0]}}
        return _conclude(task, read_docs, search_results)

    # 最近一次是读取
    if "doc_id" in last_obs:
        pending = [r["doc_id"] for r in search_results if r["doc_id"] not in read_docs]
        if pending:
            return {"thought": f"[Mock规则] 已读 {len(read_docs)} 篇，仍有命中文档未核对 → 继续读取 {pending[0]}",
                    "action": "read_doc", "args": {"doc_id": pending[0]}}
        return _conclude(task, read_docs, search_results)

    # 兜底
    return _finish({"answer": "", "citations": [],
                    "info_gap": "未获得可用的工具观察，无法回答。", "status": "OUT_OF_SCOPE"},
                   "[Mock规则] 观察内容无法识别 → 兜底结束为 OUT_OF_SCOPE，不编造")
