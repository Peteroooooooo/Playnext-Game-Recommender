"""OpenAI-compatible chat client (design 10.9). Only preference text and game descriptions are sent, never SteamIDs
or library data. Replies may come wrapped in ```json fences; `chat_json` strips them before parsing."""
import json
import re
import time

from .pricing import load_env


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, timeout=60):
        env = load_env()
        if not env.get("LLM_BASE_URL"):
            raise LLMError("LLM_BASE_URL missing in .env")
        from openai import OpenAI
        self.client = OpenAI(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], timeout=timeout, max_retries=1)
        self.model = env["LLM_MODEL"]
        self.calls = []  # (purpose, seconds) for the latency report

    def chat(self, system, user, purpose="", temperature=0):
        t0 = time.time()
        r = self.client.chat.completions.create(model=self.model, temperature=temperature,
                                                messages=[{"role": "system", "content": system},
                                                          {"role": "user", "content": user}])
        self.calls.append((purpose, round(time.time() - t0, 1)))
        return r.choices[0].message.content or ""


def strip_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    m = re.search(r"\{.*\}|\[.*\]", raw, re.S)
    return m.group(0) if m else raw


def chat_json(llm, system, user, purpose="", validate=None):
    """Ask, parse, validate; on failure retry once with the error appended (design 5.5). Raises LLMError."""
    err = None
    for attempt in range(2):
        u = user if err is None else f"{user}\n\nYour previous reply was invalid: {err[:300]}. Return valid JSON only."
        raw = llm.chat(system, u, purpose)
        try:
            obj = json.loads(strip_json(raw))
            return validate(obj) if validate else obj
        except Exception as e:  # malformed JSON or schema error
            err = str(e)
    raise LLMError(f"LLM output invalid twice: {err[:200]}")
