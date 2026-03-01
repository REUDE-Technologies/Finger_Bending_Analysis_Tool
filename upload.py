"""
Upload module — dual-mode upload (ZIP auto-detect / per-pressure).

Exports:
    render_upload()  → returns {kpa: {filename: bytes}} or None
"""
import re
import streamlit as st
from styles import section
from processing import (
    extract_zip,
    scan_zip_structure,
    get_zip_summary,
    filter_pressure_files,
)

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════
PRESSURE_OPTIONS = list(range(10, 110, 10))  # 10 … 100 kPa


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════
def _process_uploaded_files(uploaded_files: list) -> dict[str, bytes]:
    """Convert uploaded ZIP/TXT files into {filename: content} dict."""
    result = {}
    for f in uploaded_files:
        data = f.read()
        if f.name.lower().endswith(".zip"):
            result.update(extract_zip(data))
        elif f.name.lower().endswith(".txt"):
            result[f.name] = data
    return result


def _extract_point_name(filename: str) -> str | None:
    """Extract point name from filename. e.g. 'p1.txt' → 'p1'."""
    m = re.match(r"(p\d+)", filename.lower().replace(".txt", ""))
    return m.group(1) if m else None


# ═══════════════════════════════════════════════════════════════════════════
# ZIP upload mode
# ═══════════════════════════════════════════════════════════════════════════
def _render_zip_mode() -> dict[int, dict[str, bytes]] | None:
    """Upload ZIP → auto-detect pressures & points → select & filter."""
    st.markdown(
        '<div class="upload-hero">'
        '<div class="u-icon">📦</div>'
        '<p class="u-title">Upload ZIP folder</p>'
        '<p class="u-desc">Upload a ZIP file containing pressure-level subfolders '
        '(e.g. 10 kpa/, 30kpa/) with point .txt files — everything is detected automatically</p>'
        '<span class="fmt-pill">.ZIP</span>'
        '<span class="fmt-pill">AUTO-DETECT</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    uploaded = st.file_uploader(
        "Upload ZIP", type=["zip"],
        accept_multiple_files=False, key="zip_upload",
        label_visibility="collapsed",
    )

    if not uploaded:
        st.session_state["_step_upload"] = False
        return None

    # Step 2 reached — files uploaded
    st.session_state["_step_upload"] = True

    data = uploaded.read()
    try:
        pf = scan_zip_structure(data)
    except Exception as e:
        st.error(f"❌ Could not read ZIP: {e}")
        return None

    if not pf:
        st.error(
            "❌ **No pressure levels detected.**  \n"
            "ZIP must contain subfolders named by pressure (e.g. `10 kpa/`, `30kpa/`) "
            "each containing `.txt` point files."
        )
        return None

    summ = get_zip_summary(pf)

    # ── Scan banner ──
    st.markdown(
        f'<div class="scan-ok">'
        f'<h4>✅ Scan Complete — {uploaded.name}</h4>'
        f'<div class="scan-kpis">'
        f'<div class="kpi"><div class="num">{len(summ["pressures"])}</div><div class="tag">Pressures</div></div>'
        f'<div class="kpi"><div class="num">{len(summ["all_points"])}</div><div class="tag">Points</div></div>'
        f'<div class="kpi"><div class="num">{summ["total_files"]}</div><div class="tag">Files</div></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Structure table ──
    with st.expander("📂 View detected structure", expanded=False):
        rows = ""
        for kpa in summ["pressures"]:
            pts = summ["points_per_pressure"][kpa]
            chips = " ".join(f'<span class="pt-tag">{p}</span>' for p in pts)
            rows += (
                f'<tr><td><span class="kpa-tag">⚡ {kpa} kPa</span></td>'
                f'<td style="font-weight:700">{len(pts)}</td>'
                f'<td>{chips}</td></tr>'
            )
        st.markdown(
            f'<table class="s-table"><thead><tr>'
            f'<th>Pressure</th><th>Files</th><th>Points</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Filter selection ──
    with st.container(border=True):
        section("🎯", "amber", "Select Data for Output",
                "Toggle off any pressures or points you don't need")

        s1, s2 = st.columns(2)
        with s1:
            fmt_p = [f"{k} kPa" for k in summ["pressures"]]
            sel_p_labels = st.pills(
                "Pressure Levels",
                options=fmt_p, default=fmt_p,
                selection_mode="multi", key="zip_pressure_pills",
            )
        with s2:
            fmt_pts = [p.upper() for p in summ["all_points"]]
            sel_pt_labels = st.pills(
                "Tracking Points",
                options=fmt_pts, default=fmt_pts,
                selection_mode="multi", key="zip_point_pills",
            )

    sel_pressures = [int(l.replace(" kPa", "")) for l in sel_p_labels] if sel_p_labels else []
    sel_points = [p.lower() for p in sel_pt_labels] if sel_pt_labels else []

    if not sel_pressures:
        st.warning("⚠️ Select at least one pressure level.")
        st.session_state["_step_select"] = False
        return None
    if not sel_points:
        st.warning("⚠️ Select at least one tracking point.")
        st.session_state["_step_select"] = False
        return None

    # Step 3 reached — selection made
    st.session_state["_step_select"] = True

    filtered = filter_pressure_files(pf, sel_pressures, sel_points)
    if not filtered:
        st.error("❌ No data matches current selection.")
        return None

    total = sum(len(v) for v in filtered.values())
    st.markdown(
        f"<span class='b-neut'>📊 Ready: {len(filtered)} pressures · {total} files</span>",
        unsafe_allow_html=True,
    )
    return filtered


# ═══════════════════════════════════════════════════════════════════════════
# Manual (per-pressure) upload mode
# ═══════════════════════════════════════════════════════════════════════════
def _render_manual_mode() -> dict[int, dict[str, bytes]] | None:
    """Select pressures → upload files per pressure → filter points."""
    fmt_options = [f"{k} kPa" for k in PRESSURE_OPTIONS]
    selected_labels = st.pills(
        "Pressure Levels (kPa)",
        options=fmt_options,
        default=None,
        selection_mode="multi",
        key="pressure_pills",
    )

    selected_pressures = [int(l.replace(" kPa", "")) for l in selected_labels] if selected_labels else []

    if not selected_pressures:
        st.info("👆 Select pressure levels above, then upload point files for each.")
        st.session_state["_step_upload"] = False
        st.session_state["_step_select"] = False
        return None

    st.markdown(
        f"<span class='b-info'>📊 {len(selected_pressures)} pressure level(s) selected</span>",
        unsafe_allow_html=True,
    )

    pressure_files: dict[int, dict[str, bytes]] = {}
    cols_per_row = min(len(selected_pressures), 3)
    sorted_pressures = sorted(selected_pressures)

    for row_start in range(0, len(sorted_pressures), cols_per_row):
        row_pressures = sorted_pressures[row_start:row_start + cols_per_row]
        cols = st.columns(len(row_pressures))

        for col, kpa in zip(cols, row_pressures):
            with col:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='text-align:center; margin-bottom:8px;'>"
                        f"<span style='font-size:1.6rem; font-weight:800; "
                        f"background:linear-gradient(135deg,#1B6CA8,#3B82F6); "
                        f"-webkit-background-clip:text; -webkit-text-fill-color:transparent; "
                        f"background-clip:text;'>{kpa}</span>"
                        f"<span style='font-size:0.75rem; font-weight:600; color:#64748B; "
                        f"display:block; text-transform:uppercase; letter-spacing:0.05em;'>kPa</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    uploaded = st.file_uploader(
                        f"Upload for {kpa} kPa",
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
                                f"<span class='b-ok'>✅ {len(files_dict)} file(s)</span>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Drop ZIP or TXT files")

    if not pressure_files:
        st.warning("Upload point files (ZIP or individual .txt) for the selected pressure levels.")
        st.session_state["_step_upload"] = False
        st.session_state["_step_select"] = False
        return None

    # Step 2 reached
    st.session_state["_step_upload"] = True

    # ── Detect unique points across all uploaded pressures ──
    all_points: set[str] = set()
    for kpa, files in pressure_files.items():
        for fname in files:
            pt = _extract_point_name(fname)
            if pt:
                all_points.add(pt)

    if all_points:
        sorted_pts = sorted(all_points, key=lambda p: int(re.sub(r'\D', '', p) or 0))
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

        with st.container(border=True):
            section("🎯", "amber", "Filter Tracking Points",
                    "Deselect any points you don't need in the output")
            fmt_pts = [p.upper() for p in sorted_pts]
            sel_pt_labels = st.pills(
                "Tracking Points",
                options=fmt_pts, default=fmt_pts,
                selection_mode="multi", key="manual_point_pills",
            )

        sel_points = {p.lower() for p in sel_pt_labels} if sel_pt_labels else set()

        if not sel_points:
            st.warning("⚠️ Select at least one tracking point.")
            st.session_state["_step_select"] = False
            return None

        # Step 3 reached
        st.session_state["_step_select"] = True

        # Filter out deselected points from each pressure
        if sel_points != all_points:
            for kpa in list(pressure_files.keys()):
                filtered = {}
                for fname, content in pressure_files[kpa].items():
                    pt = _extract_point_name(fname)
                    if pt and pt in sel_points:
                        filtered[fname] = content
                    elif not pt:
                        filtered[fname] = content  # keep non-point files
                pressure_files[kpa] = filtered
    else:
        st.session_state["_step_select"] = True

    total_files = sum(len(v) for v in pressure_files.values())
    st.markdown(
        f"<span class='b-neut'>📊 Ready: {len(pressure_files)} pressure level(s) · {total_files} files</span>",
        unsafe_allow_html=True,
    )
    return pressure_files


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════
def render_upload() -> dict[int, dict[str, bytes]] | None:
    """
    Render dual-mode upload section.
    Returns {kpa: {filename: bytes}} or None.
    """
    with st.container(border=True):
        section("📦", "green", "Upload Point Data",
                "Upload a ZIP with all pressures or upload per pressure level")

        mode = st.segmented_control(
            "Input Mode",
            options=["📦 Upload ZIP", "📋 Select & Upload"],
            default="📦 Upload ZIP",
            key="input_mode",
            label_visibility="collapsed",
        )

    if mode == "📦 Upload ZIP":
        return _render_zip_mode()
    else:
        return _render_manual_mode()
