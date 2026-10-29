# -*- coding: utf-8 -*-
"""MockLLM 的确定性决策策略：解析最后一条 OBSERVATION 与动作历史，依据观察结果变招。

决策树（与 docs/01 §5 的动态决策要求一一对应）：
- 尚无观察            → 按问题主题构造首次检索（问题已含制度用语则直接用制度用语，口语问法原样首发）
- 观察 ok=false       → 护栏 5：TOOL_FAILED 终态，不编造
- 检索 0 命中(首次)    → 护栏 2：改写为制度用语再检索一次
- 检索(含改写)仍 0 命中 → OUT_OF_SCOPE，如实报资料缺口
- 检索命中            → 逐篇 read_doc 核对原文（读到冲突值为止）
- 全部读完、天数取值不一致且无适用范围 → 护栏 3：CONFLICT_NEED_CONFIRM，列双方引用请求确认
- 全部读完、取值一致或唯一依据 → ANSWERED，引用 read_doc 原文（逐字）
- 追问（含 [历史]）    → 结合历史理解指代（如“那 15 天那份”），定位到对应文档后回答

边界声明：本策略只验证 ReAct 流程与状态处理，不证明真实模型的决策质量；
真实模型路径下同样的分支由模型自己走。
"""
import json
import re

from agent import extract_json

# 主题 → 供句子级摘录匹配的同义词（用于从 excerpt 里挑出支撑句）
_TOPIC_SYNONYMS = [
    ("报销期限", ["报销期限", "报销"]),
    ("年假", ["年假"]),
    ("考勤", ["考勤", "打卡"]),
    ("差旅住宿标准", ["差旅", "出差", "住宿"]),
    ("培训", ["培训"]),
]

# 问题文本中的制度用语 → 首次检索词（口语词如“打卡”故意不在此列，保留口语首发以触发 0 命中）
_TERM_TO_QUERY = [
    ("报销期限", "报销期限"),
    ("报销", "报销期限"),
    ("年假", "年假"),
    ("差旅", "差旅 住宿标准"),
    ("出差", "差旅 住宿标准"),
    ("住宿", "差旅 住宿标准"),
    ("培训", "培训 学时"),
    ("考勤", "考勤 系统"),
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


def _first_query(task):
    """首次检索词：追问场景结合历史找主题；普通问题已含制度用语则直接用制度用语；否则用原话（口语 → 可能 0 命中）。"""
    question = _current_question(task)
    scope = task if "[当前问题]" in task else question
    for term, query in _TERM_TO_QUERY:
        if term in scope:
            return query
    return question.rstrip("？?。！，, ")  # 原话首发，仅去掉句末标点


def _rephrase(task, last_query):
    """护栏 2 的改写规则：口语“打卡/考勤”类问题 → 制度用语；其他问题去掉疑问词精简。"""
    if "打卡" in task or "考勤" in task:
        return "考勤 系统"
    query = last_query
    for word in ("是什么", "多少", "怎么", "哪里", "哪儿", "吗", "呢", "？", "?", "。", "！"):
        query = query.replace(word, "")
    return query.strip()


def _clause(excerpt, synonyms):
    """从 excerpt 挑出包含主题词的支撑句；0 句或多句命中时整段引用。返回值必为 excerpt 的逐字子串。"""
    sentences = [s for s in re.split(r"[。；;]", excerpt) if s.strip()]
    hits = [s for s in sentences if any(x in s for x in synonyms)]
    if len(hits) == 1:
        return hits[0]
    return excerpt


def _days(text):
    """提取“N 天”取值（字符串形式），用于多篇文档的一致性/冲突判断。"""
    return re.findall(r"(\d+)\s*天", text)


def _finish(final, thought):
    return {"thought": thought, "action": "finish", "args": {}, "final": final}


def _conclude(task, read_docs, search_results):
    """所有命中文档已读完 → 依据读到的原文决定：追问定位 / 冲突确认 / 一致可答 / 唯一依据直答。"""
    topic, syns = _topic_of(task)
    ordered = [read_docs[r["doc_id"]] for r in search_results if r["doc_id"] in read_docs]
    if not ordered:
        ordered = [read_docs[k] for k in sorted(read_docs)]
    question = _current_question(task)

    # 1) 追问“定位文件”模式：结合历史理解“那 X 天那份是哪份文件”
    if "[当前问题]" in task and re.search(r"哪份|哪个|那份|这份", question):
        match = re.search(r"(\d+)\s*天", question)
        if match:
            want = match.group(1)
            for obs in ordered:
                clause = _clause(obs["excerpt"], syns)
                if want in _days(clause):
                    answer = (f"结合上一轮对话，写明 {want} 天的是《{obs['title']}》"
                              f"（{obs['doc_id']}，版本 {obs['version_date']}），原文：{clause}")
                    return _finish({"answer": answer,
                                    "citations": [{"doc_id": obs["doc_id"], "version": obs["version_date"], "excerpt": clause}],
                                    "info_gap": None, "status": "ANSWERED"},
                                   f"[Mock规则] 追问指代定位：历史冲突回复中写明 {want} 天的文件 → 引用其原文作答")
            return _finish({"answer": "", "citations": [],
                            "info_gap": f"结合对话历史，已读文档中未找到写明“{match.group(0)}”的规定文件，无法定位。",
                            "status": "OUT_OF_SCOPE"},
                           "[Mock规则] 追问定位失败：读过的文档原文中没有该取值 → 如实报缺口，不猜测")

    # 2) 多篇核对：同主题取值不一致且无适用范围 → 冲突，列双方引用请求确认（不按版本日期裁决）
    if len(ordered) > 1:
        listing = "；".join(f"{o['doc_id']}《{o['title']}》（版本 {o['version_date']}）写明：{_clause(o['excerpt'], syns).rstrip('。；;')}"
                           for o in ordered)
        citations = [{"doc_id": o["doc_id"], "version": o["version_date"], "excerpt": _clause(o["excerpt"], syns)}
                     for o in ordered]
        all_values = set()
        for o in ordered:
            all_values |= set(_days(_clause(o["excerpt"], syns)))
        if len(all_values) > 1:
            answer = (f"知识库中关于{topic or '该问题'}存在 {len(ordered)} 份规定且内容不一致：{listing}。"
                      f"上述文件均未写明适用范围与优先级，我无法替您选择其一（也不能仅凭版本日期新旧裁决），"
                      f"请确认您适用的制度后，我再据此给出结论。")
            return _finish({"answer": answer, "citations": citations,
                            "info_gap": f"{topic or '该主题'}存在无适用范围的冲突规定（{'、'.join(o['doc_id'] for o in ordered)}），待用户确认适用制度。",
                            "status": "CONFLICT_NEED_CONFIRM"},
                           "[Mock规则] 读到的多篇原文取值不一致且无适用范围 → 冲突：列双方引用并请求确认，不擅自择一、不按版本日期裁决")
        if all_values:
            answer = f"知识库中 {len(ordered)} 份文档对{topic or '该问题'}的规定一致：{listing}"
        else:
            answer = f"知识库中命中 {len(ordered)} 份与{topic or '该问题'}相关的文档：{listing}"
        return _finish({"answer": answer, "citations": citations, "info_gap": None, "status": "ANSWERED"},
                       "[Mock规则] 多篇原文取值一致 → 可回答，引用全部支撑文档原文")

    # 3) 唯一依据 → 直接回答 + 逐字引用
    obs = ordered[0]
    clause = _clause(obs["excerpt"], syns)
    answer = f"根据《{obs['title']}》（{obs['doc_id']}，版本 {obs['version_date']}）：{clause}"
    return _finish({"answer": answer,
                    "citations": [{"doc_id": obs["doc_id"], "version": obs["version_date"], "excerpt": clause}],
                    "info_gap": None, "status": "ANSWERED"},
                   "[Mock规则] 唯一命中且已读原文、无冲突 → 依据该文档回答并附原文引用")


def decide(messages):
    """MockLLM 的 policy：依据观察历史在 检索/改写检索/读取/结束 之间确定性选择。"""
    task = _task_of(messages)
    actions, observations = _history(messages)
    last_obs = observations[-1] if observations else None

    # 尚无任何观察 → 首次检索
    if last_obs is None:
        return {"thought": "[Mock规则] 尚无观察：按问题主题发起首次检索（问题含制度用语则直接用制度用语）",
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
                    return {"thought": "[Mock规则] 首次检索 0 命中（口语问法搜不中）→ 改写为制度用语再检索一次",
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
