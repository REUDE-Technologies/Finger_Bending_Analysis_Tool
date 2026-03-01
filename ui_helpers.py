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

        loaded = loaded or {}
        c1, c2, c3 = st.columns(3)
        with c1:
            ft_opts = get_finger_types() if DB_AVAILABLE else []
            finger_type = _select_or_add("Finger Type", ft_opts,
                                          loaded.get("finger_type", ""), "ft")
        with c2:
            finger_length = st.number_input(
                "Finger Length (mm)", min_value=0.0, step=1.0,
                value=float(loaded.get("finger_length", 0)),
            )
        with c3:
            speed = st.number_input(
                "Speed (m/s)", min_value=0.0, step=0.01, format="%.2f",
                value=float(loaded.get("speed", 0)),
            )

        c4, c5, c6 = st.columns(3)
        with c4:
            bm_opts = get_materials("body") if DB_AVAILABLE else []
            body_mat = _select_or_add("Body Material", bm_opts,
                                       loaded.get("body_material", ""), "bm")
        with c5:
            sm_opts = get_materials("skin") if DB_AVAILABLE else []
            skin_mat = _select_or_add("Skin Material", sm_opts,
                                       loaded.get("skin_material", ""), "sm")
        with c6:
            designed_by = st.text_input("Designed By",
                                         value=loaded.get("designed_by", ""))

        design_ver = st.text_input("Design Version",
                                    value=loaded.get("design_version", ""))

    disp = {
        "Finger": finger_type, "Finger Length (mm)": finger_length,
        "Body Material": body_mat, "Skin Material": skin_mat,
        "Speed (m/s)": speed, "Designed By": designed_by,
        "Design Version": design_ver,
    }
    db = {
        "finger_type": finger_type, "finger_length": finger_length,
        "body_material": body_mat, "skin_material": skin_mat,
        "speed": speed, "designed_by": designed_by,
        "design_version": design_ver,
    }
    return disp, db


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚡ Quick Load")
        if DB_AVAILABLE:
            recent = get_recent_configs(10)
            if recent:
                labels = [
                    f"{r.get('finger_type','?')} · {r.get('body_material','?')} · {r.get('created_at','')[:10]}"
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
        st.markdown("### 📁 ZIP Layout")
        st.code(
            "data.zip\n"
            "├── 10/\n│   ├── p1.txt\n│   ├── p2.txt\n│   └── …\n"
            "├── 20/\n│   └── …\n"
            "└── 30kpa/\n    └── …",
            language=None,
        )
        st.caption("Folders named by pressure (kPa). Each contains point `.txt` files.")
