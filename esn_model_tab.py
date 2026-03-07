"""
ESN Model tab — Echo State Network for batoid-inspired soft finger control.

Forward model: Input = pressure u(t) at varying time; Output = measured force and derived
bending angle over time. Train on 9 pressure levels, predict force and bending angle.
Inverse use: Give target force and target bending angle → predict required pressure;
then apply that pressure to the finger and compare measured vs target (feedback propagation).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

from styles import section
from ui_helpers import render_inverse_prediction_section


# =========================
# Sequence building (aligned with compiled DataFrame)
# =========================
def _build_sequences_from_compiled(
    df: pd.DataFrame,
    pressure_col: str,
    time_col: str,
    ctx_cols: List[str],
    target_cols: List[str],
    pressure_round_decimals: int,
    min_len: int,
) -> Dict[Tuple, Dict[str, np.ndarray]]:
    df = df.dropna(subset=[pressure_col] + target_cols).copy()
    df[pressure_col] = pd.to_numeric(df[pressure_col], errors="coerce")
    for t in target_cols:
        df[t] = pd.to_numeric(df[t], errors="coerce")
    df = df.dropna(subset=[pressure_col] + target_cols).copy()
    df["_P_grp"] = df[pressure_col].round(pressure_round_decimals)

    seqs = {}
    for key, g in df.groupby(["_P_grp"]):
        g = g.copy()
        if time_col in g.columns and pd.api.types.is_numeric_dtype(g[time_col]):
            g = g.sort_values(time_col)
            t_arr = g[time_col].to_numpy(dtype=np.float32)
        else:
            g = g.sort_index()
            t_arr = np.arange(len(g), dtype=np.float32)

        if len(g) < min_len:
            continue

        ctx = np.zeros(0, dtype=np.float32)
        if ctx_cols:
            existing = [c for c in ctx_cols if c in g.columns]
            if existing:
                ctx = g.iloc[0][existing].fillna(0).to_numpy(dtype=np.float32)

        Pseq = g["_P_grp"].to_numpy(dtype=np.float32).reshape(-1, 1)
        yseq = g[target_cols].to_numpy(dtype=np.float32)
        seqs[key] = {"time": t_arr, "pressure": Pseq, "ctx": ctx, "y": yseq}

    return seqs


def _key_to_pressure(k: Any) -> float:
    return float(k[0]) if isinstance(k, tuple) else float(k)


def _sanitize_for_float32(arr: np.ndarray, clip_max: float = 1e10) -> np.ndarray:
    """Replace inf/nan and clip to safe range so sklearn/scipy float32 ops don't raise."""
    arr = np.asarray(arr, dtype=np.float64)
    finite_max = np.finfo(np.float32).max * 0.5
    cap = min(clip_max, finite_max)
    out = np.nan_to_num(arr, nan=0.0, posinf=cap, neginf=-cap)
    out = np.clip(out, -cap, cap).astype(np.float32)
    return out


def _make_one_step_pairs(
    pressure_seq: np.ndarray,
    ctx: np.ndarray,
    y: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    T, O = y.shape
    ctx_rep = np.repeat(ctx.reshape(1, -1), T, axis=0) if ctx.size else np.zeros((T, 0), dtype=np.float32)
    y_prev = np.vstack([np.zeros((1, O), dtype=np.float32), y[:-1]])
    U = np.concatenate([pressure_seq, ctx_rep, y_prev], axis=1).astype(np.float32)
    Y = y.astype(np.float32)
    return U, Y


# =========================
# ESN implementation
# =========================
class EchoStateNetwork:
    """
    ESN with leaky integrator. Readout: Ridge (closed-form) or sklearn regressor.
    State: x(t) = (1-a)*x(t-1) + a*tanh( Win*u(t) + W*x(t-1) + b )
    """
    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        reservoir_size: int = 500,
        spectral_radius: float = 0.9,
        sparsity: float = 0.1,
        leak_rate: float = 0.3,
        input_scale: float = 0.5,
        ridge_lambda: float = 1e-4,
        readout_type: str = "Ridge",
        seed: int = 42,
    ):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.N = reservoir_size
        self.spectral_radius = spectral_radius
        self.sparsity = sparsity
        self.leak = leak_rate
        self.input_scale = input_scale
        self.ridge = ridge_lambda
        self.readout_type = readout_type

        rng = np.random.RandomState(seed)

        self.Win = (rng.uniform(-1, 1, size=(self.N, self.input_dim)) * self.input_scale).astype(np.float32)

        W = rng.uniform(-1, 1, size=(self.N, self.N)).astype(np.float32)
        mask = rng.rand(self.N, self.N) < self.sparsity
        W *= mask.astype(np.float32)
        eigvals = np.linalg.eigvals(W)
        rad = np.max(np.abs(eigvals)) if eigvals.size > 0 else 1.0
        if rad == 0:
            rad = 1.0
        W *= (self.spectral_radius / rad)
        self.W = W.astype(np.float32)
        self.b = rng.uniform(-0.1, 0.1, size=(self.N,)).astype(np.float32)

        self.Wout = None
        self._readout_sklearn = None

    def _update(self, x_prev: np.ndarray, u_t: np.ndarray) -> np.ndarray:
        pre = self.Win @ u_t + self.W @ x_prev + self.b
        x_new = (1.0 - self.leak) * x_prev + self.leak * np.tanh(pre)
        return x_new.astype(np.float32)

    def fit(self, U_list: List[np.ndarray], Y_list: List[np.ndarray], washout: int = 30) -> None:
        Z_collect = []
        Y_collect = []

        for U, Y in zip(U_list, Y_list):
            T = U.shape[0]
            x = np.zeros((self.N,), dtype=np.float32)
            for t in range(T):
                x = self._update(x, U[t])
                if t >= washout:
                    z = np.concatenate([[1.0], U[t], x], axis=0)
                    Z_collect.append(z)
                    Y_collect.append(Y[t])

        Z = np.stack(Z_collect, axis=1).T  # (M, D)
        Y_arr = np.stack(Y_collect, axis=0)  # (M, output_dim)

        if self.readout_type == "Ridge":
            # Closed-form: Wout = Y^T Z (Z^T Z + λI)^-1
            D = Z.shape[1]
            ZtZ = Z.T @ Z
            reg = self.ridge * np.eye(D, dtype=np.float32)
            inv = np.linalg.inv(ZtZ + reg)
            self.Wout = (Y_arr.T @ Z) @ inv
            self.Wout = self.Wout.astype(np.float32)
            self._readout_models = None
        else:
            from sklearn.linear_model import LinearRegression, Ridge, BayesianRidge, ElasticNet
            self.Wout = None
            self._readout_models = []
            for j in range(self.output_dim):
                if self.readout_type == "Linear Regression":
                    m = LinearRegression()
                elif self.readout_type == "Ridge (sklearn)":
                    m = Ridge(alpha=self.ridge)
                elif self.readout_type == "Bayesian Ridge":
                    m = BayesianRidge()
                elif self.readout_type == "ElasticNet":
                    m = ElasticNet(alpha=0.01, l1_ratio=0.5)
                else:
                    m = Ridge(alpha=self.ridge)
                m.fit(Z, Y_arr[:, j])
                self._readout_models.append(m)

    def step(self, x_prev: np.ndarray, u_t: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        x_new = self._update(x_prev, u_t)
        z = np.concatenate([[1.0], u_t, x_new], axis=0)
        if self.Wout is not None:
            y = (self.Wout @ z).astype(np.float32)
        else:
            z_2d = z.reshape(1, -1)
            y = np.array([m.predict(z_2d)[0] for m in (self._readout_models or [])], dtype=np.float32)
        return x_new, y


def _rollout_sequence(
    esn: EchoStateNetwork,
    seq: Dict[str, np.ndarray],
    feature_scaler: Any,
    target_scaler: Any,
    warm_start_steps: int = 1,
) -> np.ndarray:
    P = seq["pressure"]
    ctx = seq["ctx"]
    y_true = seq["y"]
    T, O = y_true.shape
    y_pred = np.zeros_like(y_true, dtype=np.float32)
    warm = min(max(1, warm_start_steps), T)
    y_pred[:warm] = y_true[:warm]

    x_state = np.zeros((esn.N,), dtype=np.float32)
    for t in range(warm):
        u_t = np.concatenate([
            P[t].reshape(-1), ctx,
            y_pred[t - 1] if t > 0 else np.zeros((O,), dtype=np.float32),
        ], axis=0)
        u_t = _sanitize_for_float32(u_t)
        u_t_s = feature_scaler.transform(u_t.reshape(1, -1))[0].astype(np.float32)
        x_state, _ = esn.step(x_state, u_t_s)

    for t in range(warm, T):
        u_t = np.concatenate([P[t].reshape(-1), ctx, y_pred[t - 1]], axis=0)
        u_t = _sanitize_for_float32(u_t)
        u_t_s = feature_scaler.transform(u_t.reshape(1, -1))[0].astype(np.float32)
        x_state, y_hat_s = esn.step(x_state, u_t_s)
        y_hat = target_scaler.inverse_transform(y_hat_s.reshape(1, -1))[0]
        y_pred[t] = _sanitize_for_float32(y_hat)

    return y_pred


# =========================
# ESN architecture diagram
# =========================
def _draw_esn_architecture(
    input_dim: int,
    reservoir_size: int,
    output_dim: int,
    readout_type: str,
) -> Optional[object]:
    """Draw ESN architecture diagram. Returns None if matplotlib/numpy fail to import."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.set_xlim(0, 6)
    ax.set_ylim(0, 2)
    ax.axis("off")

    colors = {
        "Input": ("#e3f2fd", "#1976d2"),
        "Reservoir": ("#fff3e0", "#e65100"),
        "Readout": ("#f3e5f5", "#7b1fa2"),
        "Output": ("#e8f5e9", "#2e7d32"),
    }

    def box(x: float, y: float, w: float, h: float, label: str, key: str):
        face, edge = colors.get(key, ("#fafafa", "#333"))
        rect = mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", facecolor=face, edgecolor=edge, linewidth=1.2)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=9)

    box(0.2, 0.6, 1.0, 0.8, f"Input\n(u)\ndim={input_dim}", "Input")
    box(1.8, 0.4, 1.6, 1.2, f"Reservoir\nN = {reservoir_size}\n(leaky tanh)", "Reservoir")
    box(4.0, 0.5, 1.2, 1.0, f"Readout\n{readout_type}", "Readout")
    box(5.4, 0.6, 0.5, 0.8, f"Output\n(y)\ndim={output_dim}", "Output")

    ay = 1.0
    ax.annotate("", xy=(1.7, ay), xytext=(1.2, ay), arrowprops=dict(arrowstyle="->", color="#1565c0", lw=2))
    ax.annotate("", xy=(3.95, ay), xytext=(3.5, ay), arrowprops=dict(arrowstyle="->", color="#1565c0", lw=2))
    ax.annotate("", xy=(5.35, ay), xytext=(5.25, ay), arrowprops=dict(arrowstyle="->", color="#1565c0", lw=2))

    ax.set_title("ESN (Echo State Network) architecture", fontsize=11)
    plt.tight_layout()
    return fig


# =========================
# Save ESN runs (like DL)
# =========================
ESN_RUNS_DIR = Path(__file__).resolve().parent / "esn_training_runs"


def _esn_run_basename(
    reservoir_size: int,
    readout_type: str,
    test_pressure: float,
    min_seq_len: int,
) -> str:
    import re
    s = f"ESN_N{reservoir_size}_{readout_type.replace(' ', '_')}_tp{test_pressure}_minlen{min_seq_len}"
    return re.sub(r"[^\w\-.]", "_", s)


def _get_next_run_path(dir_path: Path, basename: str, ext: str) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{basename}{ext}"
    if not path.exists():
        return path
    n = 2
    while True:
        path = dir_path / f"{basename}_{n}{ext}"
        if not path.exists():
            return path
        n += 1


# =========================
# Tab render
# =========================
def render_esn_model_tab(
    compiled: pd.DataFrame,
    summary: pd.DataFrame,
    pn: List[str],
    cfg: dict,
) -> None:
    section(
        "🌊",
        "teal",
        "ESN Model (Echo State Network)",
        "Forward: pressure u(t) → measured force & derived bending angle at varying time (train on 9 pressures). "
        "Inverse: target force & angle → predicted pressure; use on finger to validate (feedback propagation).",
    )

    df = compiled
    if df is None or len(df) < 10:
        st.info("Process data in the **Process** tab first to use the ESN model.")
        return
    if "Time" not in df.columns:
        st.warning("Compiled data must contain a **Time** column.")
        return

    pressure_col = "Pressure (kPa)" if "Pressure (kPa)" in df.columns else None
    if not pressure_col or df[pressure_col].nunique() < 2:
        st.warning("Need at least 2 pressure levels for train/test split.")
        return

    time_col = "Time"
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    input_candidates = [c for c in numeric_cols if c not in (time_col, pressure_col)]
    default_inputs = [c for c in ["Finger Length (mm)", "Finger Width (mm)", "Speed (m/s)"] if c in input_candidates]
    if not default_inputs and input_candidates:
        default_inputs = input_candidates[:3]

    angle_cols = [c for c in ["angle1", "angle2"] if c in df.columns]
    other_targets = [c for c in ["p8_disp", "Contact Force (N)", "Contact Area (mm²)", "Contact Arc Length (mm)", "Tip Stiffness (N/mm)", "Tip Work (N·mm)"] if c in df.columns]
    target_candidates = list(dict.fromkeys(angle_cols + other_targets))
    if not target_candidates:
        st.warning("No target columns found in data.")
        return

    # ---- 1) Data & validation ----
    st.markdown("#### 1. Data & validation")
    pressures = sorted(df[pressure_col].dropna().unique().astype(float).tolist())
    test_pressure = st.selectbox(
        "Hold-out pressure for validation",
        pressures,
        index=len(pressures) - 1 if len(pressures) > 1 else 0,
        key="esn_test_pressure",
    )
    target_cols_sel = st.multiselect(
        "Target(s) to predict",
        target_candidates,
        default=angle_cols[:1] if angle_cols else target_candidates[:1],
        key="esn_target_cols",
    )
    context_cols = st.multiselect(
        "Context / input features",
        input_candidates,
        default=default_inputs,
        key="esn_context_cols",
    )
    min_seq_len = st.number_input("Min sequence length", min_value=10, value=80, step=5, key="esn_min_seq_len")
    pressure_round_decimals = 3

    if not target_cols_sel:
        st.warning("Select at least one target.")
        return

    # ---- 2) ESN hyperparameters ----
    st.markdown("#### 2. Reservoir (ESN) parameters")
    col_esn, col_arch = st.columns([1, 1])
    with col_esn:
        reservoir_size = st.number_input("Reservoir size (N)", min_value=50, value=600, step=50, key="esn_reservoir_size")
        spectral_radius = st.number_input("Spectral radius", min_value=0.1, max_value=1.5, value=0.95, step=0.05, format="%.2f", key="esn_spectral_radius")
        sparsity = st.number_input("Sparsity (0–1)", min_value=0.01, max_value=1.0, value=0.10, step=0.01, format="%.2f", key="esn_sparsity")
        leak_rate = st.number_input("Leak rate", min_value=0.01, max_value=1.0, value=0.25, step=0.05, format="%.2f", key="esn_leak_rate")
        input_scale = st.number_input("Input scale", min_value=0.01, max_value=2.0, value=0.5, step=0.05, format="%.2f", key="esn_input_scale")
        ridge_lambda = st.number_input("Ridge λ (readout)", min_value=1e-8, value=1e-4, step=1e-5, format="%.0e", key="esn_ridge")
        washout = st.number_input("Washout steps", min_value=0, value=30, step=5, key="esn_washout")
        warm_start_steps = st.number_input("Warm-start steps (rollout)", min_value=1, value=1, step=1, key="esn_warm_start")
        seed = st.number_input("Random seed", min_value=0, value=42, step=1, key="esn_seed")

        readout_type = st.selectbox(
            "Readout regression model",
            ["Ridge", "Linear Regression", "Ridge (sklearn)", "Bayesian Ridge", "ElasticNet"],
            index=0,
            key="esn_readout_type",
            help="Ridge: closed-form. Others use sklearn (multi-output per target).",
        )

    with col_arch:
        ctx_len = len(context_cols) if context_cols else 0
        # input_dim = 1 (pressure) + ctx_len + len(target_cols_sel) (y_prev)
        input_dim = 1 + ctx_len + len(target_cols_sel)
        output_dim = len(target_cols_sel)
        arch_fig = _draw_esn_architecture(input_dim, reservoir_size, output_dim, readout_type)
        if arch_fig is not None:
            st.pyplot(arch_fig)
            import matplotlib.pyplot as plt
            plt.close(arch_fig)
        else:
            st.warning(
                "Architecture diagram could not be drawn (NumPy/matplotlib import error). "
                "Try: **pip install --upgrade numpy** then restart the app."
            )

    st.markdown("#### Train ESN")
    if st.button("▶ Train ESN model", type="primary", key="esn_train_btn"):
        with st.spinner("Building sequences and training ESN…"):
            _run_esn_training(
                df=df,
                pressure_col=pressure_col,
                time_col=time_col,
                context_cols=context_cols,
                target_cols=target_cols_sel,
                test_pressure=float(test_pressure),
                min_seq_len=int(min_seq_len),
                pressure_round_decimals=pressure_round_decimals,
                reservoir_size=int(reservoir_size),
                spectral_radius=float(spectral_radius),
                sparsity=float(sparsity),
                leak_rate=float(leak_rate),
                input_scale=float(input_scale),
                ridge_lambda=float(ridge_lambda),
                washout=int(washout),
                warm_start_steps=int(warm_start_steps),
                seed=int(seed),
                readout_type=readout_type,
            )

    if "_esn_metrics" in st.session_state:
        st.markdown("#### Test metrics")
        st.json(st.session_state["_esn_metrics"])
    if "_esn_pred_fig" in st.session_state:
        st.markdown("#### True vs predicted (first test sequence)")
        st.plotly_chart(st.session_state["_esn_pred_fig"], use_container_width=True)

    st.markdown("---")
    render_inverse_prediction_section(df, key_prefix="esn_inv")


def _run_esn_training(
    df: pd.DataFrame,
    pressure_col: str,
    time_col: str,
    context_cols: List[str],
    target_cols: List[str],
    test_pressure: float,
    min_seq_len: int,
    pressure_round_decimals: int,
    reservoir_size: int,
    spectral_radius: float,
    sparsity: float,
    leak_rate: float,
    input_scale: float,
    ridge_lambda: float,
    washout: int,
    warm_start_steps: int,
    seed: int,
    readout_type: str,
) -> None:
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

    np.random.seed(seed)

    seqs = _build_sequences_from_compiled(
        df=df,
        pressure_col=pressure_col,
        time_col=time_col,
        ctx_cols=context_cols or [],
        target_cols=target_cols,
        pressure_round_decimals=pressure_round_decimals,
        min_len=min_seq_len,
    )
    if not seqs:
        st.error("No valid sequences. Increase min sequence length or check columns.")
        return

    train_seqs = [s for k, s in seqs.items() if _key_to_pressure(k) != test_pressure]
    test_seqs = [s for k, s in seqs.items() if _key_to_pressure(k) == test_pressure]
    if not train_seqs or not test_seqs:
        st.error("Train or test split is empty.")
        return

    U_train_list = []
    Y_train_list = []
    for s in train_seqs:
        U, Y = _make_one_step_pairs(s["pressure"], s["ctx"], s["y"])
        U_train_list.append(U)
        Y_train_list.append(Y)

    U_all = np.concatenate(U_train_list, axis=0)
    Y_all = np.concatenate(Y_train_list, axis=0)
    U_all = _sanitize_for_float32(U_all)
    Y_all = _sanitize_for_float32(Y_all)
    feature_scaler = StandardScaler()
    target_scaler = StandardScaler()
    feature_scaler.fit(U_all)
    target_scaler.fit(Y_all)

    U_train_s = [feature_scaler.transform(_sanitize_for_float32(U)).astype(np.float32) for U in U_train_list]
    Y_train_s = [target_scaler.transform(_sanitize_for_float32(Y)).astype(np.float32) for Y in Y_train_list]

    input_dim = U_train_s[0].shape[1]
    output_dim = Y_train_s[0].shape[1]

    esn = EchoStateNetwork(
        input_dim=input_dim,
        output_dim=output_dim,
        reservoir_size=reservoir_size,
        spectral_radius=spectral_radius,
        sparsity=sparsity,
        leak_rate=leak_rate,
        input_scale=input_scale,
        ridge_lambda=ridge_lambda,
        readout_type=readout_type,
        seed=seed,
    )
    esn.fit(U_train_s, Y_train_s, washout=washout)

    all_true = []
    all_pred = []
    for s in test_seqs:
        y_pred = _rollout_sequence(esn, s, feature_scaler, target_scaler, warm_start_steps)
        all_true.append(s["y"])
        all_pred.append(y_pred)

    Y_true = np.concatenate(all_true, axis=0)
    Y_pred = np.concatenate(all_pred, axis=0)

    metrics = {}
    for j, name in enumerate(target_cols):
        metrics[name] = {
            "RMSE": float(np.sqrt(mean_squared_error(Y_true[:, j], Y_pred[:, j]))),
            "MAE": float(mean_absolute_error(Y_true[:, j], Y_pred[:, j])),
            "R2": float(r2_score(Y_true[:, j], Y_pred[:, j])),
        }

    st.session_state["_esn_metrics"] = {"test_pressure": test_pressure, "targets": target_cols, "metrics": metrics}

    s0 = test_seqs[0]
    t0 = s0["time"]
    y0_true = s0["y"]
    y0_pred = all_pred[0]
    import plotly.graph_objects as go
    fig = go.Figure()
    for j, name in enumerate(target_cols):
        fig.add_trace(go.Scatter(x=t0, y=y0_true[:, j], name=f"{name} (true)", mode="lines"))
        fig.add_trace(go.Scatter(x=t0, y=y0_pred[:, j], name=f"{name} (pred)", mode="lines", line=dict(dash="dash")))
    fig.update_layout(title=f"ESN True vs predicted (test pressure={test_pressure})", xaxis_title="Time", height=400)
    st.session_state["_esn_pred_fig"] = fig

    # Save run (like DL tab)
    try:
        ESN_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        base = _esn_run_basename(reservoir_size, readout_type, test_pressure, min_seq_len)
        mse_path = _get_next_run_path(ESN_RUNS_DIR, base, "_metrics.json")
        with open(mse_path, "w") as f:
            import json
            json.dump(st.session_state["_esn_metrics"], f, indent=2)
        pred_path = _get_next_run_path(ESN_RUNS_DIR, "pred_" + base, ".html")
        fig.write_html(str(pred_path))
        st.success(f"Training finished. **Saved:** metrics `{mse_path.name}`, prediction `{pred_path.name}` in `{ESN_RUNS_DIR}`.")
    except Exception as e:
        st.success("Training finished. See metrics and plot below.")
        st.warning(f"Could not save run: {e}")
