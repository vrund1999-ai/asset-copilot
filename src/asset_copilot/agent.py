"""Agent loop (Claude tool use) for SQL questions.

Tools: run_sql, calculate, search_documents, submit_answer. The loop ends when the model calls submit_answer with a
valid, grounded answer, or fails safely (iteration cap, too many SQL errors, refusal, truncation).

Design rules (see docs/ROADMAP.md, M1):
  - Citations are built by code from queries that actually ran, never from model claims.
  - Every number in an answer must trace to a cited query/calculation result (grounding.py).
  - Every step is written to audit_log with the session id.
"""

import contextlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import anthropic

from . import db
from .config import settings
from .grounding import find_ungrounded
from .prompts import build_system_prompt
from .schemas import AskResponse, Citation
from .tools import (
    TOOLS,
    RunContext,
    format_decimal,
    run_calculate,
    run_search_documents,
    run_sql,
)

CANNOT_DETERMINE = "I can't determine that from the data."
SUBMIT_NUDGE = (
    "You did not call a tool. Finish by calling submit_answer (status 'answered' with query_ids, "
    "or doc_ids, or 'cannot_determine')."
)


class AgentConfigError(RuntimeError):
    """The agent cannot run because it is not configured (e.g. no API key)."""


@dataclass
class _Final:
    status: str
    answer: str
    query_ids: list[str] = field(default_factory=list)
    calc_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    grounded: bool = True


def build_client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise AgentConfigError("ANTHROPIC_API_KEY is not set. Add it to .env and restart the API.")
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key, timeout=settings.anthropic_timeout, max_retries=2
    )


def _audit(action: str, detail: dict, session_id: str) -> None:
    db.audit(action, detail, session_id)


def _usage(resp: Any) -> dict[str, int]:
    u = getattr(resp, "usage", None)
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


def _handle_submit(args: dict, ctx: RunContext, question: str) -> tuple[_Final | None, str | None]:
    """Validate a submit_answer call. Returns (final, None) or (None, error message for the model)."""
    status = args.get("status")
    answer = args.get("answer")
    if status not in ("answered", "cannot_determine"):
        return None, "status must be 'answered' or 'cannot_determine'."
    if not isinstance(answer, str) or not answer.strip():
        return None, "answer must be a non-empty string."

    if status == "cannot_determine":
        text = answer.strip()
        if not text.lower().startswith(CANNOT_DETERMINE.lower()):
            text = f"{CANNOT_DETERMINE} {text}"
        return _Final("cannot_determine", text), None

    qids = args.get("query_ids") or []
    cids = args.get("calc_ids") or []
    dids = args.get("doc_ids") or []
    if not all(isinstance(x, list) for x in (qids, cids, dids)):
        return None, "query_ids, calc_ids and doc_ids must be arrays of strings."
    if not qids and not dids:
        return None, ("An 'answered' response must cite at least one query_id from run_sql or "
                      "doc_id from search_documents. Run a query or search, or use status "
                      "'cannot_determine'.")
    unknown = ([q for q in qids if q not in ctx.queries] + [c for c in cids if c not in ctx.calcs]
               + [d for d in dids if d not in ctx.passages])
    if unknown:
        return None, (f"Unknown ids: {unknown}. Valid query_ids: {list(ctx.queries)}; "
                      f"valid calc_ids: {list(ctx.calcs)}; valid doc_ids: {list(ctx.passages)}.")

    ungrounded = find_ungrounded(
        answer, question, [ctx.queries[q] for q in qids], [ctx.calcs[c] for c in cids],
        [ctx.passages[d] for d in dids],
    )
    _audit("grounding_check", {"ungrounded": ungrounded, "correction_used": ctx.corrections},
                ctx.session_id)
    if ungrounded and ctx.corrections < 1:
        ctx.corrections += 1
        return None, (
            f"These numbers in your answer do not appear in the cited tool results: {ungrounded}. "
            "Query them, compute them with calculate, cite the supporting ids, or remove them, "
            "then call submit_answer again."
        )
    return _Final("answered", answer.strip(), list(dict.fromkeys(qids)),
                  list(dict.fromkeys(cids)), list(dict.fromkeys(dids)),
                  grounded=not ungrounded), None


EXCERPT_MAX_CHARS = 1500


def _excerpt(text: str) -> str:
    """The passage the model was shown, trimmed so a response cannot balloon."""
    text = text.strip()
    return text if len(text) <= EXCERPT_MAX_CHARS else text[:EXCERPT_MAX_CHARS].rstrip() + "..."


def _citations(final: _Final, ctx: RunContext) -> list[Citation]:
    cites = [Citation(kind="sql", reference=ctx.queries[q].sql, label=q) for q in final.query_ids]
    for d in final.doc_ids:
        rec = ctx.passages[d]
        cites.append(Citation(kind="document", label=d, reference=f"{rec.title} p.{rec.page}",
                              excerpt=_excerpt(rec.content)))
    for c in final.calc_ids:
        rec = ctx.calcs[c]
        cites.append(Citation(kind="calculation", label=c,
                              reference=f"{c}: {rec.expression} = {format_decimal(rec.result)}"))
    return cites


def run_agent(
    question: str, session_id: str | None = None, client: anthropic.Anthropic | None = None
) -> AskResponse:
    sid = session_id or str(uuid.uuid4())
    client = client or build_client()
    ctx = RunContext(session_id=sid)
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    steps = 0

    def fail(message: str, reason: str) -> AskResponse:
        _audit("answer_final", {"status": "failed", "reason": reason, "steps": steps}, sid)
        return AskResponse(answer=message, status="failed", grounded=False, session_id=sid,
                           steps=steps, usage=usage)

    _audit("ask_received", {"question": question}, sid)
    system = [{"type": "text", "text": build_system_prompt(settings.as_of_date),
               "cache_control": {"type": "ephemeral"}}]
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    nudged = False

    try:
        for _ in range(settings.max_iterations):
            steps += 1
            resp = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.max_tokens,
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            step_usage = _usage(resp)
            for k, v in step_usage.items():
                usage[k] += v
            _audit("model_call", {"step": steps, "stop_reason": resp.stop_reason,
                                       "usage": step_usage}, sid)

            if resp.stop_reason == "refusal":
                return fail("The model declined to answer this request.", "refusal")
            if resp.stop_reason == "max_tokens":
                return fail("The response was cut off before finishing. Try a narrower question.",
                            "max_tokens")

            # Thinking/tool blocks must go back unchanged.
            messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if b.type == "tool_use"]

            if not tool_uses:
                if nudged:
                    return fail("I couldn't produce a structured answer. Please try rephrasing.",
                                "no_submit")
                nudged = True
                messages.append({"role": "user", "content": SUBMIT_NUDGE})
                continue

            results: list[dict[str, Any]] = []
            final: _Final | None = None
            others_present = any(u.name != "submit_answer" for u in tool_uses)

            for u in tool_uses:
                args = u.input if isinstance(u.input, dict) else {}
                if u.name == "run_sql":
                    out = run_sql(ctx, args)
                    payload, is_error, detail = out.payload, out.is_error, out.audit
                elif u.name == "calculate":
                    out = run_calculate(ctx, args)
                    payload, is_error, detail = out.payload, out.is_error, out.audit
                elif u.name == "search_documents":
                    out = run_search_documents(ctx, args)
                    payload, is_error, detail = out.payload, out.is_error, out.audit
                elif u.name == "submit_answer":
                    if others_present:
                        payload, is_error = {"error": "Call submit_answer on its own, after you "
                                                      "have seen the results of your other tools."}, True
                        detail = {"error": "submitted alongside other tools"}
                    else:
                        final, err = _handle_submit(args, ctx, question)
                        is_error = err is not None
                        payload = {"error": err} if err else {"status": "accepted"}
                        detail = {"error": err} if err else {"status": final.status}  # type: ignore[union-attr]
                else:
                    payload, is_error, detail = {"error": f"Unknown tool '{u.name}'."}, True, {}

                _audit("tool_call", {"tool": u.name, "tool_use_id": u.id, "input": args,
                                          "is_error": is_error, **detail}, sid)
                results.append({"type": "tool_result", "tool_use_id": u.id,
                                "content": json.dumps(payload, default=str), "is_error": is_error})

            if final is not None:
                cites = _citations(final, ctx)
                _audit("answer_final", {
                    "status": final.status, "grounded": final.grounded, "steps": steps,
                    "citations": [c.label for c in cites], "usage": usage}, sid)
                return AskResponse(answer=final.answer, citations=cites, session_id=sid,
                                   status=final.status, grounded=final.grounded, steps=steps,
                                   usage=usage)

            messages.append({"role": "user", "content": results})
            if ctx.sql_errors >= settings.max_sql_errors:
                return fail("I couldn't get a working query after several attempts.",
                            "too_many_sql_errors")

        return fail(f"I couldn't complete this within {settings.max_iterations} steps.",
                    "max_iterations")
    except Exception as e:
        # Never mask the original failure with an audit failure.
        with contextlib.suppress(Exception):
            _audit("agent_error", {"type": type(e).__name__, "error": str(e)[:500]}, sid)
        raise
