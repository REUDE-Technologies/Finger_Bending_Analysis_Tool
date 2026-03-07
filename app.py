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
from features_tab import render_features_tab
from results import render_results, render_ml_section
try:
    from dl_model_tab import render_dl_model_tab
except ImportError:
    render_dl_model_tab = None  # e.g. missing torch
try:
    from esn_model_tab import render_esn_model_tab
except ImportError:
    render_esn_model_tab = None
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

        saved = False
        if DB_AVAILABLE:
            saved = save_config(db_cfg)

        if saved:
            st.success(f"✅ Processed {len(pf)} pressure level(s) — {len(compiled)} rows. 💾 Config correctly saved to Supabase db!")
        else:
            st.success(f"✅ Processed {len(pf)} pressure level(s) — {len(compiled)} rows")
            if DB_AVAILABLE:
                st.warning("⚠️ Could not save your run configuration to Supabase.")
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

    tab_config, tab_upload, tab_select, tab_features, tab_process, tab_ml, tab_dl, tab_esn = st.tabs([
        "📋 Config", "📦 Upload", "🎯 Select", "📐 Features", "⚡ Process", "🤖 ML Model", "🧠 DL Model", "🌊 ESN Model",
    ])

    with tab_config:
        disp_cfg, db_cfg = render_config(loaded)
        st.session_state["_disp_cfg"] = disp_cfg
        st.session_state["_db_cfg"] = db_cfg

    with tab_upload:
        render_upload_tab()

    with tab_select:
        render_select_tab()

    with tab_features:
        render_features_tab()

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
            try:
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                render_results(
                    st.session_state[SESSION_COMPILED_DF],
                    st.session_state.get(SESSION_SUMMARY_DF),
                    st.session_state.get(SESSION_POINT_NAMES, []),
                    st.session_state.get(SESSION_CONFIG, {}),
                    include_ml=False,
                )
            except Exception as e:
                st.error(f"Process tab error: {e}")
                with st.expander("Technical details"):
                    st.exception(e)

    with tab_ml:
        if SESSION_COMPILED_DF in st.session_state:
            try:
                from results import _augment_with_geometry, _augment_summary
                compiled_raw = st.session_state[SESSION_COMPILED_DF]
                pn = st.session_state.get(SESSION_POINT_NAMES, [])
                cfg = st.session_state.get(SESSION_CONFIG, {}) or {}
                summary_raw = st.session_state.get(SESSION_SUMMARY_DF)
                compiled = _augment_with_geometry(compiled_raw, pn, cfg)
                summary = _augment_summary(compiled, summary_raw)
                if compiled is not None and len(compiled) > 0:
                    render_ml_section(compiled, summary)
                else:
                    st.warning("Augmented data is empty. Check Process tab and try again.")
            except Exception as e:
                st.error(f"ML Model tab error: {e}")
                with st.expander("Technical details"):
                    st.exception(e)
        else:
            st.info("Process data in the **Process** tab first to use the ML model.")

    with tab_dl:
        if render_dl_model_tab is None:
            st.info("DL Model tab requires PyTorch. Install with: `pip install torch`")
        elif SESSION_COMPILED_DF in st.session_state:
            try:
                from results import _augment_with_geometry, _augment_summary
                cfg = st.session_state.get(SESSION_CONFIG, {}) or {}
                compiled = _augment_with_geometry(
                    st.session_state[SESSION_COMPILED_DF],
                    st.session_state.get(SESSION_POINT_NAMES, []),
                    cfg,
                )
                summary = _augment_summary(compiled, st.session_state.get(SESSION_SUMMARY_DF))
                if compiled is not None and len(compiled) > 0:
                    render_dl_model_tab(compiled, summary, st.session_state.get(SESSION_POINT_NAMES, []), cfg)
                else:
                    st.warning("Augmented data is empty. Check Process tab and try again.")
            except Exception as e:
                st.error(f"DL Model tab error: {e}")
                with st.expander("Technical details"):
                    st.exception(e)
        else:
            st.info("Process data in the **Process** tab first to use the DL model.")

    with tab_esn:
        if render_esn_model_tab is None:
            st.info("ESN Model tab failed to load. Check that esn_model_tab.py exists and dependencies (sklearn, plotly) are installed.")
        elif SESSION_COMPILED_DF in st.session_state:
            try:
                from results import _augment_with_geometry, _augment_summary
                cfg = st.session_state.get(SESSION_CONFIG, {}) or {}
                compiled = _augment_with_geometry(
                    st.session_state[SESSION_COMPILED_DF],
                    st.session_state.get(SESSION_POINT_NAMES, []),
                    cfg,
                )
                summary = _augment_summary(compiled, st.session_state.get(SESSION_SUMMARY_DF))
                if compiled is not None and len(compiled) > 0:
                    render_esn_model_tab(compiled, summary, st.session_state.get(SESSION_POINT_NAMES, []), cfg)
                else:
                    st.warning("Augmented data is empty. Check Process tab and try again.")
            except Exception as e:
                st.error(f"ESN Model tab error: {e}")
                with st.expander("Technical details"):
                    st.exception(e)
        else:
            st.info("Process data in the **Process** tab first to use the ESN model.")

    footer()


if __name__ == "__main__":
    main()
