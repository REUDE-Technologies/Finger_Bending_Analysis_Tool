"""
Styles module — CSS, page init, and HTML header.
"""
import streamlit as st

_CSS = """
<style>
/* ── Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}

/* ── Subtle page background ── */
[data-testid="stAppViewContainer"] > .main {
    background: linear-gradient(168deg, #F8FAFD 0%, #EEF2F7 50%, #F0F4FA 100%);
}

/* ── Hero header ── */
.hero {
    background: linear-gradient(135deg, #0B1D2E 0%, #0F3460 35%, #1B6CA8 70%, #2D8CD4 100%);
    background-size: 300% 300%;
    animation: aurora 12s ease-in-out infinite;
    border-radius: 24px;
    padding: 2.25rem 2.75rem;
    margin-bottom: 1.75rem;
    color: white;
    position: relative;
    overflow: hidden;
    box-shadow: 0 12px 40px rgba(11, 29, 46, 0.35), 0 2px 8px rgba(0,0,0,0.1);
}
@keyframes aurora {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
}
.hero::after {
    content:'';
    position:absolute; top:-60%; right:-15%;
    width:400px; height:400px;
    background: radial-gradient(circle, rgba(255,255,255,0.06) 0%, transparent 70%);
    border-radius:50%;
    pointer-events:none;
}
.hero::before {
    content:'';
    position:absolute; bottom:-40%; left:10%;
    width:300px; height:300px;
    background: radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%);
    border-radius:50%;
    pointer-events:none;
}
.hero h1 {
    margin:0; font-size:1.85rem; font-weight:900;
    letter-spacing:-0.03em; color:white;
    text-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.hero p {
    margin:0.4rem 0 0; font-size:0.88rem;
    color:rgba(203,213,225,0.9); font-weight:400;
}

/* ── Stepper ── */
.stepper {
    display:flex; align-items:center; justify-content:center;
    gap:0; padding:1.25rem 2rem;
    background:white; border-radius:18px;
    border:1px solid #E2E8F0;
    box-shadow:0 2px 8px rgba(0,0,0,0.03);
    margin-bottom:1.5rem;
}
.s-item { display:flex; align-items:center; gap:10px; }
.s-dot {
    width:38px; height:38px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-weight:800; font-size:0.85rem; flex-shrink:0;
    transition: all 0.4s cubic-bezier(.4,0,.2,1);
}
.s-dot.done {
    background:linear-gradient(135deg,#059669,#34D399);
    color:white;
    box-shadow:0 4px 14px rgba(5,150,105,0.3);
}
.s-dot.on {
    background:linear-gradient(135deg,#1B6CA8,#3B82F6);
    color:white;
    box-shadow:0 4px 14px rgba(27,108,168,0.35);
    animation: pulse-ring 2s ease-out infinite;
}
@keyframes pulse-ring {
    0% { box-shadow:0 4px 14px rgba(27,108,168,0.35); }
    50% { box-shadow:0 4px 20px rgba(59,130,246,0.55); }
    100% { box-shadow:0 4px 14px rgba(27,108,168,0.35); }
}
.s-dot.off {
    background:#F1F5F9; color:#94A3B8;
    border:2px solid #E2E8F0;
}
.s-lbl { font-size:0.78rem; font-weight:600; white-space:nowrap; }
.s-lbl.done { color:#059669; } .s-lbl.on { color:#1B6CA8; } .s-lbl.off { color:#94A3B8; }
.s-line {
    width:56px; height:3px; margin:0 8px;
    border-radius:2px; flex-shrink:0;
}
.s-line.done { background:linear-gradient(90deg,#34D399,#059669); }
.s-line.on { background:linear-gradient(90deg,#93C5FD,#3B82F6); }
.s-line.off { background:#E2E8F0; }

/* ── Section label ── */
.sec-label {
    display:inline-flex; align-items:center; gap:10px;
    margin-bottom:0.75rem;
}
.sec-icon {
    width:36px; height:36px; border-radius:12px;
    display:flex; align-items:center; justify-content:center;
    font-size:1.1rem; flex-shrink:0;
}
.sec-icon.blue  { background:linear-gradient(135deg,#DBEAFE,#BFDBFE); }
.sec-icon.green { background:linear-gradient(135deg,#D1FAE5,#A7F3D0); }
.sec-icon.amber { background:linear-gradient(135deg,#FEF3C7,#FDE68A); }
.sec-icon.violet { background:linear-gradient(135deg,#EDE9FE,#C4B5FD); }
.sec-title { font-size:1.05rem; font-weight:700; color:#0F172A; margin:0; }
.sec-sub   { font-size:0.78rem; font-weight:400; color:#64748B; margin:0; }

/* ── Upload hero zone ── */
.upload-hero {
    border:2.5px dashed #C7D2E0;
    border-radius:22px;
    padding:2.75rem 2rem;
    text-align:center;
    background: linear-gradient(180deg, rgba(255,255,255,0.9) 0%, rgba(241,245,249,0.8) 100%);
    backdrop-filter:blur(6px);
    transition: all 0.4s cubic-bezier(.4,0,.2,1);
    cursor:pointer;
    position:relative;
}
.upload-hero:hover {
    border-color:#3B82F6;
    background:linear-gradient(180deg,#EFF6FF 0%,#DBEAFE 100%);
    transform:translateY(-3px);
    box-shadow:0 12px 36px rgba(59,130,246,0.12);
}
.u-icon { font-size:3.5rem; margin-bottom:0.5rem; animation:bob 3s ease-in-out infinite; }
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
.u-title { font-size:1.15rem; font-weight:700; color:#1E293B; margin:0 0 0.3rem; }
.u-desc  { font-size:0.82rem; color:#64748B; margin:0 0 0.75rem; max-width:460px; display:inline-block; }
.fmt-pill {
    display:inline-block;
    background:#EFF6FF; color:#1E40AF;
    padding:4px 14px; border-radius:8px;
    font-size:0.72rem; font-weight:700;
    letter-spacing:0.04em; margin:0 4px;
}

/* ── Scan banner ── */
.scan-ok {
    background:linear-gradient(135deg,#F0FDF4 0%,#DCFCE7 100%);
    border:1px solid #86EFAC; border-radius:18px;
    padding:1.5rem 1.75rem; margin:1rem 0;
    animation: slideUp 0.45s ease-out;
}
@keyframes slideUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.scan-ok h4 { margin:0 0 1rem; font-size:1rem; font-weight:700; color:#166534; display:flex; align-items:center; gap:8px; }
.scan-kpis { display:flex; gap:16px; flex-wrap:wrap; }
.kpi {
    text-align:center; padding:14px 22px;
    background:rgba(255,255,255,0.75);
    border-radius:14px; min-width:95px;
    backdrop-filter:blur(4px);
}
.kpi .num {
    font-size:2rem; font-weight:900; line-height:1;
    background:linear-gradient(135deg,#059669,#166534);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    background-clip:text;
}
.kpi .tag {
    font-size:0.68rem; font-weight:600;
    color:#4B5563; text-transform:uppercase;
    letter-spacing:0.06em; margin-top:3px;
}

/* ── Structure table ── */
.s-table {
    width:100%; border-collapse:separate; border-spacing:0;
    border-radius:14px; overflow:hidden;
    border:1px solid #E2E8F0; font-size:0.84rem;
    box-shadow:0 1px 4px rgba(0,0,0,0.03);
}
.s-table th {
    background:linear-gradient(180deg,#F8FAFC,#F1F5F9);
    padding:11px 16px; text-align:left;
    font-weight:700; color:#475569;
    border-bottom:2px solid #E2E8F0;
    font-size:0.73rem; text-transform:uppercase;
    letter-spacing:0.05em;
}
.s-table td {
    padding:11px 16px; border-bottom:1px solid #F1F5F9;
    color:#334155; vertical-align:middle;
}
.s-table tr:last-child td { border-bottom:none; }
.s-table tr:hover td { background:#FAFBFC; }
.kpa-tag {
    display:inline-flex; align-items:center; gap:5px;
    background:linear-gradient(135deg,#EFF6FF,#DBEAFE);
    border:1px solid #BFDBFE; border-radius:10px;
    padding:5px 14px; font-weight:700; color:#1E40AF;
    font-size:0.84rem;
}
.pt-tag {
    display:inline-block;
    background:#F0FDF4; border:1px solid #BBF7D0;
    border-radius:6px; padding:3px 8px;
    font-size:0.73rem; font-weight:600;
    color:#166534; margin:2px;
}

/* ── Gradient metric tiles ── */
.m-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:1rem 0; }
@media (max-width:768px) { .m-grid { grid-template-columns:repeat(2,1fr); } }
.m-tile {
    border-radius:18px; padding:1.35rem 1.25rem;
    text-align:center; color:white;
    position:relative; overflow:hidden;
    box-shadow:0 6px 20px rgba(0,0,0,0.12);
    transition: transform 0.25s ease, box-shadow 0.25s ease;
}
.m-tile:hover {
    transform:translateY(-3px);
    box-shadow:0 10px 30px rgba(0,0,0,0.18);
}
.m-tile::after {
    content:''; position:absolute; top:-35%; right:-18%;
    width:110px; height:110px;
    background:rgba(255,255,255,0.08);
    border-radius:50%; pointer-events:none;
}
.m-tile .v  { font-size:2rem; font-weight:900; line-height:1.1; position:relative; }
.m-tile .l  {
    font-size:0.68rem; font-weight:500; opacity:0.85;
    margin-top:5px; text-transform:uppercase;
    letter-spacing:0.06em; position:relative;
}
.t-blue    { background:linear-gradient(135deg,#1B6CA8,#3B82F6); }
.t-indigo  { background:linear-gradient(135deg,#4338CA,#6366F1); }
.t-emerald { background:linear-gradient(135deg,#059669,#34D399); }
.t-amber   { background:linear-gradient(135deg,#D97706,#F59E0B); }

/* ── Process area ── */
.proc-zone {
    background:linear-gradient(135deg,rgba(27,108,168,0.04),rgba(59,130,246,0.07));
    border:1.5px solid rgba(59,130,246,0.18);
    border-radius:18px; padding:1.75rem 2rem;
    text-align:center;
}

/* ── Badges ── */
.b-ok   { display:inline-block; background:#ECFDF5; color:#065F46; padding:5px 14px; border-radius:20px; font-size:0.8rem; font-weight:600; }
.b-warn { display:inline-block; background:#FFFBEB; color:#92400E; padding:5px 14px; border-radius:20px; font-size:0.8rem; font-weight:600; }
.b-info { display:inline-block; background:#EFF6FF; color:#1E40AF; padding:5px 14px; border-radius:20px; font-size:0.8rem; font-weight:600; }
.b-neut { display:inline-block; background:#F1F5F9; color:#475569; padding:5px 14px; border-radius:20px; font-size:0.8rem; font-weight:600; }

/* ── Divider ── */
.divider { height:1px; background:linear-gradient(90deg,transparent,#E2E8F0,transparent); margin:1.5rem 0; }

/* ── Footer ── */
.footer {
    text-align:center; padding:1.5rem;
    color:#94A3B8; font-size:0.75rem;
}

/* ── Streamlit overrides for premium feel ── */
[data-testid="stFileUploader"] > div:first-child {
    border-radius: 14px !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
    border-radius: 14px !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    padding: 0.75rem 2rem !important;
    letter-spacing: 0.01em !important;
    box-shadow: 0 4px 16px rgba(27,108,168,0.3) !important;
    transition: all 0.3s ease !important;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
    box-shadow: 0 8px 28px rgba(27,108,168,0.45) !important;
    transform: translateY(-2px) !important;
}
.stButton > button:not([kind="primary"]) {
    border-radius: 12px !important;
    font-weight: 600 !important;
}
[data-testid="stSelectbox"], [data-testid="stNumberInput"], [data-testid="stTextInput"] {
    font-family: 'Inter', sans-serif !important;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: #F1F5F9;
    padding: 4px;
    border-radius: 14px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 8px 20px !important;
}
.streamlit-expanderHeader { font-weight: 600 !important; font-size: 0.9rem !important; }
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
    border-radius: 8px !important;
    font-weight: 600 !important;
}
[data-testid="stPills"] button {
    border-radius: 10px !important;
    font-weight: 600 !important;
}
</style>
"""

_HEADER = """
<div class="hero">
    <h1>🤖 Finger Bending Analysis Tool</h1>
    <p>Upload · Auto-detect · Analyse · Export — streamlined for soft robotics research</p>
</div>
"""


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════
def init_page() -> None:
    """Set page config, inject CSS, and render hero header."""
    st.set_page_config(
        page_title="Finger Bending Analysis",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_HEADER, unsafe_allow_html=True)


# ── Stepper ──
_STEPS = [("1", "Configure"), ("2", "Upload"), ("3", "Select"), ("4", "Process")]


def stepper(active: int) -> None:
    """Render progress stepper bar. `active` is 1-4."""
    parts = []
    for i, (num, label) in enumerate(_STEPS):
        idx = i + 1
        if idx < active:
            c, ic = "done", "✓"
        elif idx == active:
            c, ic = "on", num
        else:
            c, ic = "off", num
        parts.append(
            f'<div class="s-item">'
            f'<div class="s-dot {c}">{ic}</div>'
            f'<span class="s-lbl {c}">{label}</span></div>'
        )
        if i < len(_STEPS) - 1:
            lc = "done" if idx < active else ("on" if idx == active else "off")
            parts.append(f'<div class="s-line {lc}"></div>')
    st.markdown(f'<div class="stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


# ── Section label ──
def section(icon: str, color: str, title: str, sub: str) -> None:
    """Render a styled section header with icon, title and subtitle."""
    st.markdown(
        f'<div class="sec-label">'
        f'<div class="sec-icon {color}">{icon}</div>'
        f'<div><p class="sec-title">{title}</p><p class="sec-sub">{sub}</p></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def divider() -> None:
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


def footer() -> None:
    st.markdown(
        '<div class="footer">Finger Bending Analysis Tool · Built for soft robotics research</div>',
        unsafe_allow_html=True,
    )
