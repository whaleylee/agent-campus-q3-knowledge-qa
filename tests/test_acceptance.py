# -*- coding: utf-8 -*-
"""验收测试：六个验收点逐条断言（离线 Mock 驱动）+ 红线拦截 + 步数上限。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import run_agent  # noqa: E402
from llm import MockLLM  # noqa: E402
import mock_policy  # noqa: E402
import prompts  # noqa: E402
import tools  # noqa: E402
from cli import run_case  # noqa: E402


def _run(case_name):
    case = json.loads((ROOT / "data" / "cases" / f"{case_name}.json").read_text(encoding="utf-8"))
    return run_case(case, llm_mode="mock", trace_dir=None)


def _doc(doc_id):
    payload = json.loads((ROOT / "data" / "docs.json").read_text(encoding="utf-8"))
    return next(d for d in payload["docs"] if d["doc_id"] == doc_id)


# ---------- A1 明确答案 ----------

def test_case_01_direct_answer():
    output, results = _run("case-01-direct-answer")
    entry = output["tasks"][0]
    assert entry["run_status"] == "COMPLETED"
    assert entry["status"] == "ANSWERED"
    final = entry["final"]
    # 唯一命中 D03，引用支持回答
    assert len(final["citations"]) == 1
    cite = final["citations"][0]
    assert cite["doc_id"] == "D03"
    assert cite["excerpt"] in _doc("D03")["excerpt"]          # 逐字来自知识库原文
    assert cite["excerpt"] in results[0].trace[1]["observation"]["excerpt"]  # 且来自本次 read_doc 观察
    assert "5 天" in final["answer"] and "5 天" in cite["excerpt"]
    assert final["info_gap"] is None
    # 流程：检索一次 → 读取一次 → finish
    actions = [e["action"] for e in results[0].trace]
    assert actions == ["search_docs", "read_doc", "finish"]


# ---------- A2 文档冲突 ----------

def test_case_02_conflict():
    output, results = _run("case-02-conflict")
    entry = output["tasks"][0]
    assert entry["status"] == "CONFLICT_NEED_CONFIRM"
    final = entry["final"]
    # 双引用：D01 与 D02，excerpt 均逐字
    cites = {c["doc_id"]: c for c in final["citations"]}
    assert set(cites) == {"D01", "D02"}
    for doc_id, cite in cites.items():
        assert cite["excerpt"] in _doc(doc_id)["excerpt"]
    # answer 列出双方取值并请求确认，不含单边结论、不按版本日期裁决
    assert "30" in final["answer"] and "15" in final["answer"]
    assert "D01" in final["answer"] and "D02" in final["answer"]
    assert "请确认" in final["answer"]
    assert "以新版本为准" not in final["answer"] and "版本更新" not in final["answer"]
    assert final["info_gap"] and "确认" in final["info_gap"]
    # 先读两篇原文再 finish（检索结果决定行为）
    actions = [e["action"] for e in results[0].trace]
    assert actions == ["search_docs", "read_doc", "read_doc", "finish"]


# ---------- A3 资料外问题 ----------

def test_case_03_out_of_scope():
    output, results = _run("case-03-out-of-scope")
    entry = output["tasks"][0]
    assert entry["status"] == "OUT_OF_SCOPE"
    final = entry["final"]
    assert final["answer"] == ""                 # 不编造
    assert final["citations"] == []              # 不产生引用
    assert final["info_gap"]                     # 明确资料缺口
    # 没有读取过任何文档（没有可引用的依据）
    assert all(e["action"] != "read_doc" for e in results[0].trace)


# ---------- A4 改写后的相似问题 ----------

def test_case_04_rephrase():
    output, results = _run("case-04-rephrase")
    entry = output["tasks"][0]
    assert entry["status"] == "ANSWERED"
    searches = [e for e in results[0].trace if e["action"] == "search_docs"]
    assert len(searches) == 2                                    # 首查 + 改写再查
    queries = [e["args"]["query"] for e in searches]
    assert queries[0] == "在哪儿打卡" and queries[1] == "考勤 系统"
    assert queries[0] != queries[1]                              # 两次 query 不同
    assert searches[0]["observation"]["results"] == []           # 首查口语 0 命中
    assert searches[1]["observation"]["results"]                 # 改写后命中
    final = entry["final"]
    cite = final["citations"][0]
    assert cite["doc_id"] == "D05"
    assert cite["excerpt"] in _doc("D05")["excerpt"]
    assert "OA" in final["answer"]


# ---------- A5 上下文追问 ----------

def test_case_05_followup():
    output, results = _run("case-05-followup")
    entry = output["tasks"][0]
    assert entry["status"] == "ANSWERED"
    final = entry["final"]
    cite = final["citations"][0]
    assert cite["doc_id"] == "D02"                               # “15 天那份”定位到 D02，而非 D01
    assert cite["excerpt"] in _doc("D02")["excerpt"]
    assert "费用报销补充规定" in final["answer"]
    assert "2025-06" in final["answer"]


# ---------- A6 工具失败 ----------

def test_case_06_tool_fail():
    output, results = _run("case-06-tool-fail")
    assert len(output["tasks"]) == 2
    for entry, result in zip(output["tasks"], results):
        assert entry["status"] == "TOOL_FAILED"
        assert entry["final"]["answer"] == ""                    # 不编造答案
        assert entry["final"]["citations"] == []
        assert "失败" in entry["final"]["info_gap"]
        assert entry["run_status"] == "COMPLETED"                # 流程正常走完，业务终态为 TOOL_FAILED
    # 任务 1：检索失败（观察 ok=false 后立即停止）
    obs1 = [e for e in results[0].trace if "observation" in e][-1]["observation"]
    assert obs1["ok"] is False and "检索失败" in obs1["error"]
    # 任务 2：检索命中 D04 后读取失败
    actions2 = [e["action"] for e in results[1].trace]
    assert actions2 == ["search_docs", "read_doc", "finish"]
    obs2 = results[1].trace[1]["observation"]
    assert obs2["ok"] is False and "读取文档失败" in obs2["error"]


# ---------- 红线：编造引用必须被 finish 校验器拦截 ----------

def _lying_policy(messages):
    """先读 D03，再 finish 一条编造引用（excerpt 数字被改、非观察原文）。"""
    has_obs = any(m.get("role") == "user" and str(m.get("content", "")).startswith("OBSERVATION: ")
                  for m in messages)
    if not has_obs:
        return {"thought": "[Mock规则] 先读年假文档", "action": "read_doc", "args": {"doc_id": "D03"}}
    return {"thought": "[Mock规则] 尝试带编造引用收尾", "action": "finish", "args": {},
            "final": {"answer": "入职满 1 年可休 99 天年假。",
                      "citations": [{"doc_id": "D03", "version": "2024-11",
                                     "excerpt": "员工入职满 1 年可休 99 天年假"}],
                      "info_gap": None, "status": "ANSWERED"}}


def test_fabricated_citation_is_intercepted():
    result = run_agent("入职满一年有多少天年假？", MockLLM(_lying_policy), tools.build_tools(),
                       prompts.SYSTEM_PROMPT, max_steps=8,
                       finish_validator=tools.validate_citations, llm_mode="mock")
    assert result.status == "INVALID_CITATION"                   # 运行状态被改写
    assert result.final["status"] == "INVALID_CITATION"          # 业务状态同步降级
    assert result.final["citations"] == []                       # 违规引用被丢弃
    assert "99" not in json.dumps(result.final["citations"], ensure_ascii=False)
    last = result.trace[-1]
    assert last.get("validator_note") and "丢弃" in last["validator_note"]


# ---------- 步数上限 ----------

def test_max_steps_cap():
    def loop_policy(messages):
        return {"thought": "[Mock规则] 一直检索不停（测试步数上限）", "action": "search_docs", "args": {"query": "年假"}}

    result = run_agent("年假", MockLLM(loop_policy), tools.build_tools(), prompts.SYSTEM_PROMPT,
                       max_steps=8, llm_mode="mock")
    assert result.status == "INCOMPLETE_MAX_STEPS"
    assert result.steps_used == 8 and result.final is None
