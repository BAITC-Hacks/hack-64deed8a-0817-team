"""Optional LLM strategist with guardrails.

Active only when AGENT_USE_LLM=1 and OPENAI_API_KEY are both set (a key alone does
nothing, so a machine with a key still runs fully deterministically). The model sees our posterior table and may:
  * reorder which of OUR top-6 open arms get confirmed first (no new arms);
  * flag arms it finds suspicious (logged, passed to the final review);
  * remove final campaigns (never add or edit them, never remove all of them).
Every call: temperature 0, JSON schema output, a hard 20 s wall-clock deadline covering
the whole request and body read (the worker thread is abandoned on expiry), at most MAX_CALLS per run,
and no new call once TIME_BUDGET_S seconds have been spent in calls in total.
Models that only accept the default temperature (the API rejects 0 with
param "temperature") are retried once without it; that choice is logged and kept.
Any error, timeout or invalid answer -> our deterministic decision stands.
Every decision (accepted, rejected or failed) is appended to self.log and logged.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
TIMEOUT_S = 20
MAX_CALLS = 3
TIME_BUDGET_S = 90  # cumulative wall time in LLM calls per run; further calls are skipped
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


def _call_with_deadline(fn, timeout):
    """Run fn() in a daemon thread; give up (TimeoutError) after `timeout` seconds."""
    outcome = {}

    def worker():
        try:
            outcome["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            outcome["error"] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"LLM call exceeded {timeout}s wall clock; abandoned")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


class TemperatureUnsupported(Exception):
    """The model rejected temperature=0 (only its default is allowed)."""


def _post(body):
    base = (os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            error = json.loads(detail).get("error") or {}
        except ValueError:
            error = {}
        if e.code == 400 and error.get("param") == "temperature":
            raise TemperatureUnsupported(error.get("message", "")) from e
        raise RuntimeError(f"HTTP {e.code}: {error.get('message') or detail[:300]}") from e
    return json.loads(payload["choices"][0]["message"]["content"])


def _http_body(messages, schema_name, schema, temperature):
    body = {
        "model": os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
        "messages": messages,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
    }
    if temperature:
        body["temperature"] = 0
    return body


class LLMAdvisor:
    def __init__(self, transport=None, clock=time.monotonic):
        self.enabled = transport is not None or (
            os.environ.get("AGENT_USE_LLM") == "1" and bool(os.environ.get("OPENAI_API_KEY")))
        self._transport = transport or self._http_transport
        self._clock = clock
        self._temperature_zero = True
        self.calls = 0
        self.elapsed = 0.0
        self.suspicious = []
        self.log = []

    def _http_transport(self, messages, schema_name, schema):
        """POST to chat completions; drop temperature=0 once if the model rejects it."""
        try:
            return _post(_http_body(messages, schema_name, schema, self._temperature_zero))
        except TemperatureUnsupported as e:
            if not self._temperature_zero:
                raise
            self._temperature_zero = False
            self._record(schema_name, status="temperature_default",
                         reason=f"model rejected temperature=0, using its default: {e}")
            return _post(_http_body(messages, schema_name, schema, False))

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
        if self.elapsed >= TIME_BUDGET_S:
            self._record(step, status="skipped",
                         reason=f"time budget spent: {self.elapsed:.1f}s >= {TIME_BUDGET_S}s")
            return None
        self.calls += 1
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        started = self._clock()
        try:
            answer = _call_with_deadline(
                lambda: self._transport(messages, schema_name, schema), TIMEOUT_S)
            if not isinstance(answer, dict):
                raise ValueError("answer is not a JSON object")
            return answer
        except Exception as e:  # network, timeout, HTTP error, bad JSON: fall back
            self._record(step, status="failed", error=f"{type(e).__name__}: {e}")
            return None
        finally:
            self.elapsed += self._clock() - started

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
                            "campaigns": [{**c, "arm": arm_id((c.get("filter_current_tariff"),
                                                                c.get("filter_arpu_segment")),
                                                               c.get("target_tariff"))}
                                          for c in campaigns],
                            "suspicious_arms": self.suspicious,
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
