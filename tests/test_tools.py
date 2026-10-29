# -*- coding: utf-8 -*-
"""工具单元测试：检索敏感度（口语不中/制度用语命中）、故障注入、引用校验器红线拦截、数据可替换性。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tools  # noqa: E402


def _doc(doc_id):
    payload = json.loads((ROOT / "data" / "docs.json").read_text(encoding="utf-8"))
    return next(d for d in payload["docs"] if d["doc_id"] == doc_id)


# ---------- 检索敏感度 ----------

def test_colloquial_query_scores_zero_and_misses():
    """口语问法“在哪儿打卡”不含任何制度关键词 → 计 0 分、搜不中（刻意的措辞敏感）。"""
    result = tools.search_docs("在哪儿打卡")
    assert result["ok"] is True
    assert result["results"] == []


def test_institutional_wording_hits_after_rephrase():
    """改写为制度用语“考勤 系统”后命中 D05，且只命中 D05。"""
    result = tools.search_docs("考勤 系统")
    assert result["ok"] is True
    assert [r["doc_id"] for r in result["results"]] == ["D05"]


def test_reimbursement_query_hits_both_conflict_docs():
    """“报销期限”同时命中 D01 与 D02（无适用范围冲突对），检索结果决定后续冲突路径。"""
    result = tools.search_docs("报销期限")
    ids = [r["doc_id"] for r in result["results"]]
    assert ids == ["D01", "D02"]
    assert result["results"][0]["score"] == result["results"][1]["score"]


def test_annual_leave_unique_hit():
    result = tools.search_docs("年假")
    assert [r["doc_id"] for r in result["results"]] == ["D03"]


def test_score_prefers_longer_keyword_matches():
    """“报销期限 发票”里“发票”只在 D01 关键词中 → D01 得分高于 D02，排序在前。"""
    result = tools.search_docs("报销期限 发票")
    ids = [r["doc_id"] for r in result["results"]]
    assert ids[0] == "D01"
    scores = {r["doc_id"]: r["score"] for r in result["results"]}
    assert scores["D01"] > scores["D02"]


def test_zero_hit_returns_hint_message():
    result = tools.search_docs("公司楼下食堂本周菜单是什么")
    assert result["ok"] is True and result["results"] == []
    assert "制度用语" in result["message"]


# ---------- 读取 ----------

def test_read_doc_returns_verbatim_fields():
    result = tools.read_doc("D01")
    assert result["ok"] is True
    assert result["doc_id"] == "D01"
    assert result["title"] == _doc("D01")["title"]
    assert result["version_date"] == _doc("D01")["version_date"]
    assert result["excerpt"] == _doc("D01")["excerpt"]  # 逐字，供引用校验


def test_read_doc_missing_id():
    result = tools.read_doc("D99")
    assert result["ok"] is False
    assert "不存在" in result["error"]


# ---------- 故障注入 ----------

def test_fault_injection_search_fail():
    result = tools.search_docs("培训 学时")
    assert result["ok"] is False
    assert "检索失败" in result["error"]


def test_fault_injection_read_fail():
    result = tools.read_doc("D04")
    assert result["ok"] is False
    assert "读取文档失败" in result["error"]


# ---------- finish 校验器（引用红线） ----------

def _trace_with_read(doc_id, excerpt):
    return [{"step": 1, "thought": "", "action": "search_docs", "args": {"query": "年假"},
             "observation": {"ok": True, "query": "年假", "results": [{"doc_id": doc_id, "score": 2}]}},
            {"step": 2, "thought": "", "action": "read_doc", "args": {"doc_id": doc_id},
             "observation": {"ok": True, "doc_id": doc_id, "title": "t", "version_date": "2024-11", "excerpt": excerpt}}]


def test_validator_accepts_verbatim_citation():
    excerpt = tools.read_doc("D03")["excerpt"]
    trace = _trace_with_read("D03", excerpt)
    final = {"answer": "…", "info_gap": None, "status": "ANSWERED",
             "citations": [{"doc_id": "D03", "version": "2024-11", "excerpt": excerpt}]}
    status, out, note = tools.validate_citations(final, trace)
    assert status == "COMPLETED" and note is None
    assert len(out["citations"]) == 1


def test_validator_rejects_fabricated_excerpt():
    """编造的原文（改了数字）必须被拦截：状态 INVALID_CITATION 且引用被丢弃。"""
    excerpt = tools.read_doc("D03")["excerpt"]
    trace = _trace_with_read("D03", excerpt)
    final = {"answer": "入职满 1 年可休 99 天年假", "info_gap": None, "status": "ANSWERED",
             "citations": [{"doc_id": "D03", "version": "2024-11", "excerpt": "员工入职满 1 年可休 99 天年假"}]}
    status, out, note = tools.validate_citations(final, trace)
    assert status == "INVALID_CITATION"
    assert out["citations"] == []
    assert "99" not in json.dumps(out["citations"], ensure_ascii=False)
    assert note and "丢弃" in note


def test_validator_rejects_unread_doc_id():
    excerpt = tools.read_doc("D03")["excerpt"]
    trace = _trace_with_read("D03", excerpt)
    final = {"answer": "…", "info_gap": None, "status": "ANSWERED",
             "citations": [{"doc_id": "D05", "version": "2025-02", "excerpt": excerpt}]}  # D05 没读过
    status, out, _ = tools.validate_citations(final, trace)
    assert status == "INVALID_CITATION" and out["citations"] == []


def test_validator_intercepts_answered_without_citations():
    """ANSWERED 却没有任何引用 → 无依据回答，拦截。"""
    status, out, _ = tools.validate_citations(
        {"answer": "报销期限 30 天", "citations": [], "info_gap": None, "status": "ANSWERED"}, [])
    assert status == "INVALID_CITATION"
    assert out["status"] == "INVALID_CITATION"


def test_validator_allows_terminal_states_without_citations():
    """OUT_OF_SCOPE / TOOL_FAILED / CONFLICT 本就不带编造答案，空引用不触发拦截（冲突仍需双引用）。"""
    status, _, _ = tools.validate_citations(
        {"answer": "", "citations": [], "info_gap": "知识库无相关文档", "status": "OUT_OF_SCOPE"}, [])
    assert status == "COMPLETED"


# ---------- 数据可替换性（评审红线：不得硬编码） ----------

def test_swapped_data_changes_tool_results(tmp_path, monkeypatch):
    """替换 docs.json 内容后检索与读取必须跟着变（证明没有硬编码答案）。"""
    swapped = {"docs": [{"doc_id": "D03", "title": "员工年假管理制度（修订试行）", "version_date": "2025-09",
                         "keywords": ["年假"], "excerpt": "修订后：入职满 1 年可休 8 天年假。"}]}
    (tmp_path / "docs.json").write_text(json.dumps(swapped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tools, "DATA_DIR", tmp_path)
    assert [r["title"] for r in tools.search_docs("年假")["results"]] == ["员工年假管理制度（修订试行）"]
    assert "8 天年假" in tools.read_doc("D03")["excerpt"]
