"""Presentation of one assistant turn on the Ask page: result first, state, source cards, feedback.

Pure helpers (`turn_state`, `tables_in`, `source_card`) are separate from the Streamlit calls so
they can be tested without a browser. Nothing here changes an answer; the View only changes how
much is shown.
"""

import re

import streamlit as st
from ui_common import current_view, quick_feedback

# state key -> (icon, short label). Always shown as text plus icon, never colour alone.
STATES = {
    "answered": ("✅", "Answered. Every number traced to a cited source."),
    "ungrounded": ("⚠️", "Not fully verified. Some numbers could not be traced to a source."),
    "cannot_determine": ("ℹ️", "Cannot be determined from the data."),
    "failed": ("❌", "The assistant could not finish this question."),
    "error": ("🔌", "The service did not respond."),
}

_TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def turn_state(turn: dict) -> str:
    status = turn.get("status", "answered")
    if status in ("error", "failed", "cannot_determine"):
        return status
    return "answered" if turn.get("grounded", True) else "ungrounded"


def tables_in(sql: str) -> list[str]:
    """Table names a query reads, in order of first appearance (for the plain-language summary)."""
    seen: list[str] = []
    for name in _TABLE_RE.findall(sql):
        if name.lower() not in seen:
            seen.append(name.lower())
    return seen


def source_card(c: dict) -> dict:
    """{title, detail, code, language} for one citation, in words an asset manager can read."""
    label = c.get("label") or ""
    kind = c["kind"]
    if kind == "sql":
        tables = tables_in(c["reference"])
        detail = ("Read from: " + ", ".join(tables)) if tables else "Database query"
        return {"title": f"Database query {label}".strip(), "detail": detail,
                "code": c["reference"], "language": "sql"}
    if kind == "document":
        return {"title": c["reference"], "detail": f"Document passage {label}".strip(),
                "code": None, "language": None, "excerpt": c.get("excerpt")}
    return {"title": f"Calculation {label}".strip(), "detail": "Computed by the calculator tool",
            "code": c["reference"], "language": "text"}


MARKDOWN_CHARS = set("\\`*_{}[]<>#|~$")


def quote(text: str) -> str:
    """Block-quote a passage. Markdown characters in the document text are escaped so a lease
    clause cannot change how the page renders."""
    escaped = "".join("\\" + ch if ch in MARKDOWN_CHARS else ch for ch in text)
    return "\n".join("> " + line if line.strip() else ">" for line in escaped.splitlines())


def render_sources(citations: list[dict]) -> None:
    view = current_view()
    with st.expander(f"Sources ({len(citations)})", expanded=view != "Asset manager"):
        for c in citations:
            card = source_card(c)
            with st.container(border=True):
                st.markdown(f"**{card['title']}**")
                st.caption(card["detail"])
                if card["code"]:
                    st.code(card["code"], language=card["language"], wrap_lines=True)
                if card.get("excerpt"):
                    st.markdown(quote(card["excerpt"]))
                    st.caption("Text of the passage that was cited for this answer.")
                elif card["language"] is None:
                    st.caption("The passage text was not returned for this source.")


def render_turn(turn: dict, key: int) -> None:
    state = turn_state(turn)
    icon, label = STATES[state]
    content = turn["content"]

    # Result first. Problems that change how much to trust it come before the text.
    if state == "error":
        st.error(f"{icon} {label} {content}")
        if turn.get("question") and st.button("Try again", key=f"retry_{key}"):
            st.session_state.pending_question = turn["question"]
            st.rerun()
        return
    if state == "failed":
        st.error(f"{icon} {label}\n\n{content}")
        return
    if state == "cannot_determine":
        st.info(f"{icon} {label}\n\n{content}")
    else:
        if state == "ungrounded":
            st.warning(f"{icon} {label} Check the sources before relying on it.")
        st.markdown(content)
        if state == "answered":
            st.caption(f"{icon} {label}")

    citations = turn.get("citations", [])
    if citations:
        render_sources(citations)

    view = current_view()
    sid = (turn.get("session_id") or "")[:8]
    if view == "Analyst" and turn.get("steps"):
        n = turn["steps"]
        st.caption(f"{n} model {'call' if n == 1 else 'calls'} · session {sid}")
    if view == "Reviewer":
        st.caption("Checks applied: read-only database role, approved tables only, numbers traced "
                   f"to cited results, every step logged to the audit table (session {sid}).")

    quick_feedback(f"chat_{key}", turn.get("question", ""), content)
