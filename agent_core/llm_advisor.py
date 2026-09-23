"""Optional LLM strategist with guardrails.

Active only when OPENAI_API_KEY is set. The model sees our posterior table and may:
  * reorder which of OUR top-6 open arms get confirmed first (no new arms);
  * flag arms it finds suspicious (logged, passed to the final review);
  * remove final campaigns (never add or edit them, never remove all of them).
Every call: temperature 0, JSON schema output, 20 s timeout, at most MAX_CALLS per run.
Any error, timeout or invalid answer -> our deterministic decision stands.
Every decision (accepted, rejected or failed) is appended to self.log and logged.
"""

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
TIMEOUT_S = 20
MAX_CALLS = 3
TOP_K = 6

SYSTEM_PROMPT = (
    "You advise a telecom tariff-migration campaign agent. Each arm is "
    "(current_tariff, arpu_segment) -> target_tariff. 'base_mean'/'base_sd' is our Bayesian "
    "posterior of the relative ARPU effect at channel multiplier 1.0 (prior from history, "
    "updated by noisy pilots, pilot noise sd = 0.804/sqrt(n)/multiplier). Large effects from a "
    "single small pilot, or a posterior far from its prior, are typical winner's-curse signs. "
    "Answer only with JSON matching the schema."
)

RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "order": {"type": "array", "items": {"type": "string"}},
        "suspicious": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["order", "suspicious", "reason"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "remove": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["remove", "reason"],
    "additionalProperties": False,
}


def arm_id(cell, target):
    return f"{cell[0]}|{cell[1]}|{target}"


def _str_list(answer, key):
    value = answer.get(key)
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _http_transport(messages, schema_name, schema):
    """POST to the chat completions endpoint and return the parsed JSON answer."""
    body = {
        "model": os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
        "temperature": 0,
        "messages": messages,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
    }
    base = (os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return json.loads(payload["choices"][0]["message"]["content"])


class LLMAdvisor:
    def __init__(self, transport=None):
        self.enabled = bool(os.environ.get("OPENAI_API_KEY")) or transport is not None
        self._transport = transport or _http_transport
        self.calls = 0
        self.suspicious = []
        self.log = []

    def _record(self, step, **entry):
        entry = {"step": step, **entry}
        self.log.append(entry)
        logger.info("llm_advisor %s", json.dumps(entry, ensure_ascii=False, default=str))

    def _ask(self, step, payload, schema_name, schema):
        if not self.enabled:
            return None
        if self.calls >= MAX_CALLS:
            self._record(step, status="skipped", reason="call limit reached")
            return None
        self.calls += 1
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        try:
            answer = self._transport(messages, schema_name, schema)
            if not isinstance(answer, dict):
                raise ValueError("answer is not a JSON object")
            return answer
        except Exception as e:  # network, timeout, HTTP error, bad JSON: fall back
            self._record(step, status="failed", error=f"{type(e).__name__}: {e}")
            return None

    def rank_confirmations(self, arms, table):
        """arms: our open arms in our order. Returns the new order (only top-6 reordered)."""
        top = arms[:TOP_K]
        ids = [arm_id(c, t) for c, t in top]
        answer = self._ask("rank_confirmations",
                           {"task": "Order these arm ids by which to confirm first with a "
                                    "200-customer pilot; flag suspicious arm ids.",
                            "candidates": ids, "posterior_table": table},
                           "rank_confirmations", RANK_SCHEMA)
        if answer is None:
            return arms
        order = _str_list(answer, "order")
        suspicious = _str_list(answer, "suspicious")
        valid = [i for i in dict.fromkeys(order) if i in ids]  # only our top-6, no duplicates
        valid += [i for i in ids if i not in valid]            # nothing may be dropped
        by_id = dict(zip(ids, top))
        self.suspicious = suspicious
        self._record("rank_confirmations", status="applied", ours=ids, llm=order,
                     applied=valid, ignored=[i for i in order if i not in ids],
                     suspicious=self.suspicious, reason=answer.get("reason"))
        return [by_id[i] for i in valid] + arms[TOP_K:]

    def review_finals(self, campaigns, table):
        """May only remove campaigns by name; never adds, edits, or empties the list."""
        names = [c["campaign_name"] for c in campaigns]
        answer = self._ask("review_finals",
                           {"task": "Return names of final campaigns to REMOVE because their "
                                    "evidence looks unreliable; empty list keeps all.",
                            "campaigns": campaigns, "suspicious_arms": self.suspicious,
                            "posterior_table": table},
                           "review_finals", REVIEW_SCHEMA)
        if answer is None:
            return campaigns
        remove = _str_list(answer, "remove")
        drop = {n for n in remove if n in names}
        if drop and len(drop) == len(names):
            self._record("review_finals", status="rejected", llm=remove,
                         reason="would remove every campaign", llm_reason=answer.get("reason"))
            return campaigns
        kept = [c for c in campaigns if c["campaign_name"] not in drop]
        self._record("review_finals", status="applied", llm=remove, removed=sorted(drop),
                     ignored=[n for n in remove if n not in names], reason=answer.get("reason"))
        return kept
