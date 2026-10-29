# -*- coding: utf-8 -*-
"""CLI 入口：python src/cli.py --case data/cases/case-01-direct-answer.json [--llm auto|mock|real] [--trace-dir examples] [--reset-state]"""
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 【适配】import 本项目的 tools / prompts / mock_policy 与输出渲染
import mock_policy  # noqa: E402
import prompts  # noqa: E402
import tools as kb_tools  # noqa: E402
from llm import RealLLM, MockLLM  # noqa: E402
from agent import run_agent, trace_to_markdown  # noqa: E402

MAX_STEPS = 8  # q3 约定（CONVENTIONS §2.3）

BOUNDARY_NOTE = "Mock 边界：本 Trace 由离线确定性策略（src/mock_policy.py）驱动，只验证流程与状态处理，不证明真实模型的决策质量。"


def build_llm(mode):
    if mode == "mock":
        return MockLLM(mock_policy.decide), "mock"
    if mode == "real":
        return RealLLM(), "real"
    if os.getenv("LLM_API_KEY"):
        return RealLLM(), "real(auto)"
    return MockLLM(mock_policy.decide), "mock(auto)"


def run_case(case, llm_mode="mock", trace_dir=None):
    """跑一个用例（可含 1~2 个任务），返回 (output_dict, [RunResult])；trace_dir 非空则写产物。

    q3 的检索/读取均为无状态调用，任务间不共享状态文件（无 runs/state.json）；
    --reset-state 仅为对齐四项目统一 CLI 契约而保留，实际无状态可清。
    """
    llm, mode = build_llm(llm_mode)
    toolset = kb_tools.build_tools()
    tasks = case.get("tasks", [])
    results = [run_agent(task, llm, toolset, prompts.SYSTEM_PROMPT,
                         max_steps=MAX_STEPS, finish_validator=kb_tools.validate_citations,
                         llm_mode=mode)
               for task in tasks]
    output = {
        "case_id": case.get("case_id", "unknown"),
        "acceptance": case.get("acceptance", ""),
        "llm_mode": mode,
        "max_steps": MAX_STEPS,
        "tasks": [{"task": task,
                   "run_status": r.status,
                   "status": (r.final or {}).get("status"),
                   "steps_used": r.steps_used,
                   "final": r.final}
                  for task, r in zip(tasks, results)],
    }
    if trace_dir:
        out_dir = Path(trace_dir) / output["case_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "output.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        trace_payload = {"case_id": output["case_id"], "llm_mode": mode, "max_steps": MAX_STEPS,
                         "traces": [r.trace for r in results]}
        (out_dir / "trace.json").write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        parts = [f"# 用例 {output['case_id']}（验收点 {output['acceptance']}）", ""]
        for i, r in enumerate(results, 1):
            parts.append(trace_to_markdown(f"{output['case_id']} · 任务 {i}", r, BOUNDARY_NOTE))
        (out_dir / "trace.md").write_text("\n".join(parts), encoding="utf-8")
    return output, results


def main(argv=None):
    parser = argparse.ArgumentParser(description="企业知识问答 Agent（q3）")
    parser.add_argument("--case", required=True, help="用例文件路径，如 data/cases/case-01-direct-answer.json")
    parser.add_argument("--llm", choices=["auto", "mock", "real"], default="auto",
                        help="auto=有 LLM_API_KEY 用 real 否则 mock（默认）")
    parser.add_argument("--trace-dir", default=str(ROOT / "examples"), help="产物输出目录（默认 examples/）")
    parser.add_argument("--reset-state", action="store_true",
                        help="兼容统一入口：本项目检索/读取无持久化状态，该参数实际不执行任何清理")
    args = parser.parse_args(argv)

    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    output, _ = run_case(case, llm_mode=args.llm, trace_dir=Path(args.trace_dir))
    for i, entry in enumerate(output["tasks"], 1):
        print(f"[{output['case_id']}] 任务{i}: run_status={entry['run_status']} "
              f"status={entry['status']} steps={entry['steps_used']}/{output['max_steps']}")
    print(f"产物目录: {Path(args.trace_dir) / output['case_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
