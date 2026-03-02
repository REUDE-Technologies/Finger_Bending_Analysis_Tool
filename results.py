"""
Results module — charts, data tabs, export.
"""
from datetime import datetime
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


# ═══════════════════════════════════════════════════════════════════════════
# Geometry helpers (arc length, area, force)
# ═══════════════════════════════════════════════════════════════════════════


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

    return df


def _augment_summary(compiled, summary):
    """
    Enrich per-pressure summary with aggregates of the geometry/physics features
    that were added to the compiled DataFrame.
    """
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

    return type(compiled)(rows)  # returns a DataFrame-like object


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

        # ── Maximum Displacement per Point Bar Chart ──
        if disp_cols:
            st.markdown("#### Maximum Displacement per Point")
            
            # Extract points we have disp for
            max_disps = []
            pt_names = []
            for dp in disp_cols:
                pt_prefix = dp.replace("_disp", "").upper()
                pt_names.append(pt_prefix)
                max_disps.append(compiled[dp].max())
                
            fig_bar = px.bar(
                x=pt_names, y=max_disps,
                labels={"x": "Tracking Point", "y": "Max Displacement (mm)"},
                title="Maximum Displacement by Point",
                color=pt_names, color_discrete_sequence=_CHART_COLORS
            )
            fig_bar.update_layout(
                height=350, template="plotly_white",
                font=dict(family="Inter, sans-serif", size=12),
                title_font=dict(size=14, color="#1E293B"),
                margin=dict(t=48, b=24, l=48, r=24),
                plot_bgcolor="rgba(248,250,253,0.6)",
                xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
                yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
                showlegend=False
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        # ── Custom graphs: Independent configurable rows ──
        st.markdown("#### Custom Graphs")
        numeric_cols = [
            c for c in compiled.columns
            if np.issubdtype(compiled[c].dtype, np.number)
        ]
        if len(numeric_cols) >= 2:
            if "custom_graphs_count" not in st.session_state:
                st.session_state["custom_graphs_count"] = 1
            
            bc1, bc2 = st.columns([1, 1])
            with bc1:
                if st.button("➕ Add graph", key="add_graph"):
                    st.session_state["custom_graphs_count"] += 1
            with bc2:
                if st.button("➖ Remove last graph", key="remove_last_graph"):
                    if st.session_state["custom_graphs_count"] > 1:
                        st.session_state["custom_graphs_count"] -= 1

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
                            legend=dict(orientation="h", yanchor="top", y=-0.18, font=dict(size=11)),
                            plot_bgcolor="rgba(248,250,253,0.6)",
                            xaxis=dict(gridcolor="#F1F5F9"), yaxis=dict(gridcolor="#F1F5F9"),
                        )
                        fig.update_traces(line=dict(width=2.0))
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
            "ML section requires scikit-learn + scipy. "
            f"Environment error: `{e}`. The rest of the analysis still works."
        )
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
    target_angle = st.selectbox("Target angle", angle_cols, key="ml_target_angle")

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

    # ── Features: Time, Pressure, config (finger length, width, speed, materials) ──
    st.markdown("#### 2. Features")
    numeric_candidates = [c for c in df.columns if c != target_angle and np.issubdtype(df[c].dtype, np.number)]
    preferred = [c for c in ["Time", pressure_col, "Finger Length (mm)", "Finger Width (mm)", "Speed (m/s)"]
                 if c in numeric_candidates]
    other_num = [c for c in numeric_candidates if c not in preferred]
    default_num = preferred + [c for c in other_num if c not in (preferred + [target_angle])][:5]

    cat_candidates = [c for c in df.columns if df[c].dtype == "object" or getattr(df[c].dtype, "name", "") == "category"]
    cat_candidates = [c for c in cat_candidates if c != target_angle]

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

    if not selected_num or "Time" not in selected_num:
        st.info("Include **Time** and at least one other numeric feature.")
        return

    # Build X, y from train and test
    def _build_xy(_df):
        Xn = _df[selected_num].copy()
        for col in selected_cat:
            if col in _df.columns:
                Xn[col] = _df[col].astype(str).fillna("_nan_")
        return Xn, _df[target_angle].values

    X_train_df, y_train = _build_xy(train_df)
    X_test_df, y_test = _build_xy(test_df)

    # Encode categoricals on train and map to test
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
        # Map unseen labels to first class
        test_vals = np.where(np.isin(test_vals, le.classes_), test_vals,
                             le.classes_[0] if len(le.classes_) else "_nan_")
        X_test_enc[col] = le.transform(test_vals)

    X_train = X_train_enc.values
    X_test = X_test_enc.values

    mask_train = ~(np.isnan(X_train).any(axis=1) | np.isnan(y_train))
    mask_test = ~(np.isnan(X_test).any(axis=1) | np.isnan(y_test))
    X_train, y_train = X_train[mask_train], y_train[mask_train]
    X_test, y_test = X_test[mask_test], y_test[mask_test]
    if len(X_train) < 5 or len(X_test) < 1:
        st.warning("Too few rows after dropping NaNs.")
        return

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    feature_names = selected_num + [c for c in selected_cat if c in encoders]

    # ── Model ──
    st.markdown("#### 3. Model")
    random_state = st.number_input("Random state", 0, 99999, 42, key="ml_raw_seed")
    models = {
        "Linear Regression": LinearRegression(),
        "Ridge": Ridge(alpha=1.0),
        "Lasso": Lasso(alpha=0.1),
        "Random Forest": RandomForestRegressor(n_estimators=100, max_depth=10, random_state=random_state),
        "Gradient Boosting": GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=random_state),
    }
    model_name = st.selectbox("Model", list(models.keys()), key="ml_raw_model")
    model = models[model_name]

    if st.button("▶ Train model (9 pressures) / Validate (1 pressure)", type="primary", key="ml_raw_train"):
        with st.spinner("Training..."):
            model.fit(X_train_s, y_train)
            y_pred_test = model.predict(X_test_s)
        st.session_state["_ml_raw_model"] = model
        st.session_state["_ml_raw_scaler"] = scaler
        st.session_state["_ml_raw_encoders"] = encoders
        st.session_state["_ml_raw_feature_names"] = feature_names
        st.session_state["_ml_raw_y_test"] = y_test
        st.session_state["_ml_raw_y_pred_test"] = y_pred_test
        st.session_state["_ml_raw_test_time"] = test_df["Time"].values[mask_test] if "Time" in test_df.columns else np.arange(len(y_test))
        st.session_state["_ml_raw_target"] = target_angle

    # ── Validation metrics and Time vs Angle plot ──
    if "_ml_raw_model" in st.session_state:
        st.markdown("#### 4. Validation (held-out pressure)")
        y_test = st.session_state["_ml_raw_y_test"]
        y_pred = st.session_state["_ml_raw_y_pred_test"]
        time_test = st.session_state["_ml_raw_test_time"]

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Validation MAE", f"{mean_absolute_error(y_test, y_pred):.4f}")
        with m2:
            st.metric("Validation RMSE", f"{np.sqrt(mean_squared_error(y_test, y_pred)):.4f}")
        with m3:
            st.metric("Validation R²", f"{r2_score(y_test, y_pred):.4f}")

        fig_val = go.Figure()
        fig_val.add_trace(
            go.Scatter(x=time_test, y=y_test, mode="lines+markers", name="Actual", line=dict(color="#3B82F6", width=2))
        )
        fig_val.add_trace(
            go.Scatter(x=time_test, y=y_pred, mode="lines+markers", name="Predicted", line=dict(color="#EF4444", width=2, dash="dash"))
        )
        fig_val.update_layout(
            title=f"Time vs {st.session_state['_ml_raw_target']} — Validation at {validation_pressure} kPa",
            xaxis_title="Time",
            yaxis_title=f"{st.session_state['_ml_raw_target']} (°)",
            height=380,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="top", y=1.08),
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

        # Time grid: use same range as training data
        time_min = float(df["Time"].min())
        time_max = float(df["Time"].max())
        n_points = min(200, max(50, len(df) // 5))
        time_new = np.linspace(time_min, time_max, n_points)

        if st.button("Predict Time vs Angle", key="ml_predict_btn"):
            model = st.session_state["_ml_raw_model"]
            scaler = st.session_state["_ml_raw_scaler"]
            encoders = st.session_state.get("_ml_raw_encoders", {})
            feature_names = st.session_state.get("_ml_raw_feature_names", [])

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
            X_new = scaler.transform(X_new_df[feature_names].values)
            y_new = model.predict(X_new)
            st.session_state["_ml_new_time"] = time_new
            st.session_state["_ml_new_angle"] = y_new

        if "_ml_new_angle" in st.session_state:
            fig_new = go.Figure()
            fig_new.add_trace(
                go.Scatter(
                    x=st.session_state["_ml_new_time"],
                    y=st.session_state["_ml_new_angle"],
                    mode="lines",
                    name="Predicted",
                    line=dict(color="#059669", width=2),
                )
            )
            fig_new.update_layout(
                title=f"Time vs {st.session_state['_ml_raw_target']} — New prediction ({new_pressure} kPa, L={new_length} mm, {new_body} / {new_skin})",
                xaxis_title="Time",
                yaxis_title=f"{st.session_state['_ml_raw_target']} (°)",
                height=380,
                template="plotly_white",
            )
            st.plotly_chart(fig_new, use_container_width=True)
# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════
def render_results(compiled, summary, pn, cfg, include_ml=True):
    """Render full analysis results section. Set include_ml=False to omit ML block (e.g. when using a separate ML tab)."""
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # Add geometry / physics columns and config into compiled data
    compiled = _augment_with_geometry(compiled, pn, cfg)
    # Enrich summary with aggregates of new features
    summary = _augment_summary(compiled, summary)

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

    # ML model application section on the same page (optional)
    if include_ml:
        _ml_section(compiled, summary)


def render_ml_section(compiled, summary):
    """Render only the ML model application block (e.g. for ML Model tab)."""
    _ml_section(compiled, summary)
