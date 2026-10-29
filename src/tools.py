# -*- coding: utf-8 -*-
"""q3 项目工具：知识库检索 / 原文读取（每次真实读 data/*.json，支持故障注入）
与 finish 校验器 validate_citations（防“无依据回答 / 错误引用”红线）。

检索对措辞敏感是刻意设计：计分只看每篇文档的 keywords 数组是否作为子串出现在 query 里，
口语问法（如“在哪儿打卡”）不含制度关键词时计 0 分、搜不中；改写为制度用语
（如“考勤 系统”）后才命中。这条“假阴性”用于验证 ReAct 的检索改进路径（A4）。
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_docs():
    """每次调用都重新读盘：评审替换 data/docs.json 内容后，检索与读取结果随之改变（答案不硬编码）。"""
    payload = json.loads((DATA_DIR / "docs.json").read_text(encoding="utf-8"))
    return payload["docs"]


def _load_faults():
    path = DATA_DIR / "faults.json"
    if not path.exists():
        return {"search_fail_query_substrings": [], "read_fail_doc_ids": []}
    return json.loads(path.read_text(encoding="utf-8"))


def all_docs():
    """返回全部文档（供检索词反查使用）：与检索/读取一样每次重读盘，替换 docs.json 即改变反查结果。"""
    return _load_docs()


def load_rewrite_terms():
    """口语→制度用语改写表（data/terms.json，外置数据）：改表即改改写行为，代码不写死任何词表。"""
    path = DATA_DIR / "terms.json"
    if not path.exists():
        return {"terms": []}
    return json.loads(path.read_text(encoding="utf-8"))


def search_docs(query):
    """关键词计分检索。返回 {ok, query, results:[{doc_id,title,version_date,score}]}。

    计分：文档 keywords 中每个关键词若作为子串出现在 query 里，累加该关键词的字符长度；
    得分 > 0 才算命中，按得分降序、doc_id 升序排列。query 命中 faults.json 的
    search_fail_query_substrings 任一子串时直接返回失败（故障注入，A6）。
    """
    query = (query or "").strip()
    for sub in _load_faults().get("search_fail_query_substrings", []):
        if sub and sub in query:
            return {"ok": False,
                    "error": f"知识库检索失败（故障注入）：query 含“{sub}”，检索服务暂时不可用，请稍后重试"}
    results = []
    for doc in _load_docs():
        score = sum(len(kw) for kw in doc.get("keywords", []) if kw and kw in query)
        if score > 0:
            results.append({"doc_id": doc["doc_id"], "title": doc["title"],
                            "version_date": doc["version_date"], "score": score})
    results.sort(key=lambda r: (-r["score"], r["doc_id"]))
    payload = {"ok": True, "query": query, "results": results}
    if not results:
        payload["message"] = "0 命中：当前问法未匹配任何文档关键词，可改写为制度用语（如 考勤/报销期限）后重试"
    return payload


def read_doc(doc_id):
    """读取文档原文片段。引用（citations 的 excerpt）只允许逐字来自本工具返回的 excerpt。"""
    if doc_id in _load_faults().get("read_fail_doc_ids", []):
        return {"ok": False, "error": f"读取文档失败（故障注入）：{doc_id} 存储服务暂时不可用"}
    for doc in _load_docs():
        if doc["doc_id"] == doc_id:
            return {"ok": True, "doc_id": doc["doc_id"], "title": doc["title"],
                    "version_date": doc["version_date"], "excerpt": doc["excerpt"]}
    return {"ok": False, "error": f"文档不存在: {doc_id}"}


def build_tools():
    """组装 agent.py 需要的 tools 字典：{name: {"desc", "params", "fn"}}。"""
    return {
        "search_docs": {"desc": "文档检索（关键词计分，对措辞敏感；口语问法可能 0 命中，可改写为制度用语重试）",
                        "params": {"query": "str"}, "fn": search_docs},
        "read_doc": {"desc": "读取文档原文片段（引用的唯一来源）",
                     "params": {"doc_id": "str"}, "fn": read_doc},
    }


def validate_citations(final, trace):
    """finish 校验器（本题灵魂，防一票否决红线）。

    规则（代码级防线，不靠模型自觉）：
    1. final.citations 每条引用的 doc_id 必须是本次 trace 里 read_doc 成功读取过的文档；
    2. excerpt 必须逐字出现在那次读取观察的 excerpt 里（不得改写/拼接/编造）；
    3. 违规引用直接丢弃，业务状态与运行状态均改为 INVALID_CITATION，并在 trace 记 validator_note；
    4. status=ANSWERED 却没有任何可核实引用 → 同样按“无依据回答”拦截。

    返回 (run_status, final, note)，供 agent.run_agent 的 finish_validator 协议使用。
    """
    read_pool = {}  # doc_id -> 本次 trace 中成功读到的 excerpt
    for entry in trace:
        if entry.get("action") == "read_doc":
            obs = entry.get("observation") or {}
            if obs.get("ok") and obs.get("doc_id") and obs.get("excerpt"):
                read_pool[obs["doc_id"]] = obs["excerpt"]

    final = dict(final or {})
    kept, dropped = [], []
    for cite in final.get("citations") or []:
        if (isinstance(cite, dict)
                and cite.get("doc_id") in read_pool
                and isinstance(cite.get("excerpt"), str)
                and cite["excerpt"]
                and cite["excerpt"] in read_pool[cite["doc_id"]]):
            kept.append(cite)
        else:
            dropped.append(cite)

    if not dropped:
        if final.get("status") == "ANSWERED" and not kept:
            final["status"] = "INVALID_CITATION"
            final["citations"] = []
            final["info_gap"] = "引用校验失败：回答声明 ANSWERED，但没有任何能在 read_doc 观察中逐字核实的引用，按无依据回答拦截。"
            return "INVALID_CITATION", final, "ANSWERED 缺少可核实引用 → 拦截（无依据回答）"
        return "COMPLETED", final, None

    dropped_ids = [c.get("doc_id") if isinstance(c, dict) else str(c) for c in dropped]
    final["citations"] = kept
    final["status"] = "INVALID_CITATION"
    note = f"丢弃 {len(dropped)} 条无法在本次 read_doc 观察中逐字核实的引用：{dropped_ids}"
    final["info_gap"] = f"引用校验失败：{note}。" + (final.get("info_gap") or "")
    return "INVALID_CITATION", final, note
