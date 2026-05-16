"""In-app chat assistant — opener button + full-height dialog.

Two public entry points:

  * `render_fab()`        -- floating bottom-right pill (upload view).
  * `render_inline()`     -- normal-sized button suitable for placement
                             in a Streamlit column (dashboard rail,
                             where it sits next to the download CTA).

Both open the same `@st.dialog`-decorated chat modal -- a near-full-
viewport panel that holds a scrollable transcript and a Send form.

The dialog body uses `st.chat_message` for bubbles and a plain
`st.text_area` + Send button for input -- `st.chat_input` is restricted
to the top-level page body in Streamlit and won't render inside a
dialog as of 1.57.

Session-state keys:
  chat_messages     -- the transcript in Anthropic format
  chat_spend_usd    -- running session spend, capped by chat_agent

CSS for this component is bundled into `src.ui.inject_all_css()`. We
deliberately do NOT inject from inside render_fab/render_inline -- on
a Streamlit rerun, conditionally-injected style blocks get dropped
from the DOM, which silently breaks the dialog chrome.
"""
from __future__ import annotations

import streamlit as st

from src.ui.components.chat_agent import (
    MAX_SESSION_SPEND_USD,
    respond,
    scrub_user_text,
)


CSS = """
<style>
/* ---- Floating Ask button (upload view only) ---------------------------
   The button is a real Streamlit button so it can trigger reruns. We
   give it `key="chat_fab"`, which Streamlit lands on the wrapping
   stVerticalBlock as `.st-key-chat_fab`. We pin THAT wrapper to the
   viewport corner and style the inner <button> as a pill. */
.st-key-chat_fab {
    position: fixed !important;
    bottom: 22px !important;
    right: 22px !important;
    z-index: 9999 !important;
    width: auto !important;
    margin: 0 !important;
}
.st-key-chat_fab button {
    background: var(--c-accent) !important;
    color: white !important;
    border: none !important;
    border-radius: var(--r-pill) !important;
    padding: 12px 22px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
    box-shadow:
        0 0 0 1px rgba(3,105,161,0.18),
        0 6px 18px -4px rgba(15,23,42,0.25) !important;
    transition: transform 120ms ease, box-shadow 120ms ease,
                background 120ms ease !important;
}
.st-key-chat_fab button:hover {
    background: #075985 !important;
    transform: translateY(-1px) !important;
    box-shadow:
        0 0 0 1px rgba(3,105,161,0.28),
        0 10px 22px -4px rgba(15,23,42,0.30) !important;
}
.st-key-chat_fab button:focus { outline: none !important; }

/* ---- Inline Ask button (dashboard rail) -------------------------------
   Sits in a column next to the download CTA, mirroring its look so the
   pair reads as one row. Radius (10px / --r-md) matches the catches
   cards directly above; height is kept short (44px) so the pair reads
   as a slim action strip, not a heavy blue bar competing for weight
   with the catches grid. */
.st-key-chat_inline button {
    background: var(--c-accent) !important;
    color: white !important;
    border: 1px solid var(--c-accent) !important;
    border-radius: var(--r-md) !important;
    padding: var(--s-2) var(--s-4) !important;
    min-height: 44px !important;
    height: 44px !important;
    font-weight: 600 !important;
    font-size: 13.5px !important;
    width: 100% !important;
    box-shadow: var(--shadow-card) !important;
}
.st-key-chat_inline button:hover {
    background: #075985 !important;
    border-color: #075985 !important;
}

/* ---- Dialog chrome ----------------------------------------------------
   Streamlit's dialog renders inside a portal with [role="dialog"]. Make
   it nearly viewport-tall so the transcript has room to breathe, and
   let the content scroll inside instead of pushing the page. */
div[role="dialog"] {
    border-radius: var(--r-md) !important;
    box-shadow: var(--shadow-hover) !important;
    height: 92vh !important;
    max-height: 92vh !important;
    display: flex !important;
    flex-direction: column !important;
}
/* The dialog body wrapper -- this is the scroll container. Streamlit
   ships it as the second child after the title bar. */
div[role="dialog"] > div:nth-of-type(2) {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow-y: auto !important;
}
div[role="dialog"] [data-testid="stMarkdownContainer"] p {
    line-height: 1.55 !important;
}

/* Eyebrow + subhead inside the dialog header area we render manually. */
.chat-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s-3);
    margin: -4px 0 var(--s-3) 0;
    padding-bottom: var(--s-3);
    border-bottom: 1px solid var(--c-border-soft);
}
.chat-header .eyebrow {
    font-size: 10.5px;
    font-weight: 700;
    color: var(--c-accent);
    letter-spacing: 0.14em;
    text-transform: uppercase;
}
.chat-header .sub {
    font-size: 12px;
    color: var(--c-muted);
    font-variant-numeric: tabular-nums;
}

/* Empty-state hint when there are no messages yet. */
.chat-empty {
    background: var(--c-accent-soft);
    border: 1px solid #bae6fd;
    color: #075985;
    border-radius: var(--r-sm);
    padding: 12px 14px;
    font-size: 12.5px;
    line-height: 1.55;
    margin-bottom: var(--s-3);
}
.chat-empty b { color: #0c4a6e; }

/* Cap-reached banner. */
.chat-cap {
    background: var(--c-yellow-soft);
    border: 1px solid #fcd34d;
    color: #78350f;
    border-radius: var(--r-sm);
    padding: 10px 14px;
    font-size: 12.5px;
    line-height: 1.5;
    margin-top: var(--s-3);
}

/* Tighten chat-message bubble padding so the modal feels less airy. */
[data-testid="stChatMessage"] {
    padding: 10px 12px !important;
    margin-bottom: 8px !important;
}
</style>
"""


@st.dialog("Ask the QC bot", width="large")
def _chat_dialog() -> None:
    """Modal body: header, transcript, input. One round-trip per Send."""
    messages: list[dict] = st.session_state.setdefault("chat_messages", [])
    spend: float = st.session_state.setdefault("chat_spend_usd", 0.0)

    st.markdown(
        f"<div class='chat-header'>"
        f"<div class='eyebrow'>QC assistant · Haiku 4.5</div>"
        f"<div class='sub'>session spend "
        f"<b>${spend:.4f}</b> / ${MAX_SESSION_SPEND_USD:.2f}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not messages:
        st.markdown(
            "<div class='chat-empty'>"
            "<b>Ask anything about this trench-inspection project.</b><br>"
            "Try: <i>&ldquo;How are we doing overall?&rdquo;</i> · "
            "<i>&ldquo;Which trench sections still need attention?&rdquo;</i> · "
            "<i>&ldquo;What does the map show me?&rdquo;</i>"
            "</div>",
            unsafe_allow_html=True,
        )

    # ---- Transcript -----------------------------------------------------
    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # ---- Input ----------------------------------------------------------
    # NOT in an st.form, deliberately. Form submission in Streamlit 1.57
    # triggers an APP-scope rerun, which tears down the dialog. Plain
    # buttons inside @st.dialog reruns are fragment-scoped, so the
    # dialog stays open across Send. We use a turn counter in the key
    # so the textarea resets cleanly after each send.
    cap_reached = spend >= MAX_SESSION_SPEND_USD
    turn_n = st.session_state.setdefault("chat_turn_n", 0)

    user_text = st.text_area(
        "Your question",
        key=f"chat_input_{turn_n}",
        placeholder=(
            "Session budget exhausted — reload the page to reset."
            if cap_reached
            else "Ask about your batch or the segments…"
        ),
        height=80,
        label_visibility="collapsed",
        disabled=cap_reached,
    )
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        send = st.button(
            "Send",
            key=f"chat_send_{turn_n}",
            use_container_width=True,
            type="primary",
            disabled=cap_reached,
        )
    with c2:
        clear = st.button(
            "Clear chat",
            key=f"chat_clear_{turn_n}",
            use_container_width=True,
        )

    if cap_reached:
        st.markdown(
            f"<div class='chat-cap'>Session spend hit the "
            f"${MAX_SESSION_SPEND_USD:.2f} cap. Reload the page to reset.</div>",
            unsafe_allow_html=True,
        )

    if clear:
        st.session_state["chat_messages"] = []
        st.session_state["chat_turn_n"] = turn_n + 1
        st.rerun(scope="fragment")

    if send and user_text and user_text.strip() and not cap_reached:
        clean = scrub_user_text(user_text)
        messages.append({"role": "user", "content": clean})
        with st.spinner("Thinking…"):
            reply, turn_cost = respond(messages)
        messages.append({"role": "assistant", "content": reply})
        st.session_state["chat_spend_usd"] = spend + turn_cost
        st.session_state["chat_turn_n"] = turn_n + 1
        st.rerun(scope="fragment")


def render_fab() -> None:
    """Render the floating Ask button. Click → open the chat dialog.

    Used on the upload view, where there's no rail to put an inline
    button in. CSS is bundled into `inject_all_css()` -- don't re-inject
    here, the Streamlit DOM-replacement on rerun drops conditionally-
    injected style blocks."""
    if st.button("Ask QC bot", key="chat_fab", help="Open the QC assistant"):
        _chat_dialog()


def render_inline() -> None:
    """Render the in-flow Ask button. Click → open the chat dialog.

    Used on the dashboard rail next to the download CTA. Styled to
    match the download button so the pair reads as one row of two
    primary actions."""
    if st.button(
        "Ask QC bot",
        key="chat_inline",
        help="Open the QC assistant",
        use_container_width=True,
    ):
        _chat_dialog()
