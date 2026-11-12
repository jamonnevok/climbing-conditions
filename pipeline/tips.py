"""Rule-based tips engine. Rules live in config/tips.yaml, texts in config/i18n.

FACTS available to rules (per day, computed on that day's climbing hours from the
reference time = max(day start, now)):
  day_score, t_mean_c, t_max_c, rh_mean, spread_mean_c, wind_mean_ms, wind_max_ms,
  rain_prev48_mm, wet_start_mm, hours_to_dry (-1 = not within forecast), sun_fraction,
  has_better_window, temp_lo, temp_hi, dry_ok_mm
"""
from __future__ import annotations

import operator

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
       "==": operator.eq, "!=": operator.ne}


def _resolve(v, facts):
    if isinstance(v, str) and v.startswith("$"):
        return facts.get(v[1:])
    return v


def _cond(c, facts) -> bool:
    fact, op, value = c
    a, b = facts.get(fact), _resolve(value, facts)
    if a is None or b is None:
        return False  # unknown facts never trigger a tip
    return OPS[op](a, b)


def matches(when: dict, facts: dict) -> bool:
    ok = True
    if "all" in when:
        ok = ok and all(_cond(c, facts) for c in when["all"])
    if "any" in when:
        ok = ok and any(_cond(c, facts) for c in when["any"])
    return ok


def select(rules_cfg: dict, facts: dict, params: dict) -> list[dict]:
    hits = [r for r in rules_cfg["rules"] if matches(r["when"], facts)]
    hits.sort(key=lambda r: -r["priority"])
    return [{"key": r["key"], "params": params} for r in hits[: rules_cfg["max_tips"]]]


def validate(rules_cfg: dict, i18n: dict) -> list[str]:
    """Return problems: unknown operators or missing translations."""
    problems = []
    for r in rules_cfg["rules"]:
        for part in ("all", "any"):
            for c in r["when"].get(part, []):
                if len(c) != 3 or c[1] not in OPS:
                    problems.append(f"rule {r['id']}: bad condition {c}")
        for lang, t in i18n.items():
            if r["key"] not in t.get("tips", {}):
                problems.append(f"rule {r['id']}: missing '{lang}' translation tips.{r['key']}")
    return problems
