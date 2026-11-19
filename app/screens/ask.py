import httpx
import streamlit as st
from answer_view import render_turn
from ui_common import API_URL, error_detail, session_id

st.title("Ask")
st.caption("Ask questions about a synthetic CRE portfolio. Answers cite their sources.")


session_id()
if "history" not in st.session_state:
    st.session_state.history = []

for i, turn in enumerate(st.session_state.history):
    with st.chat_message(turn["role"]):
        if turn["role"] == "user":
            st.markdown(turn["content"])
        else:
            render_turn(turn, i)

question = st.chat_input("e.g. Which assets have >20% lease rollover in the next 18 months?")
question = question or st.session_state.pop("pending_question", None)  # sample question from Home
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Working on it. Questions usually take 10 to 30 seconds."):
            try:
                r = httpx.post(
                    f"{API_URL}/ask",
                    json={"question": question, "session_id": st.session_state.session_id},
                    timeout=180,
                )
                r.raise_for_status()
                data = r.json()
                turn = {
                    "role": "assistant",
                    "question": question,
                    "content": data["answer"],
                    "status": data.get("status", "answered"),
                    "grounded": data.get("grounded", True),
                    "citations": data.get("citations", []),
                    "steps": data.get("steps", 0),
                    "session_id": data.get("session_id") or st.session_state.session_id,
                }
            except httpx.HTTPError as e:
                turn = {"role": "assistant", "content": error_detail(e), "status": "error",
                        "question": question}
        render_turn(turn, len(st.session_state.history))
    st.session_state.history.append(turn)
