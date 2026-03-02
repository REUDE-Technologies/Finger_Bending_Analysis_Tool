"""
Finger Bending Analysis Tool — Streamlit App (v3)

Slim orchestration layer. All logic lives in:
  - styles.py     → CSS, page init, stepper, section helpers
  - ui_helpers.py → config form, sidebar, session keys
  - upload.py     → dual-mode upload (ZIP / per-pressure)
  - results.py    → charts, data tabs, export
  - processing.py → data pipeline & Excel export
"""

import logging

logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(
    logging.ERROR
)

import streamlit as st

from styles import init_page, section, divider, footer
from ui_helpers import (
    render_config,
    render_sidebar,
    SESSION_COMPILED_DF,
    SESSION_SUMMARY_DF,
    SESSION_POINT_NAMES,
    SESSION_CONFIG,
    SESSION_LOAD_CONFIG,
)
from upload import render_upload_tab, render_select_tab
from results import render_results, render_ml_section
from processing import (
    compile_all_pressures,
    extract_point_names_from_columns,
    build_summary,
)

# ── DB import (optional) ──
try:
    from db import save_config
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════
# Processing helper
# ═══════════════════════════════════════════════════════════════════════════
def _run_processing(pf, speed, disp_cfg, db_cfg) -> bool:
    """Run the analysis pipeline and cache results in session state."""
    try:
        compiled = compile_all_pressures(pf, speed)
        pn = extract_point_names_from_columns(compiled.columns)
        summ = build_summary(compiled, pn)

        st.session_state[SESSION_COMPILED_DF] = compiled
        st.session_state[SESSION_SUMMARY_DF] = summ
        st.session_state[SESSION_POINT_NAMES] = pn
        st.session_state[SESSION_CONFIG] = disp_cfg

        if DB_AVAILABLE:
            save_config(db_cfg)

        st.success(f"✅ Processed {len(pf)} pressure level(s) — {len(compiled)} rows")
        return True
    except Exception as e:
        st.error(f"❌ Processing failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Main — tabbed layout
# ═══════════════════════════════════════════════════════════════════════════
def main():
    init_page()
    loaded = st.session_state.pop(SESSION_LOAD_CONFIG, None)
    render_sidebar()

    tab_config, tab_upload, tab_select, tab_process, tab_ml = st.tabs([
        "📋 Config", "📦 Upload", "🎯 Select", "⚡ Process", "🤖 ML Model",
    ])

    with tab_config:
        disp_cfg, db_cfg = render_config(loaded)
        st.session_state["_disp_cfg"] = disp_cfg
        st.session_state["_db_cfg"] = db_cfg

    with tab_upload:
        render_upload_tab()

    with tab_select:
        render_select_tab()

    with tab_process:
        section("⚡", "blue", "Process & Compile",
                "Run the analysis pipeline on your selected data")
        pressure_files = st.session_state.get("_pressure_files")
        disp_cfg = st.session_state.get("_disp_cfg", {})
        db_cfg = st.session_state.get("_db_cfg", {})

        if pressure_files is None or len(pressure_files) == 0:
            st.info("Complete **Upload** and **Select** tabs first, then run processing here.")
        else:
            if st.button("▶  Process & Compile", type="primary", use_container_width=True, key="tab_process_btn"):
                with st.spinner("Processing point data…"):
                    _run_processing(pressure_files, db_cfg.get("speed", 0), disp_cfg, db_cfg)

        if SESSION_COMPILED_DF in st.session_state:
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            render_results(
                st.session_state[SESSION_COMPILED_DF],
                st.session_state[SESSION_SUMMARY_DF],
                st.session_state[SESSION_POINT_NAMES],
                st.session_state[SESSION_CONFIG],
                include_ml=False,
            )

    with tab_ml:
        if SESSION_COMPILED_DF in st.session_state:
            # Use augmented data (same as in render_results)
            from results import _augment_with_geometry, _augment_summary
            compiled = _augment_with_geometry(
                st.session_state[SESSION_COMPILED_DF],
                st.session_state[SESSION_POINT_NAMES],
                st.session_state[SESSION_CONFIG],
            )
            summary = _augment_summary(compiled, st.session_state[SESSION_SUMMARY_DF])
            render_ml_section(compiled, summary)
        else:
            st.info("Process data in the **Process** tab first to use the ML model.")

    footer()


if __name__ == "__main__":
    main()
