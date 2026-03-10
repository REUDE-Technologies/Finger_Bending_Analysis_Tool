"""
Results module — charts, data tabs, export.
"""
from datetime import datetime
import copy
import re

import numpy as np

# Compatibility shim for NumPy 2.x with libraries expecting np.unicode_
if not hasattr(np, "unicode_"):
    np.unicode_ = np.str_

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from styles import section
from processing import to_excel_bytes

# ── Chart capture for save/load sessions ──
SESSION_SAVED_CHARTS = "_saved_chart_html"  # mirror from ui_helpers


def _capture_chart(fig, chart_name: str):
    """Store a Plotly figure's HTML in session_state for later save."""
    try:
        if SESSION_SAVED_CHARTS not in st.session_state:
            st.session_state[SESSION_SAVED_CHARTS] = {}
        html = fig.to_html(full_html=False, include_plotlyjs="cdn")
        st.session_state[SESSION_SAVED_CHARTS][chart_name] = html
    except Exception:
        pass  # non-critical


# ═══════════════════════════════════════════════════════════════════════════
# Geometry helpers (arc length, area, force)
# ═══════════════════════════════════════════════════════════════════════════

# Finger outline connection order: shows actual finger shape with angle1 (P7-P1-P8) and angle2 (P5-P2-P6)
FINGER_OUTLINE_ORDER = ["p1", "p2", "p3", "p4", "p5", "p2", "p6", "p7", "p1", "p8"]


def _finger_draw_order(selected_pts, available_pts):
    """Return connection order for outline: FINGER_OUTLINE_ORDER restricted to selected points that exist."""
    return [p for p in FINGER_OUTLINE_ORDER if p in selected_pts and p in available_pts]


def _sorted_points(pn):
    """Sort point names like ['p1','p2',...] by numeric index."""
    def _num(name: str) -> int:
        m = re.search(r"(\d+)", name)
        return int(m.group(1)) if m else 0

    return sorted(pn, key=_num)


def _augment_with_geometry(compiled, pn, cfg):
    """
    Add contact arc length, surface area, force, and extra physics features
    into the compiled DataFrame, plus config columns (including Finger Width).
    """
    if compiled is None or len(compiled) == 0:
        return compiled
    cfg = cfg if isinstance(cfg, dict) else {}
    df = compiled.copy()

    # ── Inject config columns so they appear in Data preview ──
    for col_name, value in reversed(list(cfg.items())):
        if col_name not in df.columns:
            df.insert(0, col_name, value)

    # ── Contact arc, surface area, and force (using points 8→7→6→5→4) ──
    width_mm = float(cfg.get("Finger Width (mm)", 0) or 0.0)

    contact_order = ["p8", "p7", "p6", "p5", "p4"]
    contact_pts = [p for p in contact_order if f"{p}_x" in df.columns and f"{p}_y" in df.columns]

    if len(contact_pts) >= 2:
        segs = []
        for i in range(len(contact_pts) - 1):
            a, b = contact_pts[i], contact_pts[i + 1]
            ax, ay = f"{a}_x", f"{a}_y"
            bx, by = f"{b}_x", f"{b}_y"
            dx = df[bx] - df[ax]
            dy = df[by] - df[ay]
            segs.append(np.sqrt(dx**2 + dy**2))

        contact_arc = sum(segs)
        df["Contact Arc Length (mm)"] = contact_arc

    if width_mm > 0 and "Contact Arc Length (mm)" in df.columns:
        df["Finger Width (mm)"] = width_mm  # ensure numeric column
        df["Contact Area (mm²)"] = df["Contact Arc Length (mm)"] * width_mm

        if "Pressure (kPa)" in df.columns:
            # F [N] = P [Pa] * A [m²]; 1 kPa = 1000 Pa, 1 mm² = 1e-6 m²
            df["Contact Force (N)"] = (
                df["Pressure (kPa)"] * 1000.0 * df["Contact Area (mm²)"] / 1e6
            )

    # ── Extra physics features useful for ML ──
    tip_col = "p8_disp" if "p8_disp" in df.columns else None

    # Instantaneous stiffness (N/mm) at the tip
    if tip_col and "Contact Force (N)" in df.columns:
        disp = df[tip_col].replace(0, np.nan)
        df["Tip Stiffness (N/mm)"] = df["Contact Force (N)"] / disp

        # Approximate cumulative work at the tip per pressure level (N·mm)
        work_col = np.full(len(df), np.nan)
        for kpa, group in df.groupby("Pressure (kPa)"):
            idx = group.index
            d_disp = group[tip_col].diff().fillna(0.0)
            dW = group["Contact Force (N)"] * d_disp
            work_col[idx] = dW.cumsum()
        df["Tip Work (N·mm)"] = work_col

    # ── Speed = displacement / time (mm/s) per tracking point ──
    if "Time" in df.columns:
        time_safe = df["Time"].replace(0, np.nan)
        for col in list(df.columns):
            if col.endswith("_disp"):
                point = col.replace("_disp", "")
                df[f"{point}_speed"] = df[col] / time_safe

    return df


def _augment_summary(compiled, summary):
    """
    Enrich per-pressure summary with aggregates of the geometry/physics features
    that were added to the compiled DataFrame.
    """
    if compiled is None or len(compiled) == 0 or "Pressure (kPa)" not in compiled.columns:
        return summary if summary is not None else pd.DataFrame()
    # Map existing summary rows by pressure for easy updating
    base_by_kpa = {}
    if summary is not None and len(summary) > 0:
        for _, row in summary.iterrows():
            kpa = row.get("Pressure (kPa)")
            if kpa is not None:
                base_by_kpa[kpa] = dict(row)

    rows = []
    for kpa, group in compiled.groupby("Pressure (kPa)"):
        row = base_by_kpa.get(kpa, {"Pressure (kPa)": kpa})

        if "Contact Arc Length (mm)" in group.columns:
            row["Mean Contact Arc (mm)"] = float(group["Contact Arc Length (mm)"].mean())
        if "Contact Area (mm²)" in group.columns:
            row["Mean Contact Area (mm²)"] = float(group["Contact Area (mm²)"].mean())
        if "Contact Force (N)" in group.columns:
            row["Max Contact Force (N)"] = float(group["Contact Force (N)"].max())
        if "Tip Stiffness (N/mm)" in group.columns:
            row["Mean Tip Stiffness (N/mm)"] = float(
                group["Tip Stiffness (N/mm)"].replace([np.inf, -np.inf], np.nan).mean()
            )
        if "Tip Work (N·mm)" in group.columns:
            tw = group["Tip Work (N·mm)"].dropna()
            if not tw.empty:
                row["Final Tip Work (N·mm)"] = float(tw.iloc[-1])

        rows.append(row)

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Chart helpers
# ═══════════════════════════════════════════════════════════════════════════
_CHART_COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
                 "#EC4899", "#06B6D4", "#84CC16", "#F97316", "#6366F1"]
# Black bold font for all graph axes, ticks, and legends
_FONT_AXIS_TITLE = dict(color="black", family="Arial Black", size=12)
_FONT_TICKS = dict(color="black", family="Arial Black", size=11)
_FONT_LEGEND = dict(color="black", family="Arial Black", size=11)


def _angle_chart(df, col, title):
    if col not in df.columns:
        return
    fig = px.line(
        df, x="Time", y=col, color="Pressure (kPa)",
        title=title, labels={col: "Angle (°)"},
        color_discrete_sequence=_CHART_COLORS,
    )
    fig.update_layout(
        height=400, template="plotly_white",
        font=dict(family="Inter, sans-serif", size=12),
        title_font=dict(size=14, color="#1E293B"),
        margin=dict(t=48, b=24, l=48, r=24),
        legend=dict(orientation="h", yanchor="top", y=-0.18, font=_FONT_LEGEND),
        plot_bgcolor="rgba(248,250,253,0.6)",
        xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
        yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
    )
    fig.update_traces(line=dict(width=2.5))
    _capture_chart(fig, f"{col}_line")
    st.plotly_chart(fig, use_container_width=True)


def _bar_chart_by_pressure(compiled, col, title, y_label, stat_key_prefix):
    """
    Bar chart: one bar per pressure level, height = selected stat (min/max/mean) of col.
    Renders a selectbox to choose Minimum, Maximum, or Mean; then the bar chart.
    """
    if col not in compiled.columns or "Pressure (kPa)" not in compiled.columns:
        return
    agg = compiled.groupby("Pressure (kPa)")[col].agg(["min", "max", "mean"]).reset_index()
    if isinstance(agg.columns, pd.MultiIndex):
        agg.columns = ["Pressure (kPa)", "min", "max", "mean"]
    pressures = agg["Pressure (kPa)"].astype(int).astype(str) + " kPa"
    stat_choice = st.selectbox(
        "Statistic",
        ["Minimum", "Maximum", "Mean"],
        key=f"{stat_key_prefix}_stat",
    )
    stat_map = {"Minimum": "min", "Maximum": "max", "Mean": "mean"}
    stat_col = stat_map[stat_choice]
    vals = agg[stat_col].values
    n_bars = len(pressures)
    colors = (_CHART_COLORS * (n_bars // len(_CHART_COLORS) + 1))[:n_bars]
    fig = go.Figure(data=[go.Bar(x=pressures, y=vals, marker_color=colors)])
    fig.update_layout(
        title=f"{title} — {stat_choice} by pressure",
        xaxis_title="Pressure",
        yaxis_title=y_label,
        height=400,
        template="plotly_white",
        font=dict(family="Inter, sans-serif", size=12),
        title_font=dict(size=14, color="#1E293B"),
        margin=dict(t=48, b=24, l=48, r=24),
        plot_bgcolor="rgba(248,250,253,0.6)",
        xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
        yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
        showlegend=False,
    )
    _capture_chart(fig, f"{stat_key_prefix}_{stat_col}")
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# Results tabs  (data, charts, summary, export)
# ═══════════════════════════════════════════════════════════════════════════
_RESULTS_TAB_LABELS = ["📋 Data", "📈 Charts", "📊 Summary", "📥 Export"]


def _results_tabs(compiled, summary, pn, cfg):
    # Persist selected tab in session state so it doesn't reset to Data when a chart widget triggers rerun
    default_tab = st.session_state.get("_results_tab_radio", _RESULTS_TAB_LABELS[0])
    if default_tab not in _RESULTS_TAB_LABELS:
        default_tab = _RESULTS_TAB_LABELS[0]
    tab_idx = _RESULTS_TAB_LABELS.index(default_tab)
    tab_choice = st.radio(
        "View",
        options=_RESULTS_TAB_LABELS,
        index=tab_idx,
        key="_results_tab_radio",
        horizontal=True,
        label_visibility="collapsed",
    )

    if tab_choice == "📋 Data":
        st.dataframe(compiled, use_container_width=True, height=420)
        return

    if tab_choice == "📈 Charts":
        _render_charts_tab(compiled, summary, pn, cfg)
        return

    if tab_choice == "📊 Summary":
        st.markdown("#### Max Displacement & Statistics per Pressure")
        st.dataframe(summary, use_container_width=True)
        return

    if tab_choice == "📥 Export":
        _render_export_tab(compiled, summary, cfg)
        return


def _render_charts_tab(compiled, summary, pn, cfg):
    """Charts tab content (extracted so tab selection is stable)."""
    # ── Angle 1: line chart (left) + bar chart by pressure with min/max/mean (right) ──
    if "angle1" in compiled.columns:
        st.markdown("#### Angle 1 — P7 › P1 › P8")
        a1_left, a1_right = st.columns(2)
        with a1_left:
            _angle_chart(compiled, "angle1", "Angle 1 — P7 › P1 › P8")
        with a1_right:
            _bar_chart_by_pressure(
                compiled, "angle1", "Angle 1", "Angle (°)", "angle1_bar"
            )

    # ── Angle 2: line chart (left) + bar chart by pressure with min/max/mean (right) ──
    if "angle2" in compiled.columns:
        st.markdown("#### Angle 2 — P5 › P2 › P6")
        a2_left, a2_right = st.columns(2)
        with a2_left:
            _angle_chart(compiled, "angle2", "Angle 2 — P5 › P2 › P6")
        with a2_right:
            _bar_chart_by_pressure(
                compiled, "angle2", "Angle 2", "Angle (°)", "angle2_bar"
            )

    # ── Finger shape (x, y) at selected times: add/remove times, then points & pressure ──
    pn_xy = [p for p in pn if f"{p}_x" in compiled.columns and f"{p}_y" in compiled.columns]
    if pn_xy and "Time" in compiled.columns:
        st.markdown("#### Finger shape (x, y) at time")
        st.caption("Add times (s) with + to see deformation at multiple moments. Points connected in finger order. Visualize deformation at selected pressure, point and time.")
        times_available = np.sort(compiled["Time"].dropna().unique())
        if len(times_available) > 0:
            t_min, t_max = float(times_available.min()), float(times_available.max())
            if "_finger_shape_times" not in st.session_state:
                mid = times_available[len(times_available) // 2]
                st.session_state["_finger_shape_times"] = [float(mid)]

            default_pts = [p for p in FINGER_OUTLINE_ORDER if p in pn_xy]
            default_pts = list(dict.fromkeys(default_pts)) or pn_xy
            selected_pts = st.multiselect(
                "Points to include (connected in finger order)",
                options=pn_xy,
                default=default_pts,
                format_func=lambda p: p.upper(),
                key="finger_shape_points",
            )
            draw_order = _finger_draw_order(selected_pts, set(pn_xy))

            pressures_all = []
            if "Pressure (kPa)" in compiled.columns:
                pressures_all = sorted(compiled["Pressure (kPa)"].dropna().unique().tolist())
            # Persist pressure selection in session state so it isn't overwritten by default on rerun
            if "_finger_shape_pressure_sel" not in st.session_state:
                st.session_state["_finger_shape_pressure_sel"] = pressures_all[:1] if pressures_all else []
            selected_pressures = st.multiselect(
                "Pressure (kPa) at this time — select one or more to compare",
                options=pressures_all,
                default=st.session_state["_finger_shape_pressure_sel"],
                key="finger_shape_pressure",
            )
            st.session_state["_finger_shape_pressure_sel"] = selected_pressures

            # Time range for selected pressure(s) so user can add times within valid limits
            pressures_to_plot = st.session_state["_finger_shape_pressure_sel"]
            if pressures_to_plot and "Pressure (kPa)" in compiled.columns:
                sub = compiled[compiled["Pressure (kPa)"].isin(pressures_to_plot)]
                t_min_sel = float(sub["Time"].min()) if len(sub) else t_min
                t_max_sel = float(sub["Time"].max()) if len(sub) else t_max
                st.info(f"**Time range for selected pressure(s):** {t_min_sel:.2f} s – {t_max_sel:.2f} s (add times within this range).")
            else:
                t_min_sel, t_max_sel = t_min, t_max

            col_time_a, col_time_b = st.columns([3, 1])
            with col_time_a:
                new_time = st.number_input(
                    "Time (s)",
                    min_value=t_min_sel,
                    max_value=t_max_sel,
                    value=st.session_state["_finger_shape_times"][-1] if st.session_state["_finger_shape_times"] else t_min_sel,
                    step=0.01,
                    format="%.4f",
                    key="finger_shape_time_input",
                )
            with col_time_b:
                st.markdown("<br>", unsafe_allow_html=True)  # align with input
                if st.button("➕ Add time", key="finger_shape_add_time"):
                    st.session_state["_finger_shape_times"] = list(st.session_state["_finger_shape_times"]) + [float(new_time)]
                    st.rerun()
            # Show list of selected times with "-" to remove each
            sel_times = st.session_state["_finger_shape_times"]
            if sel_times:
                n_display = min(12, len(sel_times))
                cols = st.columns(n_display + 1)
                for i in range(n_display):
                    with cols[i]:
                        t = sel_times[i]
                        if st.button(f"− {t:.2f}s", key=f"finger_remove_t_{i}"):
                            st.session_state["_finger_shape_times"] = [x for j, x in enumerate(sel_times) if j != i]
                            st.rerun()
                if len(sel_times) > n_display:
                    with cols[n_display]:
                        st.caption(f"+{len(sel_times) - n_display} more")
            else:
                st.caption("No times added yet. Enter a time above and click **+ Add time**.")

            if not draw_order:
                st.warning("Select at least one point to plot.")
            elif not sel_times:
                st.warning("Add at least one time (use the + Add time button).")
            elif not selected_pressures and "Pressure (kPa)" in compiled.columns:
                st.warning("Select at least one pressure to plot.")
            else:
                # Use persisted selection so plot exactly matches what user selected (avoids rerun/default glitch)
                pressures_to_plot = st.session_state["_finger_shape_pressure_sel"]
                # Build (t_val, kpa) pairs and sort by time so legend appears in ascending time order
                pairs = []
                for t_val in sel_times:
                    for kpa in (pressures_to_plot if pressures_to_plot else [None]):
                        pairs.append((t_val, kpa))
                pairs.sort(key=lambda p: (p[0], p[1] or 0))
                # Build figure: one trace per (time, pressure); find closest row for each (t, kpa)
                fig_finger = go.Figure()
                colors = ["#1B6CA8", "#059669", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#65A30D", "#4F46E5", "#0D9488", "#A855F7"]
                for trace_idx, (t_val, kpa) in enumerate(pairs):
                    if kpa is not None:
                        subset = compiled[compiled["Pressure (kPa)"] == kpa]
                    else:
                        subset = compiled
                    if len(subset) == 0:
                        continue
                    # Row with Time closest to t_val
                    idx = (subset["Time"].astype(float) - t_val).abs().idxmin()
                    row = subset.loc[idx]
                    xs = [float(row[f"{p}_x"]) for p in draw_order]
                    ys = [float(row[f"{p}_y"]) for p in draw_order]
                    c = colors[trace_idx % len(colors)]
                    label = f"{int(kpa)} kPa, t={t_val:.2f}s" if kpa is not None else f"t={t_val:.2f}s"
                    fig_finger.add_trace(
                        go.Scatter(
                            x=xs,
                            y=ys,
                            mode="lines+markers",
                            name=label,
                            line=dict(color=c, width=2),
                            marker=dict(size=6, color=c, line=dict(width=1, color="white")),
                        )
                    )
                fig_finger.update_layout(
                    title="Finger outline — deformation at selected times and pressures",
                    xaxis_title="x (mm)",
                    yaxis_title="y (mm)",
                    height=500,
                    template="plotly_white",
                    showlegend=True,
                    legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, font=_FONT_LEGEND),
                    font=dict(family="Inter, sans-serif", size=12),
                    title_font=dict(size=14, color="#1E293B"),
                    margin=dict(t=56, b=40, l=48, r=24),
                    plot_bgcolor="rgba(248,250,253,0.6)",
                    xaxis=dict(scaleanchor="y", scaleratio=1, title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS, gridcolor="#F1F5F9"),
                    yaxis=dict(title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS, gridcolor="#F1F5F9"),
                )
                st.plotly_chart(fig_finger, use_container_width=True)

    # ── Variable vs Time: line chart (left) + bar chart by pressure with min/max/mean (right) ──
    numeric_cols_for_var = [
        c for c in compiled.columns
        if np.issubdtype(compiled[c].dtype, np.number) and c not in ("Time",)
    ]
    if numeric_cols_for_var:
        st.markdown("#### Variable over Time & by Pressure")
        st.caption("Select points (optional filter for point-specific variables), then any numeric column to plot over time and by pressure.")
        selected_pts_var = st.multiselect(
            "Points (P1…P8)",
            options=pn,
            default=pn,
            format_func=lambda p: p.upper(),
            key="var_over_time_points",
        )
        # Variable list: all non–point columns plus columns for selected points only
        def _is_point_col(col):
            return any(col.startswith(px + "_") for px in pn)

        def _point_in_selected(col):
            return any(col.startswith(px + "_") for px in selected_pts_var) if selected_pts_var else True

        var_options = [
            c for c in numeric_cols_for_var
            if not _is_point_col(c) or _point_in_selected(c)
        ]
        if not var_options:
            var_options = numeric_cols_for_var
        variable_col = st.selectbox(
            "Variable",
            options=var_options,
            key="disp_or_speed_var",
        )
        if variable_col in compiled.columns:
            disp_left, disp_right = st.columns(2)
            with disp_left:
                fig = px.line(
                    compiled, x="Time", y=variable_col, color="Pressure (kPa)" if "Pressure (kPa)" in compiled.columns else None,
                    title=f"{variable_col} over Time",
                    labels={variable_col: variable_col},
                    color_discrete_sequence=_CHART_COLORS,
                )
                fig.update_layout(
                    height=400, template="plotly_white",
                    font=dict(family="Inter, sans-serif", size=12),
                    title_font=dict(size=14, color="#1E293B"),
                    margin=dict(t=48, b=24, l=48, r=24),
                    legend=dict(orientation="h", yanchor="top", y=-0.18, font=_FONT_LEGEND),
                    plot_bgcolor="rgba(248,250,253,0.6)",
                    xaxis=dict(gridcolor="#F1F5F9", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
                    yaxis=dict(gridcolor="#F1F5F9", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
                )
                fig.update_traces(line=dict(width=2.5))
                _capture_chart(fig, f"variable_{re.sub(r'[^a-zA-Z0-9]', '_', variable_col)}_line")
                st.plotly_chart(fig, use_container_width=True)
            with disp_right:
                _bar_chart_by_pressure(
                    compiled, variable_col,
                    variable_col,
                    variable_col,
                    f"var_{re.sub(r'[^a-zA-Z0-9]', '_', variable_col)}_bar",
                )
                # Show overall min and max for the selected variable
                v_min = compiled[variable_col].min()
                v_max = compiled[variable_col].max()
                st.markdown(f"**Overall range:** Min = **{v_min:.4g}**, Max = **{v_max:.4g}**")

    # ── Total time consumed by point and pressure: max(Time) at each pressure ──
    if "Time" in compiled.columns and "Pressure (kPa)" in compiled.columns:
        st.markdown("#### Total Time by Point & Pressure")
        st.caption("Total time consumed = max of Time column at each pressure. Select points and pressures to compare.")
        pressures = sorted(compiled["Pressure (kPa)"].dropna().unique().tolist())
        selected_pts_time = st.multiselect(
            "Points (P1…P8)",
            options=pn,
            default=pn,
            format_func=lambda p: p.upper(),
            key="total_time_points",
        )
        selected_pressures = st.multiselect(
            "Pressure (kPa)",
            pressures,
            default=pressures[: min(5, len(pressures))],
            key="time_per_point_pressure",
        )
        if not selected_pressures:
            st.warning("Select at least one pressure.")
        elif not selected_pts_time:
            st.warning("Select at least one point.")
        else:
            pt_labels = [p.upper() for p in selected_pts_time]
            colors = ["#1B6CA8", "#059669", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#65A30D", "#4F46E5"]
            fig_time = go.Figure()
            for idx, kpa in enumerate(selected_pressures):
                subset = compiled[compiled["Pressure (kPa)"] == kpa]
                if len(subset) == 0:
                    continue
                total_time = float(subset["Time"].max())
                y_vals = [total_time] * len(selected_pts_time)
                c = colors[idx % len(colors)]
                fig_time.add_trace(
                    go.Bar(name=f"{int(kpa)} kPa", x=pt_labels, y=y_vals, marker_color=c)
                )
            fig_time.update_layout(
                barmode="group",
                title="Total time consumed (s) by point and pressure",
                xaxis_title="Point",
                yaxis_title="Time (s)",
                height=400,
                template="plotly_white",
                font=dict(family="Inter, sans-serif", size=12),
                title_font=dict(size=14, color="#1E293B"),
                margin=dict(t=48, b=24, l=48, r=24),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=_FONT_LEGEND),
                plot_bgcolor="rgba(248,250,253,0.6)",
                xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
                yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
            )
            _capture_chart(fig_time, "total_time_by_point_pressure")
            st.plotly_chart(fig_time, use_container_width=True)

    # ── Custom graphs: Independent configurable rows ──
    st.markdown("#### Custom Graphs")
    numeric_cols = [
        c for c in compiled.columns
        if np.issubdtype(compiled[c].dtype, np.number)
    ]
    if len(numeric_cols) >= 2:
        if "custom_graphs_count" not in st.session_state:
            st.session_state["custom_graphs_count"] = 1

        default_x = "Time" if "Time" in numeric_cols else numeric_cols[0]
        x_idx = numeric_cols.index(default_x) if default_x in numeric_cols else 0

        for i in range(st.session_state["custom_graphs_count"]):
            with st.container(border=True):
                sc1, sc2 = st.columns([0.3, 0.7])
                with sc1:
                    st.markdown(f"**Graph {i + 1} Settings**")
                    gx = st.selectbox("X axis", numeric_cols, index=x_idx, key=f"cg_x_{i}")
                    y_choices = [c for c in numeric_cols if c != gx]
                    y_def = y_choices[0] if len(y_choices) > 0 else numeric_cols[0]
                    gy = st.selectbox("Y axis", y_choices, index=0, key=f"cg_y_{i}")

                with sc2:
                    fig = px.line(
                        compiled, x=gx, y=gy,
                        color="Pressure (kPa)" if "Pressure (kPa)" in compiled.columns else None,
                        title=f"{gy} vs {gx}",
                        color_discrete_sequence=_CHART_COLORS,
                    )
                    fig.update_layout(
                        height=360, template="plotly_white",
                        font=dict(family="Inter, sans-serif", size=12),
                        title_font=dict(size=14, color="#1E293B"),
                        margin=dict(t=40, b=24, l=48, r=24),
                        legend=dict(orientation="h", yanchor="top", y=-0.18, font=_FONT_LEGEND),
                        plot_bgcolor="rgba(248,250,253,0.6)",
                        xaxis=dict(gridcolor="#F1F5F9", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
                        yaxis=dict(gridcolor="#F1F5F9", title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
                    )
                    fig.update_traces(line=dict(width=2.0))
                    st.plotly_chart(fig, use_container_width=True)

        bc1, bc2 = st.columns([1, 1])
        with bc1:
            if st.button("➕ Add graph", key="add_graph"):
                st.session_state["custom_graphs_count"] += 1
        with bc2:
            if st.button("➖ Remove last graph", key="remove_last_graph"):
                if st.session_state["custom_graphs_count"] > 1:
                    st.session_state["custom_graphs_count"] -= 1


def _render_export_tab(compiled, summary, cfg):
    """Export tab content (extracted so tab selection is stable)."""
    st.markdown("#### Download Compiled Excel")
    try:
        data_key = f"{len(compiled)}_{hash(tuple(compiled.columns))}"
        if st.session_state.get("_export_key") != data_key:
            ft = cfg.get("Finger", "finger") or "finger"
            bm = cfg.get("Body Material", "test") or "test"
            st.session_state["_export_fn"] = (
                f"{ft}_{bm}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            st.session_state["_export_xl"] = to_excel_bytes(compiled, cfg, summary)
            st.session_state["_export_key"] = data_key

        fn = st.session_state["_export_fn"]
        xl = st.session_state["_export_xl"]

        st.download_button(
            "📥  Download Excel Report",
            data=xl, file_name=fn,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_excel",
        )
        st.caption(
            f"File: `{fn}` · {len(compiled):,} rows · "
            f"{compiled['Pressure (kPa)'].nunique()} pressure levels"
        )
    except Exception as e:
        st.error(f"❌ Failed to generate Excel: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Inline ML model section — raw data, train on 9 pressures / validate on 1, time vs angle
# ═══════════════════════════════════════════════════════════════════════════
def _ml_section(compiled, summary):
    """ML using raw compiled data: train on 9 pressures, validate on 1, predict time vs angle for new pressure/material."""
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import Lasso, LinearRegression, Ridge
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        from sklearn.preprocessing import LabelEncoder, StandardScaler
    except Exception as e:
        st.info(
            "**ML section** requires scikit-learn and scipy. "
            "If you see an environment error (e.g. `numpy.core.multiarray` failed to import), "
            "the rest of the analysis — upload, process, export, charts — still works. "
            "To fix ML: run **pip install --upgrade numpy** and restart the app."
        )
        with st.expander("Technical error details"):
            st.code(str(e))
        return

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    section(
        "🤖",
        "blue",
        "ML Model — Raw Data",
        "Train on 9 pressure levels, validate on 1 held-out pressure; predict time vs angle for new pressure, finger length, material.",
    )

    # Use raw compiled data only
    df = compiled
    if df is None or len(df) < 10:
        st.info("Not enough raw data for ML. Process at least 10 rows (multiple pressures × time) first.")
        return

    if "Time" not in df.columns:
        st.warning("Raw data must contain a **Time** column. Process data from the Process tab.")
        return

    pressure_col = "Pressure (kPa)" if "Pressure (kPa)" in df.columns else None
    if not pressure_col or df[pressure_col].nunique() < 2:
        st.warning("Need at least 2 pressure levels in the data (e.g. 9 for training, 1 for validation).")
        return

    pressures = sorted(df[pressure_col].dropna().unique().astype(int).tolist())
    angle_cols = [c for c in ["angle1", "angle2"] if c in df.columns]
    if not angle_cols:
        st.warning("No angle1/angle2 columns in data. Process data that includes angle computation.")
        return

    with st.expander("Preview raw ML dataset", expanded=False):
        st.dataframe(df.head(30), use_container_width=True)
    st.caption(f"**Raw data:** {len(df)} rows · {len(pressures)} pressure levels · Use for time vs angle prediction.")

    # ── Hold-out pressure (validate on 1) ──
    st.markdown("#### 1. Validation setup")
    validation_pressure = st.selectbox(
        "Hold-out pressure for validation (train on the rest)",
        pressures,
        index=len(pressures) - 1 if len(pressures) > 1 else 0,
        key="ml_validation_pressure",
    )
    target_angles = st.multiselect(
        "Target angle(s)",
        angle_cols,
        default=angle_cols[:1] if angle_cols else [],
        key="ml_target_angle",
    )

    if not target_angles:
        st.warning("Select at least one target angle.")
        return

    train_df = df[df[pressure_col] != validation_pressure].copy()
    test_df = df[df[pressure_col] == validation_pressure].copy()
    n_train = len(train_df)
    n_test = len(test_df)

    if n_train < 5:
        st.warning("Too few training rows after holding out the selected pressure.")
        return
    if n_test < 2:
        st.warning("Too few validation rows for the held-out pressure.")
        return

    st.success(f"Train: **{n_train}** rows ({len(pressures) - 1} pressures) · Validate: **{n_test}** rows ({validation_pressure} kPa)")

    # ── Features: Time, Pressure, config, and new physics; right = Pearson correlation map ──
    st.markdown("#### 2. Features")
    exclude_targets = set(target_angles)

    def _is_numeric(col):
        try:
            return col not in exclude_targets and pd.api.types.is_numeric_dtype(df[col])
        except Exception:
            return False

    numeric_candidates = [c for c in df.columns if _is_numeric(c)]
    preferred = [
        c for c in [
            "Time", pressure_col, "Finger Length (mm)", "Finger Width (mm)", "Speed (m/s)",
            "Contact Arc Length (mm)", "Contact Area (mm²)", "Contact Force (N)",
            "Tip Stiffness (N/mm)", "Tip Work (N·mm)",
        ]
        if c in numeric_candidates
    ]
    other_num = [c for c in numeric_candidates if c not in preferred]
    default_num = preferred + [c for c in other_num if c not in (preferred + list(exclude_targets))][:5]

    cat_candidates = [c for c in df.columns if df[c].dtype == "object" or getattr(df[c].dtype, "name", "") == "category"]
    cat_candidates = [c for c in cat_candidates if c not in exclude_targets]

    col_feat, col_corr = st.columns([1, 1])
    with col_feat:
        selected_num = st.multiselect(
            "Numeric features (X)",
            numeric_candidates,
            default=default_num,
            key="ml_raw_num_feat",
        )
        selected_cat = st.multiselect(
            "Categorical features",
            cat_candidates,
            default=[c for c in ["Body Material", "Skin Material"] if c in cat_candidates],
            key="ml_raw_cat_feat",
        )
    with col_corr:
        feats_for_corr = [c for c in (selected_num if selected_num else []) if c in train_df.columns and pd.api.types.is_numeric_dtype(train_df[c])]
        if len(feats_for_corr) >= 2:
            st.caption("**Pearson correlation** (training data)")
            corr_df = train_df[feats_for_corr].dropna().corr()
            fig_corr = px.imshow(
                corr_df,
                text_auto=".2f",
                aspect="auto",
                color_continuous_scale="RdBu_r",
                zmin=-1,
                zmax=1,
                labels=dict(color="Correlation"),
            )
            fig_corr.update_layout(height=320, margin=dict(l=80, r=40, t=24, b=80), xaxis_tickangle=-45)
            st.plotly_chart(fig_corr, use_container_width=True)
        else:
            st.caption("Select **at least 2 numeric features** to show Pearson correlation map.")

        # Random Forest feature importance (top 10, descending) — same training data
        if len(feats_for_corr) >= 1 and target_angles:
            try:
                from sklearn.ensemble import RandomForestRegressor as _RF
                _t = target_angles[0]
                _data = train_df[feats_for_corr + [_t]].dropna()
                if len(_data) >= 10:
                    _X = _data[feats_for_corr].values
                    _y = _data[_t].values
                    _rf = _RF(n_estimators=100, max_depth=10, random_state=42)
                    _rf.fit(_X, _y)
                    _imp = _rf.feature_importances_
                    _order = np.argsort(_imp)[::-1]
                    _ranked_names = [feats_for_corr[i] for i in _order]
                    _ranked_imp = [_imp[i] for i in _order]
                    st.session_state["_ml_feature_importance_ranking"] = _ranked_names
                    top_n_show = min(10, len(_ranked_names))
                    st.caption(f"**Feature importance** (Random Forest, top {top_n_show} — target: {_t})")
                    _names_show = _ranked_names[:top_n_show][::-1]
                    _imp_show = _ranked_imp[:top_n_show][::-1]
                    fig_imp = go.Figure(
                        data=[go.Bar(
                            x=_imp_show,
                            y=_names_show,
                            orientation="h",
                            marker_color="#10B981",
                            width=0.7,
                            text=[f"{v:.3f}" for v in _imp_show],
                            textposition="outside",
                        )]
                    )
                    fig_imp.update_layout(
                        height=320,
                        margin=dict(l=140, r=60, t=24, b=40),
                        xaxis_title="Feature importance score",
                        yaxis_title="",
                        showlegend=False,
                        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                        bargap=0.25,
                    )
                    st.plotly_chart(fig_imp, use_container_width=True)
                else:
                    st.session_state["_ml_feature_importance_ranking"] = feats_for_corr
            except Exception:
                st.session_state["_ml_feature_importance_ranking"] = feats_for_corr
        else:
            if "_ml_feature_importance_ranking" in st.session_state and not feats_for_corr:
                del st.session_state["_ml_feature_importance_ranking"]

    if not selected_num or "Time" not in selected_num:
        st.info("Include **Time** and at least one other numeric feature.")
        return

    # Build X (shared) and y per target from train and test
    def _build_xy(_df, target_col):
        Xn = _df[selected_num].copy()
        for col in selected_cat:
            if col in _df.columns:
                Xn[col] = _df[col].astype(str).fillna("_nan_")
        return Xn, _df[target_col].values

    X_train_df, _ = _build_xy(train_df, target_angles[0])
    X_test_df, _ = _build_xy(test_df, target_angles[0])

    # Encode categoricals on train and map to test (X is same for all targets)
    encoders = {}
    X_train_enc = X_train_df[selected_num].copy()
    for col in selected_cat:
        if col not in X_train_df.columns:
            continue
        le = LabelEncoder()
        X_train_enc[col] = le.fit_transform(X_train_df[col])
        encoders[col] = le

    X_test_enc = X_test_df[selected_num].copy()
    for col in selected_cat:
        if col not in encoders or col not in X_test_df.columns:
            continue
        le = encoders[col]
        test_vals = X_test_df[col].astype(str).fillna("_nan_")
        test_vals = np.where(np.isin(test_vals, le.classes_), test_vals,
                             le.classes_[0] if len(le.classes_) else "_nan_")
        X_test_enc[col] = le.transform(test_vals)

    X_train = X_train_enc.values
    X_test = X_test_enc.values

    # Per-target y and masks (mask must be same for all targets so we use union of valid rows)
    y_train_by_target = {t: train_df[t].values for t in target_angles}
    y_test_by_target = {t: test_df[t].values for t in target_angles}
    mask_train = ~np.isnan(X_train).any(axis=1)
    mask_test = ~np.isnan(X_test).any(axis=1)
    for t in target_angles:
        mask_train &= ~np.isnan(y_train_by_target[t])
        mask_test &= ~np.isnan(y_test_by_target[t])
    X_train_m = X_train[mask_train]
    X_test_m = X_test[mask_test]
    y_train_by_target = {t: y_train_by_target[t][mask_train] for t in target_angles}
    y_test_by_target = {t: y_test_by_target[t][mask_test] for t in target_angles}

    if len(X_train_m) < 5 or len(X_test_m) < 1:
        st.warning("Too few rows after dropping NaNs.")
        return

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train_m)
    X_test_s = scaler.transform(X_test_m)

    feature_names = selected_num + [c for c in selected_cat if c in encoders]
    ranking = st.session_state.get("_ml_feature_importance_ranking", selected_num)

    # ── Model ──
    st.markdown("#### 3. Model")
    random_state = st.number_input("Random state", 0, 99999, 42, key="ml_raw_seed")
    feature_set_mode = st.radio(
        "Feature set",
        ["All selected features", "Top N features (by importance)"],
        index=0,
        key="ml_feature_set_mode",
        help="Use all selected features or only top N by Random Forest importance to check underfitting/overfitting.",
    )
    top_n = len(feature_names)
    if feature_set_mode == "Top N features (by importance)":
        top_n = st.number_input(
            "N (number of top features)",
            min_value=1,
            max_value=max(1, len(ranking)),
            value=min(10, max(1, len(ranking))),
            step=1,
            key="ml_top_n",
        )
    # Indices to keep: top N numeric (from ranking) + all categorical
    if feature_set_mode == "Top N features (by importance)" and ranking:
        top_n_set = set(ranking[:top_n])
        keep_indices = [i for i, f in enumerate(feature_names) if f in top_n_set or f in selected_cat]
        if keep_indices:
            X_train_s = X_train_s[:, keep_indices]
            X_test_s = X_test_s[:, keep_indices]
            feature_names = [feature_names[i] for i in keep_indices]
    models = {
        "Linear Regression": LinearRegression(),
        "Ridge": Ridge(alpha=1.0),
        "Lasso": Lasso(alpha=0.1),
        "Random Forest": RandomForestRegressor(n_estimators=100, max_depth=10, random_state=random_state),
        "Gradient Boosting": GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=random_state),
    }
    model_name = st.selectbox("Model", list(models.keys()), key="ml_raw_model")
    model_cls = models[model_name]

    train_pressures = sorted([p for p in pressures if p != validation_pressure])

    if st.button("▶ Train model (9 pressures) / Validate (1 pressure)", type="primary", key="ml_raw_train"):
        with st.spinner("Training..."):
            trained_models = {}
            y_pred_by_target = {}
            for t in target_angles:
                m = copy.deepcopy(model_cls)
                m.fit(X_train_s, y_train_by_target[t])
                y_pred_by_target[t] = m.predict(X_test_s)
                trained_models[t] = m
        st.session_state["_ml_raw_models"] = trained_models
        st.session_state["_ml_raw_scaler"] = scaler
        st.session_state["_ml_raw_encoders"] = encoders
        st.session_state["_ml_raw_feature_names"] = feature_names
        st.session_state["_ml_raw_y_test"] = y_test_by_target
        st.session_state["_ml_raw_y_pred_test"] = y_pred_by_target
        st.session_state["_ml_raw_test_time"] = test_df["Time"].values[mask_test] if "Time" in test_df.columns else np.arange(len(list(y_test_by_target.values())[0]))
        st.session_state["_ml_raw_targets"] = target_angles

        # Append to validation history for bar chart and true-vs-pred replay
        r2_first = float(r2_score(y_test_by_target[target_angles[0]], y_pred_by_target[target_angles[0]]))
        time_test_arr = test_df["Time"].values[mask_test] if "Time" in test_df.columns else np.arange(len(list(y_test_by_target.values())[0]))
        if "_ml_validation_history" not in st.session_state:
            st.session_state["_ml_validation_history"] = []
        st.session_state["_ml_validation_history"].append({
            "model_name": model_name,
            "validation_r2": r2_first,
            "train_pressures": train_pressures,
            "validation_pressure": validation_pressure,
            "target": target_angles[0],
            "time": time_test_arr.tolist(),
            "y_true": y_test_by_target[target_angles[0]].tolist(),
            "y_pred": y_pred_by_target[target_angles[0]].tolist(),
        })

    # ── Bar chart: X = ML model names, legend = validation pressure ──
    if "_ml_validation_history" in st.session_state and st.session_state["_ml_validation_history"]:
        hist = st.session_state["_ml_validation_history"]
        st.markdown("#### Validation R² by model (all runs)")
        model_names = sorted(set(e["model_name"] for e in hist))
        pressures_val = sorted(set(e["validation_pressure"] for e in hist))
        # One trace per validation pressure (legend)
        colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"]
        fig_bar = go.Figure()
        for idx, p in enumerate(pressures_val):
            y_vals = []
            for m in model_names:
                runs = [e for e in hist if e["model_name"] == m and e["validation_pressure"] == p]
                y_vals.append(runs[-1]["validation_r2"] if runs else None)
            color = colors[idx % len(colors)]
            fig_bar.add_trace(
                go.Bar(
                    name=f"Val: {p} kPa",
                    x=model_names,
                    y=y_vals,
                    text=[f"{v:.4f}" if v is not None else "" for v in y_vals],
                    textposition="outside",
                    marker_color=color,
                )
            )
        fig_bar.update_layout(
            title="Validation R² by model · Legend = held-out validation pressure",
            xaxis_title="ML model",
            yaxis_title="Validation R²",
            height=380,
            template="plotly_white",
            barmode="group",
            xaxis_tickangle=-25,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(b=100),
        )
        fig_bar.update_traces(hovertemplate="%{x}<br>Val: %{fullData.name}<br>R²: %{y:.4f}<extra></extra>")
        st.plotly_chart(fig_bar, use_container_width=True)

        # Select a run from the bar chart to show its true vs pred plot
        run_options = [f"{e['model_name']} — Val: {e['validation_pressure']} kPa (R²={e['validation_r2']:.4f})" for e in hist]
        default_idx = len(hist) - 1
        selected_run_label = st.selectbox(
            "Show true vs predicted for run (select from chart):",
            range(len(run_options)),
            format_func=lambda i: run_options[i],
            index=default_idx,
            key="ml_selected_run_idx",
        )
        selected_run = hist[selected_run_label]
        st.markdown("#### True vs predicted (selected run)")
        if "time" in selected_run and "y_true" in selected_run and "y_pred" in selected_run:
            fig_sel = go.Figure()
            t_axis = selected_run["time"]
            fig_sel.add_trace(go.Scatter(x=t_axis, y=selected_run["y_true"], mode="lines+markers", name="Actual", line=dict(color="#3B82F6", width=2)))
            fig_sel.add_trace(go.Scatter(x=t_axis, y=selected_run["y_pred"], mode="lines+markers", name="Predicted", line=dict(color="#EF4444", width=2, dash="dash")))
            fig_sel.update_layout(
                title=f"{selected_run['model_name']} — Validation at {selected_run['validation_pressure']} kPa ({selected_run['target']})",
                xaxis_title="Time",
                yaxis_title=selected_run["target"],
                height=360,
                template="plotly_white",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_sel, use_container_width=True)
        else:
            st.caption("Curve not stored for this run. Train the model again to see true vs predicted here.")

        with st.expander("Training / validation pressure details", expanded=False):
            for i, e in enumerate(hist):
                st.caption(f"**{e['model_name']}** (val: {e['validation_pressure']} kPa) — R² = {e['validation_r2']:.4f} ({e['target']}) · Train: {', '.join(map(str, e['train_pressures']))} kPa")

    # ── Validation metrics and Time vs Angle plot ──
    if "_ml_raw_models" in st.session_state:
        st.markdown("#### 4. Validation (held-out pressure)")
        y_test_by_t = st.session_state["_ml_raw_y_test"]
        y_pred_by_t = st.session_state["_ml_raw_y_pred_test"]
        time_test = st.session_state["_ml_raw_test_time"]
        targets = st.session_state["_ml_raw_targets"]

        for t in targets:
            y_test = y_test_by_t[t]
            y_pred = y_pred_by_t[t]
            st.caption(f"**{t}**")
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("Validation MAE", f"{mean_absolute_error(y_test, y_pred):.4f}")
            with m2:
                st.metric("Validation RMSE", f"{np.sqrt(mean_squared_error(y_test, y_pred)):.4f}")
            with m3:
                st.metric("Validation R²", f"{r2_score(y_test, y_pred):.4f}")

        fig_val = go.Figure()
        colors_actual = ["#3B82F6", "#10B981", "#8B5CF6", "#F59E0B"]
        colors_pred = ["#EF4444", "#EC4899", "#F97316", "#84CC16"]
        for i, t in enumerate(targets):
            c_a = colors_actual[i % len(colors_actual)]
            c_p = colors_pred[i % len(colors_pred)]
            fig_val.add_trace(
                go.Scatter(x=time_test, y=y_test_by_t[t], mode="lines+markers", name=f"{t} (Actual)", line=dict(color=c_a, width=2))
            )
            fig_val.add_trace(
                go.Scatter(x=time_test, y=y_pred_by_t[t], mode="lines+markers", name=f"{t} (Pred)", line=dict(color=c_p, width=2, dash="dash"))
            )
        fig_val.update_layout(
            title=f"Time vs angle(s) — Validation at {validation_pressure} kPa",
            xaxis_title="Time",
            yaxis_title="Angle (°)",
            height=380,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="top", y=1.08, font=_FONT_LEGEND),
            xaxis=dict(title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
            yaxis=dict(title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
        )
        st.plotly_chart(fig_val, use_container_width=True)

        # ── New prediction: new pressure, finger length, material → Time vs Angle ──
        st.markdown("#### 5. New prediction (Time vs Angle)")
        st.caption("Enter a new pressure, finger length, and material; predict angle over time.")

        # Defaults from compiled data (config columns)
        def _get_default(col, default=0):
            if col in df.columns:
                try:
                    return float(df[col].iloc[0])
                except Exception:
                    return default
            return default

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            new_pressure = st.number_input("New pressure (kPa)", min_value=0, value=validation_pressure, key="ml_new_pressure")
        with col_b:
            new_length = st.number_input("Finger length (mm)", min_value=0.0, value=_get_default("Finger Length (mm)", 0), key="ml_new_length")
        with col_c:
            new_width = st.number_input("Finger width (mm)", min_value=0.0, value=_get_default("Finger Width (mm)", 10), key="ml_new_width")

        col_d, col_e = st.columns(2)
        with col_d:
            materials_b = list(train_df["Body Material"].astype(str).unique()) if "Body Material" in train_df.columns else ["—"]
            new_body = st.selectbox("Body Material", materials_b, key="ml_new_body")
        with col_e:
            materials_s = list(train_df["Skin Material"].astype(str).unique()) if "Skin Material" in train_df.columns else ["—"]
            new_skin = st.selectbox("Skin Material", materials_s, key="ml_new_skin")

        speed_default = _get_default("Speed (m/s)", 0.0)
        new_speed = st.number_input("Speed (m/s)", min_value=0.0, value=speed_default, key="ml_new_speed")

        # Time grid: use same time frame and interval as training data (e.g. 0.03s)
        time_min = float(df["Time"].min())
        time_max = float(df["Time"].max())
        time_values = np.sort(df["Time"].dropna().unique())
        time_new = time_values.astype(float)
        if len(time_new) == 0:
            time_new = np.array([time_min])

        if st.button("Predict Time vs Angle", key="ml_predict_btn"):
            trained_models = st.session_state["_ml_raw_models"]
            scaler = st.session_state["_ml_raw_scaler"]
            encoders = st.session_state.get("_ml_raw_encoders", {})
            feature_names = st.session_state.get("_ml_raw_feature_names", [])
            targets = st.session_state["_ml_raw_targets"]

            # Build feature matrix for new prediction: one row per time point
            rows = []
            for t in time_new:
                row = {}
                for f in selected_num:
                    if f == "Time":
                        row[f] = t
                    elif f == pressure_col:
                        row[f] = new_pressure
                    elif f == "Finger Length (mm)":
                        row[f] = new_length
                    elif f == "Finger Width (mm)":
                        row[f] = new_width
                    elif f == "Speed (m/s)":
                        row[f] = new_speed
                    else:
                        row[f] = train_df[f].iloc[0] if f in train_df.columns else 0
                for c in selected_cat:
                    if c == "Body Material":
                        row[c] = new_body
                    elif c == "Skin Material":
                        row[c] = new_skin
                    else:
                        row[c] = train_df[c].iloc[0] if c in train_df.columns else ""
                rows.append(row)

            X_new_df = pd.DataFrame(rows)
            for col in selected_cat:
                if col in encoders:
                    vals = X_new_df[col].astype(str).fillna("_nan_")
                    vals = np.where(vals.isin(encoders[col].classes_), vals, encoders[col].classes_[0] if len(encoders[col].classes_) else "_nan_")
                    X_new_df[col] = encoders[col].transform(vals.astype(str))
            X_new_fill = X_new_df[feature_names].fillna(0)
            X_new = scaler.transform(X_new_fill.values)

            y_new_by_target = {}
            for t in targets:
                y_new_by_target[t] = trained_models[t].predict(X_new)
            st.session_state["_ml_new_time"] = time_new
            st.session_state["_ml_new_angle_by_target"] = y_new_by_target

        if "_ml_new_angle_by_target" in st.session_state:
            y_new_by_t = st.session_state["_ml_new_angle_by_target"]
            fig_new = go.Figure()
            colors = ["#059669", "#3B82F6", "#8B5CF6", "#F59E0B"]
            for i, t in enumerate(y_new_by_t):
                fig_new.add_trace(
                    go.Scatter(
                        x=st.session_state["_ml_new_time"],
                        y=y_new_by_t[t],
                        mode="lines",
                        name=f"{t} (Predicted)",
                        line=dict(color=colors[i % len(colors)], width=2),
                    )
                )
            fig_new.update_layout(
                title=f"Time vs angle(s) — New prediction ({new_pressure} kPa, L={new_length} mm, {new_body} / {new_skin})",
                xaxis_title="Time",
                yaxis_title="Angle (°)",
                height=380,
                template="plotly_white",
                legend=dict(font=_FONT_LEGEND),
                xaxis=dict(title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
                yaxis=dict(title_font=_FONT_AXIS_TITLE, tickfont=_FONT_TICKS),
            )
            st.plotly_chart(fig_new, use_container_width=True)
# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════
def render_results(compiled, summary, pn, cfg, include_ml=True):
    """Render full analysis results section. Set include_ml=False to omit ML block (e.g. when using a separate ML tab)."""
    try:
        cfg = cfg if isinstance(cfg, dict) else {}
        if compiled is None or len(compiled) == 0:
            st.warning("No compiled data to show. Run **Process & Compile** first.")
            return
        if "Pressure (kPa)" not in compiled.columns:
            st.warning("Compiled data is missing **Pressure (kPa)** column. Re-run processing.")
            return
    except Exception as e:
        st.error(f"Results error: {e}")
        return

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    try:
        # Add geometry / physics columns and config into compiled data
        compiled = _augment_with_geometry(compiled, pn, cfg)
        if compiled is None:
            return
        # Enrich summary with aggregates of new features
        summary = _augment_summary(compiled, summary)
    except Exception as e:
        st.error(f"Could not augment data: {e}")
        with st.expander("Details"):
            st.exception(e)
        return

    with st.container(border=True):
        section("📊", "violet", "Analysis Results",
                "Processed data overview, charts and export")

        # ── Metric tiles ──
        np_ = compiled["Pressure (kPa)"].nunique()
        nr = len(compiled)
        npt = len(pn) if pn is not None else 0
        aa = f"{compiled['angle1'].mean():.1f}°" if "angle1" in compiled.columns else "N/A"

        st.markdown(
            f'<div class="m-grid">'
            f'<div class="m-tile t-blue"><div class="v">{np_}</div><div class="l">Pressure Levels</div></div>'
            f'<div class="m-tile t-indigo"><div class="v">{nr:,}</div><div class="l">Total Rows</div></div>'
            f'<div class="m-tile t-emerald"><div class="v">{npt}</div><div class="l">Points Tracked</div></div>'
            f'<div class="m-tile t-amber"><div class="v">{aa}</div><div class="l">Avg Angle 1</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        _results_tabs(compiled, summary, pn or [], cfg)

    # ML model application section on the same page (optional)
    if include_ml:
        try:
            _ml_section(compiled, summary)
        except Exception as e:
            st.error(f"ML section error: {e}")
            with st.expander("Details"):
                st.exception(e)


def render_ml_section(compiled, summary):
    """Render only the ML model application block (e.g. for ML Model tab)."""
    try:
        _ml_section(compiled, summary)
    except Exception as e:
        st.error(f"ML Model tab error: {e}")
        with st.expander("Technical details"):
            st.exception(e)
