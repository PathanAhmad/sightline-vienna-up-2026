"""Page chrome — Streamlit overrides, body/typography, hidden defaults.

Everything here is global. Component-specific styling lives in each
component's own file.
"""
from __future__ import annotations


BASE_CSS = """
<style>
/* ---- App / body --------------------------------------------------- */
html, body, [class*="css"] {
    font-family: var(--font-stack);
    color: var(--c-text);
    font-size: 16px;
    font-feature-settings: "ss01", "cv11", "tnum";
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
}
.stApp {
    background: var(--c-bg);
    overflow-x: hidden;
    overflow-y: hidden;
}

/* ---- Hide Streamlit default chrome -------------------------------- */
header[data-testid="stHeader"] {
    background: transparent;
    height: 0;
}
header[data-testid="stHeader"] [data-testid="stToolbar"] { display: none; }
[data-testid="stStatusWidget"] { display: none; }
[data-testid="stDecoration"] { display: none; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
[data-testid="stSidebarCollapsedControl"] { opacity: 0.5; }
[data-testid="stSidebarCollapsedControl"]:hover { opacity: 1; }

/* ---- Sidebar (live-score lives here) ------------------------------ */
section[data-testid="stSidebar"] {
    background: var(--c-surface);
    border-right: 1px solid var(--c-border);
}
section[data-testid="stSidebar"] .block-container {
    padding-top: var(--s-4);
}

/* ---- Default headings --------------------------------------------- */
h1, h2, h3, h4 {
    color: var(--c-text);
    letter-spacing: -0.01em;
    font-weight: 600;
}

/* ---- Default buttons (secondary look). Primary lives on
        st.download_button via the download component. ---------------- */
.stButton > button {
    border-radius: var(--r-sm);
    border: 1px solid var(--c-border);
    background: var(--c-surface);
    color: var(--c-text);
    font-weight: 500;
    font-size: 13px;
    padding: var(--s-2) var(--s-3);
    min-height: 44px;
    transition: border-color 120ms ease, color 120ms ease;
    box-shadow: none;
}
.stButton > button:hover {
    border-color: var(--c-accent);
    color: var(--c-accent);
}
.stButton > button:disabled {
    color: var(--c-muted);
    background: var(--c-bg);
    cursor: not-allowed;
}
.stButton > button:focus {
    box-shadow: 0 0 0 3px var(--c-accent-soft);
    border-color: var(--c-accent);
}

/* ---- Section heading (small caps label above a list) -------------- */
.section-head {
    font-size: 11px;
    font-weight: 700;
    color: var(--c-muted);
    letter-spacing: 0.10em;
    text-transform: uppercase;
    margin: var(--s-3) 0 var(--s-2) 0;
}
.section-head:first-child { margin-top: 0; }
.section-head-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s-2);
}
.section-head-row .hint {
    font-size: 11px;
    color: var(--c-muted);
    font-weight: 400;
    letter-spacing: normal;
    text-transform: none;
}

/* ---- Verdict pills (used in segment panel, worst list) ------------ */
.verdict-pill {
    display: inline-block;
    padding: 3px 10px;
    border-radius: var(--r-pill);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: white;
    vertical-align: middle;
    line-height: 1.4;
}
.verdict-pill.green  { background: var(--c-green); }
.verdict-pill.yellow { background: var(--c-yellow); }
.verdict-pill.red    { background: var(--c-red); }
.verdict-pill.muted  { background: var(--c-muted); }
.verdict-pill.large  { font-size: 12px; padding: 5px 14px; }
</style>
"""
