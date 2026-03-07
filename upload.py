"""
Upload module — dual-mode upload (ZIP auto-detect / per-pressure).

Exports:
    render_upload()  → returns {kpa: {filename: bytes}} or None
"""
import os
import re
from pathlib import Path

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


def _get_local_zip_options() -> list[tuple[str, str]]:
    """
    Scan app folder and optional 'data' subfolder for .zip files.
    Returns list of (display_label, absolute_path) for use in a selectbox.
    """
    out: list[tuple[str, str]] = []
    seen_basenames: set[str] = set()
    # Search cwd (folder from which streamlit is run) and cwd/data
    cwd = Path(os.getcwd())
    for base_dir in [cwd, cwd / "data"]:
        if not base_dir.is_dir():
            continue
        try:
            for path in sorted(base_dir.iterdir()):
                if path.suffix.lower() != ".zip" or not path.is_file():
                    continue
                name = path.name
                if name in seen_basenames:
                    continue
                seen_basenames.add(name)
                label = name if base_dir == cwd else f"data/{name}"
                out.append((label, str(path.resolve())))
        except OSError:
            continue
    return out


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
            sel_p_labels = st.multiselect(
                "Pressure Levels",
                options=fmt_p, default=fmt_p,
                key="zip_pressure_pills",
            )
        with s2:
            fmt_pts = [p.upper() for p in summ["all_points"]]
            sel_pt_labels = st.multiselect(
                "Tracking Points",
                options=fmt_pts, default=fmt_pts,
                key="zip_point_pills",
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
    selected_labels = st.multiselect(
        "Pressure Levels (kPa)",
        options=fmt_options,
        default=None,
        
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
            sel_pt_labels = st.multiselect(
                "Tracking Points",
                options=fmt_pts, default=fmt_pts,
                key="manual_point_pills",
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
def render_upload_tab():
    """
    Upload tab only: upload files (ZIP or per-pressure), scan, store in
    st.session_state["_scanned_pf"] and st.session_state["_upload_mode"].
    """
    with st.container(border=True):
        section("📦", "green", "Upload Point Data",
                "Upload a ZIP with all pressures or upload per pressure level")

        mode = st.radio(
            "Input Mode",
            options=["📦 Upload ZIP", "📋 Select & Upload"],
            horizontal=True,
            key="tab_input_mode",
            label_visibility="collapsed",
        )

    if mode == "📦 Upload ZIP":
        _upload_tab_zip()
    else:
        _upload_tab_manual()


def _upload_tab_zip():
    """ZIP mode: use a ZIP from folder or upload one, scan, store _scanned_pf."""
    st.markdown(
        '<div class="upload-hero">'
        '<div class="u-icon">📦</div>'
        '<p class="u-title">Upload ZIP folder</p>'
        '<p class="u-desc">Use a ZIP from this folder or upload one. ZIP must contain pressure-level subfolders '
        '(e.g. 10 kpa/, 30kpa/) with point .txt files — everything is detected automatically</p>'
        '<span class="fmt-pill">.ZIP</span>'
        '<span class="fmt-pill">AUTO-DETECT</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Option 1: Use ZIP from project folder ──
    local_zips = _get_local_zip_options()
    local_options = ["— Select a ZIP from this folder —"] + [label for label, _ in local_zips]
    selected_local = st.selectbox(
        "ZIP files in this folder",
        options=range(len(local_options)),
        format_func=lambda i: local_options[i],
        key="tab_zip_local_select",
        index=0,
    )
    use_local_path: str | None = None
    if selected_local and selected_local > 0 and local_zips:
        _, use_local_path = local_zips[selected_local - 1]

    # ── Option 2: Upload a new ZIP ──
    uploaded = st.file_uploader(
        "Or upload a new ZIP",
        type=["zip"],
        accept_multiple_files=False,
        key="tab_zip_upload",
        label_visibility="collapsed",
    )

    # Decide data source: upload wins over local selection
    data: bytes | None = None
    zip_display_name: str = "ZIP"
    if uploaded:
        data = uploaded.read()
        zip_display_name = uploaded.name
    elif use_local_path:
        try:
            with open(use_local_path, "rb") as f:
                data = f.read()
            zip_display_name = Path(use_local_path).name
        except Exception as e:
            st.error(f"❌ Could not read file: {e}")
            return

    if not data:
        if "_scanned_pf" in st.session_state:
            del st.session_state["_scanned_pf"]
        if "_upload_mode" in st.session_state:
            del st.session_state["_upload_mode"]
        return

    try:
        pf = scan_zip_structure(data)
    except Exception as e:
        st.error(f"❌ Could not read ZIP: {e}")
        return

    if not pf:
        st.error(
            "❌ **No pressure levels detected.**  \n"
            "ZIP must contain subfolders named by pressure (e.g. `10 kpa/`, `30kpa/`) "
            "each containing `.txt` point files."
        )
        return

    summ = get_zip_summary(pf)
    st.session_state["_scanned_pf"] = pf
    st.session_state["_upload_mode"] = "zip"

    st.markdown(
        f'<div class="scan-ok">'
        f'<h4>✅ Scan Complete — {zip_display_name}</h4>'
        f'<div class="scan-kpis">'
        f'<div class="kpi"><div class="num">{len(summ["pressures"])}</div><div class="tag">Pressures</div></div>'
        f'<div class="kpi"><div class="num">{len(summ["all_points"])}</div><div class="tag">Points</div></div>'
        f'<div class="kpi"><div class="num">{summ["total_files"]}</div><div class="tag">Files</div></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

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
    st.success("Go to the **Select** tab to choose pressures and points, then **Process** to run.")


def _upload_tab_manual():
    """Manual mode: select pressures, upload per pressure, store _scanned_pf."""
    fmt_options = [f"{k} kPa" for k in PRESSURE_OPTIONS]
    selected_labels = st.multiselect(
        "Pressure Levels (kPa)",
        options=fmt_options,
        default=None,
        
        key="tab_manual_pressure_pills",
    )

    selected_pressures = [int(l.replace(" kPa", "")) for l in selected_labels] if selected_labels else []

    if not selected_pressures:
        st.info("👆 Select pressure levels above, then upload point files for each.")
        if "_scanned_pf" in st.session_state:
            del st.session_state["_scanned_pf"]
        if "_upload_mode" in st.session_state:
            del st.session_state["_upload_mode"]
        return

    st.markdown(
        f"<span class='b-info'>📊 {len(selected_pressures)} pressure level(s) selected</span>",
        unsafe_allow_html=True,
    )

    pressure_files = {}
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
                        key=f"tab_upload_{kpa}",
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
        if "_scanned_pf" in st.session_state:
            del st.session_state["_scanned_pf"]
        if "_upload_mode" in st.session_state:
            del st.session_state["_upload_mode"]
        return

    st.session_state["_scanned_pf"] = pressure_files
    st.session_state["_upload_mode"] = "manual"
    st.success("Go to the **Select** tab to filter tracking points, then **Process** to run.")


def render_select_tab():
    """
    Select tab only: read _scanned_pf, show filter UI, store result in
    st.session_state["_pressure_files"]. Returns filtered dict or None.
    """
    pf = st.session_state.get("_scanned_pf")
    mode = st.session_state.get("_upload_mode")

    if not pf or mode not in ("zip", "manual"):
        st.info("Upload data in the **Upload** tab first.")
        return None

    with st.container(border=True):
        section("🎯", "amber", "Select Data for Output",
                "Choose which pressures and points to include")

    if mode == "zip":
        summ = get_zip_summary(pf)
        s1, s2 = st.columns(2)
        with s1:
            fmt_p = [f"{k} kPa" for k in summ["pressures"]]
            sel_p_labels = st.multiselect(
                "Pressure Levels",
                options=fmt_p, default=fmt_p,
                key="tab_select_zip_pressure",
            )
        with s2:
            fmt_pts = [p.upper() for p in summ["all_points"]]
            sel_pt_labels = st.multiselect(
                "Tracking Points",
                options=fmt_pts, default=fmt_pts,
                key="tab_select_zip_points",
            )

        sel_pressures = [int(l.replace(" kPa", "")) for l in sel_p_labels] if sel_p_labels else []
        sel_points = [p.lower() for p in sel_pt_labels] if sel_pt_labels else []

        if not sel_pressures:
            st.warning("⚠️ Select at least one pressure level.")
            return None
        if not sel_points:
            st.warning("⚠️ Select at least one tracking point.")
            return None

        filtered = filter_pressure_files(pf, sel_pressures, sel_points)
    else:
        all_points = set()
        for kpa, files in pf.items():
            for fname in files:
                pt = _extract_point_name(fname)
                if pt:
                    all_points.add(pt)
        sorted_pts = sorted(all_points, key=lambda p: int(re.sub(r'\D', '', p) or 0))
        fmt_pts = [p.upper() for p in sorted_pts]
        sel_pt_labels = st.multiselect(
            "Tracking Points",
            options=fmt_pts, default=fmt_pts,
            key="tab_select_manual_points",
        )
        sel_points = {p.lower() for p in sel_pt_labels} if sel_pt_labels else set()

        if not sel_points:
            st.warning("⚠️ Select at least one tracking point.")
            return None

        filtered = {}
        for kpa, files in pf.items():
            filtered[kpa] = {}
            for fname, content in files.items():
                pt = _extract_point_name(fname)
                if pt and pt in sel_points:
                    filtered[kpa][fname] = content
                elif not pt:
                    filtered[kpa][fname] = content

    if not filtered:
        st.error("❌ No data matches current selection.")
        return None

    st.session_state["_pressure_files"] = filtered
    total = sum(len(v) for v in filtered.values())
    st.success(f"📊 Ready: {len(filtered)} pressure level(s) · {total} files. Go to **Process** tab to run.")
    return filtered


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
