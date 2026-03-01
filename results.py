"""
Results module — charts, data tabs, export.
"""
from datetime import datetime

import plotly.express as px
import streamlit as st
from styles import section
from processing import to_excel_bytes


# ═══════════════════════════════════════════════════════════════════════════
# Chart helpers
# ═══════════════════════════════════════════════════════════════════════════
_CHART_COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
                 "#EC4899", "#06B6D4", "#84CC16", "#F97316", "#6366F1"]


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
        legend=dict(orientation="h", yanchor="top", y=-0.18,
                    font=dict(size=11)),
        plot_bgcolor="rgba(248,250,253,0.6)",
        xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
        yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
    )
    fig.update_traces(line=dict(width=2.5))
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# Results tabs  (data, charts, summary, export)
# ═══════════════════════════════════════════════════════════════════════════
def _results_tabs(compiled, summary, pn, cfg):
    tab_data, tab_charts, tab_summary, tab_export = st.tabs(
        ["📋 Data", "📈 Charts", "📊 Summary", "📥 Export"]
    )

    with tab_data:
        st.dataframe(compiled, use_container_width=True, height=420)

    with tab_charts:
        c1, c2 = st.columns(2)
        with c1:
            _angle_chart(compiled, "angle1", "Angle 1 — P7 › P1 › P8")
        with c2:
            _angle_chart(compiled, "angle2", "Angle 2 — P5 › P2 › P6")

        disp_cols = [c for c in compiled.columns if c.endswith("_disp")]
        if disp_cols:
            st.markdown("#### Displacement")
            sel = st.selectbox("Point", pn, key="disp_pt")
            dc = f"{sel}_disp"
            if dc in compiled.columns:
                fig = px.line(
                    compiled, x="Time", y=dc, color="Pressure (kPa)",
                    title=f"Displacement of {sel.upper()} over Time",
                    labels={dc: "Displacement (mm)"},
                    color_discrete_sequence=_CHART_COLORS,
                )
                fig.update_layout(
                    height=400, template="plotly_white",
                    font=dict(family="Inter, sans-serif", size=12),
                    title_font=dict(size=14, color="#1E293B"),
                    margin=dict(t=48, b=24, l=48, r=24),
                    legend=dict(orientation="h", yanchor="top", y=-0.18),
                    plot_bgcolor="rgba(248,250,253,0.6)",
                    xaxis=dict(gridcolor="#F1F5F9"), yaxis=dict(gridcolor="#F1F5F9"),
                )
                fig.update_traces(line=dict(width=2.5))
                st.plotly_chart(fig, use_container_width=True)

    with tab_summary:
        st.markdown("#### Max Displacement & Statistics per Pressure")
        st.dataframe(summary, use_container_width=True)

    with tab_export:
        st.markdown("#### Download Compiled Excel")
        try:
            # Cache Excel data/filename in session state to prevent UUID filenames
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
# Public API
# ═══════════════════════════════════════════════════════════════════════════
def render_results(compiled, summary, pn, cfg):
    """Render full analysis results section."""
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    with st.container(border=True):
        section("📊", "violet", "Analysis Results",
                "Processed data overview, charts and export")

        # ── Metric tiles ──
        np_ = compiled["Pressure (kPa)"].nunique()
        nr = len(compiled)
        npt = len(pn)
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

        _results_tabs(compiled, summary, pn, cfg)
