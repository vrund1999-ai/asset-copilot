"""Check that every number in an answer traces back to a tool result.

Policy: a number is grounded if it matches (within the precision it was written at) a value in a
cited query result, a cited calculation result, a row count of a cited query, or a number the user
wrote in the question. Dates, query/calc labels and list indexes are exempt.

Signs are ignored ("down 5%" matches -5), because direction is stated in words.
"""

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from .tools import CalcRecord, QueryRecord

_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_EXEMPT = [
    re.compile(r"\b[QC]\d+\b"),  # Q1 / C2 labels (also quarter names)
    re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b"),  # ISO dates
    re.compile(rf"\b{_MONTHS}\.?\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.IGNORECASE),
    re.compile(r"^\s*\d+[.)]\s", re.MULTILINE),  # list indexes
]
_NUM = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?P<suf>\s?%|\s?(?:percent|thousand|million|billion)\b|[KkMmBb]\b)?"
)
_MULT = {"k": 10**3, "thousand": 10**3, "m": 10**6, "million": 10**6,
         "b": 10**9, "billion": 10**9}


def _strip_exempt(text: str) -> str:
    for pat in _EXEMPT:
        text = pat.sub(" ", text)
    return text


def extract_numbers(text: str) -> list[tuple[str, Decimal, Decimal, bool]]:
    """Return (original, value, tolerance, is_percent) for each number in text."""
    out = []
    for m in _NUM.finditer(_strip_exempt(text)):
        raw = m.group("num")
        # A trailing comma/period is punctuation, not part of the number.
        digits = raw.rstrip(",").replace(",", "")
        try:
            value = Decimal(digits)
        except InvalidOperation:
            continue
        suf = (m.group("suf") or "").strip().lower()
        is_pct = suf in ("%", "percent")
        mult = Decimal(_MULT.get(suf, 1))
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        unit = Decimal(1).scaleb(-decimals) * mult  # size of the last written digit
        out.append((m.group(0).strip(), value * mult if not is_pct else value,
                    unit / 2 * Decimal("1.0001"), is_pct))
    return out


def _numeric(v) -> Decimal | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float | Decimal):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    if isinstance(v, str):
        try:
            return Decimal(v.strip())
        except InvalidOperation:
            return None
    return None


def build_pool(
    question: str, queries: Iterable[QueryRecord], calcs: Iterable[CalcRecord]
) -> list[Decimal]:
    pool: list[Decimal] = []
    pool.extend(v for _, v, _, _ in extract_numbers(question))
    for q in queries:
        pool.append(Decimal(len(q.rows)))
        for row in q.rows:
            for v in row.values():
                n = _numeric(v)
                if n is not None:
                    pool.append(n)
    pool.extend(c.result for c in calcs)
    return [abs(p) for p in pool]


def find_ungrounded(
    answer: str, question: str, queries: Iterable[QueryRecord], calcs: Iterable[CalcRecord]
) -> list[str]:
    """Numbers in `answer` that match nothing in the cited results. Empty list means grounded."""
    pool = build_pool(question, queries, calcs)
    bad = []
    for original, value, tol, is_pct in extract_numbers(answer):
        value = abs(value)
        candidates = [(value, tol)]
        if is_pct:  # 12.5% may be stored as the fraction 0.125
            candidates.append((value / 100, tol / 100))
        if not any(abs(value_c - p) <= tol_c for value_c, tol_c in candidates for p in pool):
            bad.append(original)
    return bad
