"""通用 ReAct 循环：模型选择动作 -> 执行工具 -> 观察结果 -> 调整下一步或结束。"""
import json
import re


def extract_json(text):
    """从模型输出中提取第一个 JSON 对象；容忍 ```json 代码块与前后杂文。"""
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"输出不是 JSON: {text[:120]}")
    return json.loads(text[start : end + 1])


class RunResult:
    def __init__(self, status, final, trace, steps_used, max_steps, llm_mode):
        self.status = status          # COMPLETED / INCOMPLETE_MAX_STEPS / 项目自定义终态
        self.final = final            # finish 载荷（可能被 finish_validator 改写）
        self.trace = trace            # [{step, thought, action, args, observation?, finish?}]
        self.steps_used = steps_used
        self.max_steps = max_steps
        self.llm_mode = llm_mode


def run_agent(task, llm, tools, system_prompt, max_steps=8, finish_validator=None, llm_mode="mock"):
    """执行一个任务的 ReAct 循环。tools: {name: {"desc", "params", "fn"}}。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]
    trace = []
    for step in range(1, max_steps + 1):
        raw = llm.chat(messages)
        try:
            decision = extract_json(raw)
        except ValueError as err:
            observation = {"ok": False, "error": f"输出格式错误，请输出纯 JSON：{err}"}
            trace.append({"step": step, "thought": "", "action": "(unparseable)", "args": {},
                          "observation": observation})
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": "OBSERVATION: " + json.dumps(observation, ensure_ascii=False)}]
            continue
        action = decision.get("action", "")
        args = decision.get("args", {}) or {}
        entry = {"step": step, "thought": decision.get("thought", ""), "action": action, "args": args}
        if action == "finish":
            final = decision.get("final", {}) or {}
            status = "COMPLETED"
            if finish_validator:
                status, final, note = finish_validator(final, trace)
                if note:
                    entry["validator_note"] = note
            entry["finish"] = True
            trace.append(entry)
            return RunResult(status, final, trace, step, max_steps, llm_mode)
        tool = tools.get(action)
        if tool is None:
            observation = {"ok": False, "error": f"未知工具 {action}，可用: {sorted(tools)}"}
        elif not isinstance(args, dict):
            observation = {"ok": False, "error": "args 必须是 JSON 对象"}
        else:
            try:
                observation = tool["fn"](**args)
            except TypeError as err:
                observation = {"ok": False, "error": f"参数不匹配: {err}"}
            except Exception as err:  # 工具内部异常不得炸掉循环
                observation = {"ok": False, "error": f"工具执行异常: {err}"}
        entry["observation"] = observation
        trace.append(entry)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "OBSERVATION: " + json.dumps(observation, ensure_ascii=False)}]
    return RunResult("INCOMPLETE_MAX_STEPS", None, trace, max_steps, max_steps, llm_mode)


def trace_to_markdown(case_id, result, boundary_note):
    """把 trace 渲染成 markdown（存 examples/<case>/trace.md）。"""
    lines = [f"# Trace — {case_id}", "",
             f"- 状态: **{result.status}** | 步数: {result.steps_used}/{result.max_steps} | LLM: {result.llm_mode}",
             f"- {boundary_note}", ""]
    for e in result.trace:
        lines.append(f"## Step {e['step']} — `{e['action']}`")
        if e.get("thought"):
            lines.append(f"**决策依据**: {e['thought']}")
        if "args" in e and e["args"]:
            lines.append(f"**工具参数**: `{json.dumps(e['args'], ensure_ascii=False)}`")
        if "observation" in e:
            obs = json.dumps(e["observation"], ensure_ascii=False)
            lines.append(f"**返回摘要**: `{obs[:400]}{'…' if len(obs) > 400 else ''}`")
        if e.get("validator_note"):
            lines.append(f"**校验器**: {e['validator_note']}")
        lines.append("")
    lines.append("> 候选人批注（可选，建议写一句人话观察，例如哪一步模型差点走错被护栏拦住）：")
    lines.append("> ")
    return "\n".join(lines)
