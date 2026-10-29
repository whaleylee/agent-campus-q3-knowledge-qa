"""LLM 接入层：RealLLM（OpenAI 兼容 /chat/completions）与 MockLLM（离线确定性策略）。"""
import json
import os


class RealLLM:
    """真实模型。需要环境变量 LLM_API_KEY，可选 LLM_BASE_URL / LLM_MODEL。"""

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        if not self.api_key:
            raise RuntimeError("未配置 LLM_API_KEY：无法使用真实模型，请改用 --llm mock")

    def chat(self, messages):
        import requests
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, "temperature": 0.2},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class MockLLM:
    """离线 Mock：调用项目提供的 policy(messages) 函数，依据对话（含工具观察）确定性选动作。

    边界声明：Mock 只验证流程与状态处理，不证明真实模型的决策质量。
    """

    def __init__(self, policy):
        self.policy = policy

    def chat(self, messages):
        return json.dumps(self.policy(messages), ensure_ascii=False)
