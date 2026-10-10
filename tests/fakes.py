from ielts.llm.base import LLMProvider


class FakeProvider(LLMProvider):
    """Devuelve respuestas predefinidas en orden y registra las llamadas."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, system, user, *, temperature, json_schema=None, seed=None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature,
                           "schema": json_schema, "seed": seed})
        return self.responses.pop(0)
