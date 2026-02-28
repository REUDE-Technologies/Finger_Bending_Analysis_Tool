"""
Finger Bending Analysis Tool — Streamlit App

Professional data extraction and compilation tool for soft robotic finger
bending measurements. Processes point tracking data at various pressure levels
and computes displacement, bending angles, and statistics.
"""

import logging
from datetime import datetime

# Suppress Streamlit "missing ScriptRunContext" in headless/Railway (expected in bare mode)
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(
    logging.ERROR
)

import pandas as pd
import plotly.express as px
import streamlit as st

from processing import (
    compile_all_pressures,
    extract_point_names_from_columns,
    extract_zip,
    to_excel_bytes,
    build_summary,
)

try:
    from db import (
        get_finger_types,
        add_finger_type,
        get_materials,
        add_material,
        save_config,
        get_recent_configs,
    )
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PRESSURE_MIN = 10
PRESSURE_MAX = 110
PRESSURE_STEP = 10
PRESSURE_OPTIONS = list(range(PRESSURE_MIN, PRESSURE_MAX, PRESSURE_STEP))

SESSION_COMPILED_DF = "compiled_df"
SESSION_SUMMARY_DF = "summary_df"
SESSION_POINT_NAMES = "point_names"
SESSION_CONFIG = "config"
SESSION_LOAD_CONFIG = "_load_config"


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
def init_page() -> None:
    """Configure page and inject global styles."""
    st.set_page_config(
        page_title="Finger Bending Analysis",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_STYLES, unsafe_allow_html=True)
    st.markdown(_HEADER_HTML, unsafe_allow_html=True)


_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, sans-serif !important;
}
.app-header {
    background: linear-gradient(135deg, #0A2E42 0%, #1B6CA8 100%);
    border-radius: 16px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
    color: white;
}
.app-header h1 { margin: 0; font-size: 1.6rem; font-weight: 700; color: white; }
.app-header p { margin: 0.25rem 0 0 0; font-size: 0.9rem; opacity: 0.85; color: #E0E7FF; }
.config-card { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
.metric-card { background: white; border: 1px solid #E2E8F0; border-radius: 12px; padding: 1rem; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.metric-card .value { font-size: 1.5rem; font-weight: 700; color: #1B6CA8; }
.metric-card .label { font-size: 0.8rem; color: #64748B; margin-top: 0.25rem; }
.upload-zone { border: 2px dashed #CBD5E1; border-radius: 12px; padding: 2rem; text-align: center; background: #FAFBFC; transition: all 0.2s; }
.upload-zone:hover { border-color: #1B6CA8; background: #F0F7FF; }
.badge-success { background: #ECFDF5; color: #065F46; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
.badge-warning { background: #FFFBEB; color: #92400E; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
.badge-info { background: #EFF6FF; color: #1E40AF; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
</style>
"""

_HEADER_HTML = """
<div class="app-header">
    <h1>🤖 Finger Bending Analysis Tool</h1>
    <p>Process point tracking data · Compute displacement & angles · Export to Excel</p>
</div>
"""


# ---------------------------------------------------------------------------
# UI: Config form
# ---------------------------------------------------------------------------
def _render_selectbox_with_add(
    label: str,
    options: list,
    default: str,
    key_prefix: str,
    add_label: str = "+ Add new...",
) -> str:
    """Render a selectbox with optional 'Add new' option. Returns selected or new value."""
    options_list = [""] + options + [add_label]
    index = options.index(default) + 1 if default and default in options else 0

    selected = st.selectbox(label, options=options_list, index=index, key=f"{key_prefix}_select")
    if selected == add_label:
        selected = st.text_input(f"New {label.lower()}", key=f"{key_prefix}_new")
    return selected or ""


def _build_display_config(
    finger_type: str,
    finger_length: float,
    body_material: str,
    skin_material: str,
    speed: float,
    designed_by: str,
    design_version: str,
) -> dict:
    """Build config dict for display/export."""
    return {
        "Finger": finger_type,
        "Finger Length (mm)": finger_length,
        "Body Material": body_material,
        "Skin Material": skin_material,
        "Speed (m/s)": speed,
        "Designed By": designed_by,
        "Design Version": design_version,
    }


def _build_db_config(
    finger_type: str,
    finger_length: float,
    body_material: str,
    skin_material: str,
    speed: float,
    designed_by: str,
    design_version: str,
) -> dict:
    """Build config dict for database storage."""
    return {
        "finger_type": finger_type,
        "finger_length": finger_length,
        "body_material": body_material,
        "skin_material": skin_material,
        "speed": speed,
        "designed_by": designed_by,
        "design_version": design_version,
    }


def render_config_form(loaded: dict | None) -> tuple[dict, dict]:
    """Render configuration form. Returns (display_config, db_config)."""
    st.markdown("### 📋 Test Configuration")

    loaded = loaded or {}
    col1, col2, col3 = st.columns(3)

    with col1:
        finger_options = get_finger_types() if DB_AVAILABLE else []
        finger_type = _render_selectbox_with_add(
            "Finger Type", finger_options, loaded.get("finger_type", ""), "finger_type"
        )

    with col2:
        finger_length = st.number_input(
            "Finger Length (mm)",
            min_value=0.0,
            step=1.0,
            value=float(loaded.get("finger_length", 0)),
        )

    with col3:
        speed = st.number_input(
            "Speed (m/s)",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            value=float(loaded.get("speed", 0)),
        )

    col4, col5, col6 = st.columns(3)
    with col4:
        body_options = get_materials("body") if DB_AVAILABLE else []
        body_material = _render_selectbox_with_add(
            "Body Material", body_options, loaded.get("body_material", ""), "body_material"
        )
    with col5:
        skin_options = get_materials("skin") if DB_AVAILABLE else []
        skin_material = _render_selectbox_with_add(
            "Skin Material", skin_options, loaded.get("skin_material", ""), "skin_material"
        )
    with col6:
        designed_by = st.text_input("Designed By", value=loaded.get("designed_by", ""))

    design_version = st.text_input("Design Version", value=loaded.get("design_version", ""))

    display_config = _build_display_config(
        finger_type, finger_length, body_material, skin_material,
        speed, designed_by, design_version,
    )
    db_config = _build_db_config(
        finger_type, finger_length, body_material, skin_material,
        speed, designed_by, design_version,
    )
    return display_config, db_config


# ---------------------------------------------------------------------------
# UI: Sidebar
# ---------------------------------------------------------------------------
def render_sidebar() -> None:
    """Render sidebar with quick-load config selector."""
    with st.sidebar:
        st.markdown("### ⚡ Quick Load")
        if DB_AVAILABLE:
            recent = get_recent_configs(10)
            if recent:
                labels = [
                    f"{r.get('finger_type', '?')} · {r.get('body_material', '?')} · {r.get('created_at', '')[:10]}"
                    for r in recent
                ]
                selected = st.selectbox("Load previous config", ["— New —"] + labels)
                if selected != "— New —":
                    idx = labels.index(selected)
                    st.session_state[SESSION_LOAD_CONFIG] = recent[idx]
            else:
                st.caption("No saved configs yet.")
        else:
            st.caption("Database not connected. Configs won't be saved.")
            st.caption("Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")


# ---------------------------------------------------------------------------
# UI: File upload
# ---------------------------------------------------------------------------
def _process_uploaded_files(uploaded_files: list) -> dict[str, bytes]:
    """Convert uploaded ZIP/TXT files into {filename: content} dict."""
    result = {}
    for f in uploaded_files:
        if f.name.lower().endswith(".zip"):
            result.update(extract_zip(f.read()))
        elif f.name.lower().endswith(".txt"):
            result[f.name] = f.read()
    return result


def render_upload_section() -> dict[int, dict[str, bytes]] | None:
    """Render pressure selection and file upload UI. Returns pressure_files or None."""
    st.markdown("### 📂 Upload Point Data")

    selected_pressures = st.multiselect(
        "Select pressure levels (kPa)",
        options=PRESSURE_OPTIONS,
        default=[],
        help="Select which pressure levels you have data for",
    )

    if not selected_pressures:
        st.info("👆 Select at least one pressure level to upload data.")
        return None

    st.markdown(
        f"<span class='badge-info'>📊 {len(selected_pressures)} pressure level(s) selected</span>",
        unsafe_allow_html=True,
    )

    pressure_files = {}
    upload_cols = st.columns(min(len(selected_pressures), 4))

    for i, kpa in enumerate(sorted(selected_pressures)):
        col_idx = i % len(upload_cols)
        with upload_cols[col_idx]:
            st.markdown(f"**{kpa} kPa**")
            uploaded = st.file_uploader(
                f"Upload ZIP or TXT files for {kpa} kPa",
                type=["zip", "txt"],
                accept_multiple_files=True,
                key=f"upload_{kpa}",
                label_visibility="collapsed",
            )
            if uploaded:
                files_dict = _process_uploaded_files(uploaded)
                if files_dict:
                    pressure_files[kpa] = files_dict
                    st.markdown(
                        f"<span class='badge-success'>✅ {len(files_dict)} files</span>",
                        unsafe_allow_html=True,
                    )

    if not pressure_files:
        st.warning("Upload point files (ZIP or individual TXT) for the selected pressure levels.")
        return None

    return pressure_files


# ---------------------------------------------------------------------------
# Processing pipeline
# ---------------------------------------------------------------------------
def run_processing(
    pressure_files: dict,
    speed: float,
    display_config: dict,
    db_config: dict,
) -> bool:
    """Run processing pipeline. Returns True on success."""
    try:
        compiled = compile_all_pressures(pressure_files, speed)
        point_names = extract_point_names_from_columns(compiled.columns)
        summary = build_summary(compiled, point_names)

        st.session_state[SESSION_COMPILED_DF] = compiled
        st.session_state[SESSION_SUMMARY_DF] = summary
        st.session_state[SESSION_POINT_NAMES] = point_names
        st.session_state[SESSION_CONFIG] = display_config

        if DB_AVAILABLE:
            save_config(db_config)

        st.success(
            f"✅ Processed {len(pressure_files)} pressure level(s), {len(compiled)} total rows"
        )
        return True
    except Exception as e:
        st.error(f"❌ Processing failed: {e}")
        return False


# ---------------------------------------------------------------------------
# UI: Results
# ---------------------------------------------------------------------------
def _render_angle_chart(df: pd.DataFrame, col: str, title: str) -> None:
    """Render a single angle line chart."""
    if col not in df.columns:
        return
    fig = px.line(
        df, x="Time", y=col, color="Pressure (kPa)",
        title=title,
        labels={col: "Angle (°)"},
    )
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)


def _render_results_tabs(
    compiled: pd.DataFrame,
    summary: pd.DataFrame,
    point_names: list,
    config: dict,
) -> None:
    """Render Data, Charts, Summary, and Export tabs."""
    tab_data, tab_charts, tab_summary, tab_export = st.tabs(
        ["📋 Data", "📈 Charts", "📊 Summary", "📥 Export"]
    )

    with tab_data:
        st.dataframe(compiled, use_container_width=True, height=400)

    with tab_charts:
        ch1, ch2 = st.columns(2)
        with ch1:
            _render_angle_chart(compiled, "angle1", "Angle 1 (P7-P1-P8) over Time")
        with ch2:
            _render_angle_chart(compiled, "angle2", "Angle 2 (P5-P2-P6) over Time")

        disp_cols = [c for c in compiled.columns if c.endswith("_disp")]
        if disp_cols:
            st.markdown("#### Displacement")
            selected_point = st.selectbox("Select point", point_names, key="disp_point")
            disp_col = f"{selected_point}_disp"
            if disp_col in compiled.columns:
                fig = px.line(
                    compiled, x="Time", y=disp_col, color="Pressure (kPa)",
                    title=f"Displacement of {selected_point} over Time",
                    labels={disp_col: "Displacement (mm)"},
                )
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)

    with tab_summary:
        st.markdown("#### Max Displacement & Statistics per Pressure")
        st.dataframe(summary, use_container_width=True)

    with tab_export:
        st.markdown("#### Download Compiled Excel")
        excel_bytes = to_excel_bytes(compiled, config, summary)
        finger_type = config.get("Finger", "finger")
        body_material = config.get("Body Material", "test")
        fname = f"{finger_type}_{body_material}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        st.download_button(
            "📥 Download Excel",
            data=excel_bytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )
        st.caption(
            f"File: {fname} · {len(compiled)} rows · {compiled['Pressure (kPa)'].nunique()} pressure levels"
        )


def render_results(
    compiled: pd.DataFrame,
    summary: pd.DataFrame,
    point_names: list,
    config: dict,
) -> None:
    """Render full results section."""
    st.markdown("---")
    st.markdown("### 📊 Results")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pressure Levels", compiled["Pressure (kPa)"].nunique())
    m2.metric("Total Rows", len(compiled))
    m3.metric("Points Tracked", len(point_names))
    if "angle1" in compiled.columns:
        m4.metric("Avg Angle 1", f"{compiled['angle1'].mean():.1f}°")

    _render_results_tabs(compiled, summary, point_names, config)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Main application entry point."""
    init_page()

    loaded = st.session_state.pop(SESSION_LOAD_CONFIG, None)
    render_sidebar()

    display_config, db_config = render_config_form(loaded)
    st.markdown("---")

    pressure_files = render_upload_section()
    if pressure_files is None:
        st.stop()

    st.markdown("---")
    st.markdown("### ⚡ Process Data")

    if st.button("▶ Process & Compile", type="primary", use_container_width=True):
        with st.spinner("Processing point data..."):
            run_processing(
                pressure_files,
                db_config["speed"],
                display_config,
                db_config,
            )

    if SESSION_COMPILED_DF in st.session_state:
        render_results(
            st.session_state[SESSION_COMPILED_DF],
            st.session_state[SESSION_SUMMARY_DF],
            st.session_state[SESSION_POINT_NAMES],
            st.session_state[SESSION_CONFIG],
        )

    st.markdown("---")
    st.markdown(
        '<p style="text-align:center; color:#94A3B8; font-size:0.8rem;">'
        "Finger Bending Analysis Tool</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
