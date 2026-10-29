# -*- coding: utf-8 -*-
"""一键用 Mock 重跑全部用例并重建 examples/。用法：PYTHONUTF8=1 python run_examples.py"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import cli  # noqa: E402


def main():
    cases_dir = ROOT / "data" / "cases"
    examples_dir = ROOT / "examples"
    examples_dir.mkdir(exist_ok=True)
    # 重建 examples/：只清理本脚本生成的用例目录，保留 .gitkeep 等占位文件
    for old in examples_dir.glob("case-*"):
        if old.is_dir():
            shutil.rmtree(old)

    rows = []
    for path in sorted(cases_dir.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        output, _ = cli.run_case(case, llm_mode="mock", trace_dir=examples_dir)
        statuses = " / ".join(f"任务{i}:{entry['status']}" for i, entry in enumerate(output["tasks"], 1))
        rows.append((output["case_id"], statuses))

    print("=" * 76)
    print(f"{'用例':<26}状态（业务终态，Mock 模式）")
    print("-" * 76)
    for case_id, statuses in rows:
        print(f"{case_id:<28}{statuses}")
    print("-" * 76)
    print(f"共 {len(rows)} 个用例；产物见 examples/<case_id>/ 下的 output.json / trace.json / trace.md")
    print("Mock 边界：只验证流程与状态处理，不证明真实模型的决策质量。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
