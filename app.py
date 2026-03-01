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

from styles import init_page, stepper, section, divider, footer
from ui_helpers import (
    render_config,
    render_sidebar,
    SESSION_COMPILED_DF,
    SESSION_SUMMARY_DF,
    SESSION_POINT_NAMES,
    SESSION_CONFIG,
    SESSION_LOAD_CONFIG,
)
from upload import render_upload
from results import render_results
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
# Determine stepper step from session state
# ═══════════════════════════════════════════════════════════════════════════
def _current_step() -> int:
    """Return the active step (1-4) based on session state flags.

    Flags _step_upload and _step_select are set by the upload module.
    SESSION_COMPILED_DF is set after successful processing.
    """
    if SESSION_COMPILED_DF in st.session_state:
        return 4
    if st.session_state.get("_step_select"):
        return 3
    if st.session_state.get("_step_upload"):
        return 2
    return 1


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
def main():
    init_page()
    loaded = st.session_state.pop(SESSION_LOAD_CONFIG, None)
    render_sidebar()

    # Stepper shows progress from the *previous* run (session state persists)
    stepper(_current_step())

    # ── Step 1: Configure ──
    disp_cfg, db_cfg = render_config(loaded)
    divider()

    # ── Steps 2 & 3: Upload + Select ──
    pressure_files = render_upload()

    if pressure_files is None:
        if SESSION_COMPILED_DF in st.session_state:
            render_results(
                st.session_state[SESSION_COMPILED_DF],
                st.session_state[SESSION_SUMMARY_DF],
                st.session_state[SESSION_POINT_NAMES],
                st.session_state[SESSION_CONFIG],
            )
        footer()
        return

    divider()

    # ── Step 4: Process ──
    with st.container(border=True):
        section("⚡", "blue", "Process & Compile",
                "Run the analysis pipeline on your selected data")

        if st.button("▶  Process & Compile", type="primary", use_container_width=True):
            with st.spinner("Processing point data…"):
                _run_processing(pressure_files, db_cfg["speed"], disp_cfg, db_cfg)


    if SESSION_COMPILED_DF in st.session_state:
        render_results(
            st.session_state[SESSION_COMPILED_DF],
            st.session_state[SESSION_SUMMARY_DF],
            st.session_state[SESSION_POINT_NAMES],
            st.session_state[SESSION_CONFIG],
        )

    footer()


if __name__ == "__main__":
    main()
