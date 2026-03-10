"""
UI helpers — config form, sidebar, and selectbox with 'add new' option.
"""
import streamlit as st
from styles import section

# ── DB import (optional) ──
try:
    from db import (
        get_finger_types,
        get_materials,
        get_recent_configs,
    )
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════
# Session keys (shared across modules)
# ═══════════════════════════════════════════════════════════════════════════
SESSION_COMPILED_DF = "compiled_df"
SESSION_SUMMARY_DF = "summary_df"
SESSION_POINT_NAMES = "point_names"
SESSION_CONFIG = "config"
SESSION_LOAD_CONFIG = "_load_config"
SESSION_SAVED_CHARTS = "_saved_chart_html"  # {chart_name: html_string}

# Default options for config tab dropdowns
MATERIAL_OPTIONS = ["dragon30", "ss960", "smooth960", "eco30", "ecoflex30"]
FINGER_TYPE_OPTIONS = [f"Finger {i}" for i in range(1, 11)]  # Finger 1 .. Finger 10

# Default config when app starts (no saved config loaded)
DEFAULT_CONFIG = {
    "finger_type": "Finger 1",
    "finger_length": 60,
    "finger_width": 10,
    "body_material": "ss960",
    "skin_material": "dragon30",
}


# ═══════════════════════════════════════════════════════════════════════════
# Selectbox with "add new" option
# ═══════════════════════════════════════════════════════════════════════════
def _select_or_add(label, options, default, key):
    opts = [""] + options + ["+ Add new…"]
    idx = options.index(default) + 1 if default and default in options else 0
    sel = st.selectbox(label, opts, index=idx, key=f"{key}_sel")
    if sel == "+ Add new…":
        sel = st.text_input(f"New {label.lower()}", key=f"{key}_new")
    return sel or ""


# ═══════════════════════════════════════════════════════════════════════════
# Config form  →  returns (display_cfg, db_cfg)
# ═══════════════════════════════════════════════════════════════════════════
def render_config(loaded: dict | None) -> tuple[dict, dict]:
    with st.container(border=True):
        section("📋", "blue", "Test Configuration",
                "Define experiment parameters and metadata for this run")

        # Merge defaults with any loaded config so form shows defaults on start
        values = {**DEFAULT_CONFIG, **(loaded or {})}
        c1, c2, c3 = st.columns(3)
        with c1:
            ft_opts = sorted(set((get_finger_types() if DB_AVAILABLE else []) + FINGER_TYPE_OPTIONS))
            finger_type = _select_or_add("Finger Type", ft_opts,
                                          values.get("finger_type", ""), "ft")
        with c2:
            finger_length = st.number_input(
                "Finger Length (mm)", min_value=0.0, step=1.0,
                value=float(values.get("finger_length", 0)),
            )
            finger_width = st.number_input(
                "Finger Width (mm)", min_value=0.0, step=1.0,
                value=float(values.get("finger_width", 0)),
            )
        with c3:
            speed = st.number_input(
                "Speed (m/s)", min_value=0.0, step=0.01, format="%.2f",
                value=float(values.get("speed", 0)),
            )

        c4, c5, c6 = st.columns(3)
        with c4:
            bm_opts = sorted(set((get_materials("body") if DB_AVAILABLE else []) + MATERIAL_OPTIONS))
            body_mat = _select_or_add("Body Material", bm_opts,
                                       values.get("body_material", ""), "bm")
        with c5:
            sm_opts = sorted(set((get_materials("skin") if DB_AVAILABLE else []) + MATERIAL_OPTIONS))
            skin_mat = _select_or_add("Skin Material", sm_opts,
                                       values.get("skin_material", ""), "sm")
        with c6:
            prepared_by = st.text_input("Prepared By",
                                         value=values.get("prepared_by", ""))

        # Save current config to Supabase so it persists (survives refresh / Railway restart)
        if DB_AVAILABLE:
            if st.button("💾 Save config to Supabase", key="config_save_btn", help="Save current form to the database so you can load it later from the sidebar."):
                from db import save_config
                db_cfg = {
                    "finger_type": finger_type, "finger_length": finger_length,
                    "finger_width": finger_width, "body_material": body_mat,
                    "skin_material": skin_mat, "speed": speed, "prepared_by": prepared_by,
                }
                ok, err = save_config(db_cfg)
                if ok:
                    st.success("Config saved. Use **Load previous config** in the sidebar to restore it.")
                else:
                    st.error(f"Could not save: {err}")
                    with st.expander("Details"):
                        st.code(err, language=None)

    disp = {
        "Finger": finger_type, "Finger Length (mm)": finger_length,
        "Finger Width (mm)": finger_width,
        "Body Material": body_mat, "Skin Material": skin_mat,
        "Speed (m/s)": speed, "Prepared By": prepared_by,
    }
    db = {
        "finger_type": finger_type, "finger_length": finger_length,
        "finger_width": finger_width,
        "body_material": body_mat, "skin_material": skin_mat,
        "speed": speed, "prepared_by": prepared_by,
    }
    return disp, db


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════
def render_sidebar() -> None:
    import psutil
    from run_presets import list_run_presets, load_run_preset
    from session_store import save_session, list_saved_sessions, load_saved_session, delete_saved_session

    with st.sidebar:
        st.markdown("### 🖥️ System Resources")
        cpu_usage = psutil.cpu_percent()
        ram_usage = psutil.virtual_memory().percent

        col1, col2 = st.columns(2)
        with col1:
            st.metric("CPU", f"{cpu_usage}%")
        with col2:
            st.metric("RAM", f"{ram_usage}%")

        st.markdown("---")

        # ── 💾 SAVE SESSION (prominent at top) ──
        st.markdown("### 💾 Save Session")
        has_data = SESSION_COMPILED_DF in st.session_state and st.session_state[SESSION_COMPILED_DF] is not None
        if has_data:
            disp_cfg = st.session_state.get("_disp_cfg", {})
            db_cfg = st.session_state.get("_db_cfg", {})
            default_name = (
                f"{disp_cfg.get('Finger', db_cfg.get('finger_type', 'Run'))}"
                f" {db_cfg.get('body_material', '')} {db_cfg.get('skin_material', '')}"
                f" @ {db_cfg.get('speed', 0)} m/s"
            ).strip()
            save_name = st.text_input(
                "Session name", value=default_name, key="_save_session_name",
                help="A descriptive name for this session (e.g. 'Finger1 ss960 dragon30 @ 0.5 m/s')."
            )
            if st.button("💾 Save All Settings & Results", type="primary", use_container_width=True, key="_save_session_btn"):
                try:
                    compiled_df = st.session_state[SESSION_COMPILED_DF]
                    summary_df = st.session_state.get(SESSION_SUMMARY_DF)
                    point_names = st.session_state.get(SESSION_POINT_NAMES, [])
                    chart_html = st.session_state.get(SESSION_SAVED_CHARTS, {})

                    session_dir = save_session(
                        name=save_name,
                        disp_cfg=disp_cfg,
                        db_cfg=db_cfg,
                        compiled_df=compiled_df,
                        summary_df=summary_df,
                        point_names=point_names,
                        chart_html_map=chart_html,
                    )
                    st.success(f"✅ Session saved: **{save_name}**")
                    st.caption(f"📂 `{session_dir.name}`")
                except Exception as e:
                    st.error(f"Could not save session: {e}")
        else:
            st.info("Process data first (📦 Upload → 🎯 Select → ⚡ Process) to enable saving.")

        st.markdown("---")

        # ── 📂 LOAD SAVED SESSIONS ──
        st.markdown("### 📂 Saved Sessions")
        saved_sessions = list_saved_sessions()
        if saved_sessions:
            session_labels = [
                f"{s['label']}  ({s['num_pressures']}P · {s['num_rows']}R · {s['created'][:10]})"
                for s in saved_sessions
            ]
            sel_session = st.selectbox(
                "Load saved session",
                ["— Select a session —"] + session_labels,
                key="_load_session_sel",
            )
            if sel_session != "— Select a session —":
                chosen_idx = session_labels.index(sel_session)
                chosen = saved_sessions[chosen_idx]

                # Show session details
                with st.expander("📋 Session details", expanded=False):
                    dcfg = chosen.get("display_config", {})
                    dbcfg = chosen.get("db_config", {})
                    st.caption(f"**Name:** {chosen['label']}")
                    st.caption(f"**Created:** {chosen['created']}")
                    st.caption(f"**Rows:** {chosen['num_rows']}  |  **Pressures:** {chosen['num_pressures']}")
                    if dcfg:
                        st.caption(f"**Config:** {', '.join(f'{k}: {v}' for k, v in dcfg.items() if v)}")

                col_load, col_del = st.columns([3, 1])
                with col_load:
                    if st.button("📥 Load Session", type="primary", use_container_width=True, key="_load_session_btn"):
                        try:
                            data = load_saved_session(chosen["id"])
                            # Restore compiled and summary DataFrames
                            if data.get("compiled_df") is not None:
                                st.session_state[SESSION_COMPILED_DF] = data["compiled_df"]
                            if data.get("summary_df") is not None:
                                st.session_state[SESSION_SUMMARY_DF] = data["summary_df"]
                            # Restore point names
                            if data.get("point_names"):
                                st.session_state[SESSION_POINT_NAMES] = data["point_names"]
                            # Restore configs
                            if data.get("db_config"):
                                st.session_state[SESSION_LOAD_CONFIG] = data["db_config"]
                                st.session_state["_db_cfg"] = data["db_config"]
                            if data.get("display_config"):
                                st.session_state[SESSION_CONFIG] = data["display_config"]
                                st.session_state["_disp_cfg"] = data["display_config"]
                            # Restore chart HTML
                            if data.get("chart_html_map"):
                                st.session_state[SESSION_SAVED_CHARTS] = data["chart_html_map"]
                            st.success(f"✅ Loaded session: **{chosen['label']}**")
                            st.caption("All settings and results restored. Check tabs for results — no reprocessing needed!")
                        except Exception as e:
                            st.error(f"Could not load: {e}")
                with col_del:
                    if st.button("🗑️", help="Delete this session", key="_del_session_btn"):
                        if delete_saved_session(chosen["id"]):
                            st.success("Deleted.")
                            st.rerun()
                        else:
                            st.error("Could not delete.")
        else:
            st.caption("No saved sessions yet. Process data and click **Save All Settings & Results** above.")

        st.markdown("---")

        st.markdown("### 📖 How to Use")
        st.markdown(
            "1. **Configure**: Fill in the test metadata.\n"
            "2. **Upload**: Select **Upload ZIP** to auto-detect structure or **Select & Upload** to add files manually.\n"
            "3. **Select**: Choose the specific pressures and tracking points you want to include.\n"
            "4. **Process**: Click the blue button to analyze.\n"
            "5. **Save**: Click 💾 **Save All Settings & Results** in the sidebar.\n"
            "6. **Load**: Select a saved session to restore everything instantly."
        )

        st.markdown("---")

        st.markdown("### ⚡ Quick Load (Supabase)")
        from streamlit import config
        try:
            host_addr = config.get_option("server.address")
            st.caption(f"Server Binding: `{host_addr}`")
        except Exception:
            pass

        if DB_AVAILABLE:
            recent = get_recent_configs(10)
            if recent:
                labels = [
                    f"{r.get('finger_type','?')} · W:{r.get('finger_width','?')} · By: {r.get('prepared_by','')[:10]}"
                    for r in recent
                ]
                sel = st.selectbox("Load previous config", ["— New —"] + labels)
                if sel != "— New —":
                    st.session_state[SESSION_LOAD_CONFIG] = recent[labels.index(sel)]
            else:
                st.caption("No saved configs yet.")
        else:
            st.caption("Database not connected.")

        st.markdown("---")
        st.markdown("### 💾 Legacy Presets")
        presets = list_run_presets()
        if presets:
            labels = [p["label"] for p in presets]
            sel = st.selectbox("Load legacy preset (runs/ folder)", ["— None —"] + labels)
            if sel != "— None —":
                chosen = presets[labels.index(sel)]
                try:
                    data = load_run_preset(chosen["id"])
                    cfg = data.get("config") or {}
                    disp_cfg = cfg.get("display_config") or {}
                    db_cfg = cfg.get("db_config") or {}
                    compiled_df = data.get("compiled_df")
                    summary_df = data.get("summary_df")
                    if compiled_df is not None:
                        st.session_state[SESSION_COMPILED_DF] = compiled_df
                    if summary_df is not None:
                        st.session_state[SESSION_SUMMARY_DF] = summary_df
                    if db_cfg:
                        st.session_state[SESSION_LOAD_CONFIG] = db_cfg
                        st.session_state["_db_cfg"] = db_cfg
                    if disp_cfg:
                        st.session_state["_disp_cfg"] = disp_cfg
                    st.success("Loaded local preset. Check Config, Process, and other tabs.")
                except Exception as e:
                    st.error(f"Could not load preset: {e}")
        else:
            st.caption("No legacy presets.")

        st.markdown("---")
        st.markdown("### 📁 ZIP Layout")
        st.code(
            "data.zip\n"
            "├── 10/\n│   ├── p1.txt\n│   ├── p2.txt\n│   └── …\n"
            "├── 20/\n│   └── …\n"
            "└── 30kpa/\n    └── …",
            language=None,
        )
        st.caption("Folders named by pressure (kPa). Each contains point `.txt` files.")


# ═══════════════════════════════════════════════════════════════════════════
# Inverse prediction: target force & angle → pressure (for DL/ESN tabs)
# ═══════════════════════════════════════════════════════════════════════════
def render_inverse_prediction_section(compiled, key_prefix: str = "inv") -> None:
    """
    Render UI to predict required pressure from target force and bending angle(s).
    Fits a Ridge model from (angle1, angle2, Contact Force) → Pressure on compiled data.
    """
    st.markdown("#### Inverse prediction: target force & angle → pressure")
    st.caption(
        "Give target force and bending angle(s); predict required pressure. "
        "Apply this pressure to the finger and compare measured vs target to validate (feedback propagation)."
    )
    try:
        import numpy as np
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        st.warning(
            "Inverse prediction requires NumPy and scikit-learn. "
            "If you see a numpy.core.multiarray error, run: **pip install --upgrade numpy** then restart the app."
        )
        return

    pressure_col = "Pressure (kPa)" if "Pressure (kPa)" in compiled.columns else None
    if not pressure_col:
        st.warning("Compiled data must contain **Pressure (kPa)**.")
        return
    inv_cols = [c for c in ["angle1", "angle2", "Contact Force (N)"] if c in compiled.columns]
    if not inv_cols:
        st.warning("Need at least one of **angle1**, **angle2**, **Contact Force (N)** for inverse prediction.")
        return
    df = compiled.dropna(subset=[pressure_col] + inv_cols)
    if len(df) < 10:
        st.warning("Not enough rows for inverse model. Process more data first.")
        return
    X = df[inv_cols].values
    y = df[pressure_col].values
    scaler_X = StandardScaler()
    X_s = scaler_X.fit_transform(X)
    model = Ridge(alpha=1.0).fit(X_s, y)
    defaults = {c: float(df[c].mean()) for c in inv_cols}
    col1, col2 = st.columns(2)
    with col1:
        inputs = {}
        for c in inv_cols:
            if "angle" in c:
                inputs[c] = st.number_input(c, value=round(defaults[c], 1), step=1.0, key=f"{key_prefix}_{c}")
            else:
                inputs[c] = st.number_input(c, value=round(defaults[c], 3), step=0.01, format="%.3f", key=f"{key_prefix}_{c}")
    with col2:
        if st.button("Predict pressure", type="primary", key=f"{key_prefix}_btn"):
            X_new = np.array([[inputs[c] for c in inv_cols]])
            X_new_s = scaler_X.transform(X_new)
            pred = float(model.predict(X_new_s)[0])
            pred = max(0.0, pred)
            st.session_state[f"_inv_pred_{key_prefix}"] = pred
        if f"_inv_pred_{key_prefix}" in st.session_state:
            p = st.session_state[f"_inv_pred_{key_prefix}"]
            st.success(f"**Predicted pressure:** {p:.1f} kPa")
            st.caption("Apply this pressure to the finger and measure force/angle to validate (feedback propagation).")
