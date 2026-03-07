"""
DL Model tab — TCN (Temporal Convolutional Network) for batoid-inspired soft finger control.

Forward model: Input = pressure u(t) at varying time; Output = measured force and derived
bending angle over time. Train on 9 pressure levels, predict force and bending angle.
Inverse use: Give target force and target bending angle → predict required pressure;
then apply that pressure to the finger and compare measured vs target (feedback propagation).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

from styles import section
from ui_helpers import render_inverse_prediction_section

try:
    import torch
except ImportError:
    torch = None  # type: ignore


def _get_activation(name: str):
    if torch is None:
        raise ImportError("PyTorch is required. Install with: pip install torch")
    nn = torch.nn
    if name == "ReLU":
        return nn.ReLU
    if name == "Tanh":
        return nn.Tanh
    if name == "LeakyReLU":
        return nn.LeakyReLU
    if name == "GELU":
        return nn.GELU
    return nn.ReLU


def _ensure_torch():
    if torch is None:
        raise ImportError("PyTorch is required for the DL model. Install with: pip install torch")
    return torch


def _get_dl_classes():
    """Define and return TCNRegressor and WindowDataset when torch is available.
    Supports per-layer options (BN, dropout, pooling) and Conv1D or Conv2D."""
    _ensure_torch()
    nn = torch.nn

    class Chomp1d(nn.Module):
        def __init__(self, chomp: int):
            super().__init__()
            self.chomp = chomp
        def forward(self, x):
            return x[:, :, :-self.chomp] if self.chomp > 0 else x

    class TemporalBlock(nn.Module):
        def __init__(self, in_ch, out_ch, kernel_size=3, dilation=1, dropout=0.1, use_batch_norm=False, activation="ReLU"):
            super().__init__()
            pad = (kernel_size - 1) * dilation
            act = _get_activation(activation)()
            self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size, padding=pad, dilation=dilation)
            self.chomp1 = Chomp1d(pad)
            self.bn1 = nn.BatchNorm1d(out_ch) if use_batch_norm else nn.Identity()
            self.act1 = act
            self.drop1 = nn.Dropout(dropout)
            self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size, padding=pad, dilation=dilation)
            self.chomp2 = Chomp1d(pad)
            self.bn2 = nn.BatchNorm1d(out_ch) if use_batch_norm else nn.Identity()
            self.act2 = act
            self.drop2 = nn.Dropout(dropout)
            self.down = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else None
        def forward(self, x):
            out = self.drop1(self.act1(self.bn1(self.chomp1(self.conv1(x)))))
            out = self.drop2(self.act2(self.bn2(self.chomp2(self.conv2(out)))))
            res = x if self.down is None else self.down(x)
            return torch.nn.functional.relu(out + res)

    # Conv2D block: treats (B, C, T) as (B, C, T, 1), uses Conv2d(kernel_size, 1)
    class Chomp2d(nn.Module):
        def __init__(self, chomp: int):
            super().__init__()
            self.chomp = chomp
        def forward(self, x):
            if self.chomp <= 0:
                return x
            return x[:, :, :-self.chomp, :]

    class TemporalBlock2d(nn.Module):
        def __init__(self, in_ch, out_ch, kernel_size=3, dilation=1, dropout=0.1, use_batch_norm=False, activation="ReLU"):
            super().__init__()
            pad = (kernel_size - 1) * dilation
            act = _get_activation(activation)()
            self.conv1 = nn.Conv2d(in_ch, out_ch, (kernel_size, 1), padding=(pad, 0), dilation=(dilation, 1))
            self.chomp1 = Chomp2d(pad)
            self.bn1 = nn.BatchNorm2d(out_ch) if use_batch_norm else nn.Identity()
            self.act1 = act
            self.drop1 = nn.Dropout(dropout)
            self.conv2 = nn.Conv2d(out_ch, out_ch, (kernel_size, 1), padding=(pad, 0), dilation=(dilation, 1))
            self.chomp2 = Chomp2d(pad)
            self.bn2 = nn.BatchNorm2d(out_ch) if use_batch_norm else nn.Identity()
            self.act2 = act
            self.drop2 = nn.Dropout(dropout)
            self.down = nn.Conv2d(in_ch, out_ch, (1, 1)) if in_ch != out_ch else None
        def forward(self, x):
            out = self.drop1(self.act1(self.bn1(self.chomp1(self.conv1(x)))))
            out = self.drop2(self.act2(self.bn2(self.chomp2(self.conv2(out)))))
            res = x if self.down is None else self.down(x)
            return torch.nn.functional.relu(out + res)

    def _default_layer_opts(n: int) -> List[dict]:
        return [{"use_batch_norm": False, "use_dropout": True, "use_pooling": False} for _ in range(n)]

    class TemporalConvNet(nn.Module):
        def __init__(self, in_ch, channels, kernel_size=3, dropout=0.1, layer_opts=None, activation="ReLU", conv_type="Conv1D"):
            super().__init__()
            ch_list = list(channels)
            opts = layer_opts if layer_opts and len(layer_opts) == len(ch_list) else _default_layer_opts(len(ch_list))
            Block = TemporalBlock2d if conv_type == "Conv2D" else TemporalBlock
            layers = []
            ch_in = in_ch
            for i, ch_out in enumerate(ch_list):
                dil = 2 ** i
                o = opts[i] if i < len(opts) else {"use_batch_norm": False, "use_dropout": True, "use_pooling": False}
                d = dropout if o.get("use_dropout", True) else 0.0
                blk = Block(ch_in, ch_out, kernel_size, dil, d, use_batch_norm=o.get("use_batch_norm", False), activation=activation)
                layers.append(blk)
                if o.get("use_pooling", False):
                    layers.append(nn.MaxPool1d(2, stride=2) if conv_type == "Conv1D" else nn.MaxPool2d((2, 1), stride=(2, 1)))
                ch_in = ch_out
            self.net = nn.Sequential(*layers)
            self.conv_type = conv_type
        def forward(self, x):
            if self.conv_type == "Conv2D":
                x = x.unsqueeze(-1)
            for m in self.net:
                x = m(x)
            if self.conv_type == "Conv2D":
                x = x.squeeze(-1)
            return x

    class TCNRegressor(nn.Module):
        def __init__(self, in_features, out_features, channels=(64, 64, 128, 128), kernel_size=3, dropout=0.1, layer_opts=None, activation="ReLU", conv_type="Conv1D"):
            super().__init__()
            ch_list = list(channels)
            self.tcn = TemporalConvNet(in_features, ch_list, kernel_size, dropout, layer_opts=layer_opts, activation=activation, conv_type=conv_type)
            self.head = nn.Conv1d(ch_list[-1], out_features, kernel_size=1)
        def forward(self, x):
            x = x.transpose(1, 2)
            h = self.tcn(x)
            y = self.head(h)
            return y.transpose(1, 2)

    class WindowDataset(torch.utils.data.Dataset):
        def __init__(self, sequences, window_len, stride, feature_scaler, target_scaler, fit_scalers=False, ctx_len=0):
            super().__init__()
            self.samples = []
            self.ctx_len = ctx_len
            if fit_scalers:
                all_X, all_Y = [], []
                for s in sequences:
                    X_full, Y_full = self._make_full_xy(s)
                    all_X.append(X_full)
                    all_Y.append(Y_full)
                X_cat = np.concatenate(all_X, axis=0)
                Y_cat = np.concatenate(all_Y, axis=0)
                feature_scaler.fit(X_cat)
                target_scaler.fit(Y_cat)
            for s in sequences:
                X_full, Y_full = self._make_full_xy(s)
                X_full = feature_scaler.transform(X_full).astype(np.float32)
                Y_full = target_scaler.transform(Y_full).astype(np.float32)
                T = X_full.shape[0]
                for start in range(0, T - window_len + 1, stride):
                    end = start + window_len
                    self.samples.append((X_full[start:end], Y_full[start:end]))

        def _make_full_xy(self, s):
            Pseq = s["pressure"]
            ctx = s["ctx"].reshape(1, -1)
            y = s["y"]
            T = y.shape[0]
            ctx_rep = np.repeat(ctx, T, axis=0) if ctx.size else np.zeros((T, 0), dtype=np.float32)
            y_prev = np.vstack([np.zeros((1, y.shape[1]), dtype=np.float32), y[:-1]])
            X = np.concatenate([Pseq, ctx_rep, y_prev], axis=1)
            return X, y

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, idx):
            X, Y = self.samples[idx]
            return torch.from_numpy(X), torch.from_numpy(Y)

    return TCNRegressor, WindowDataset


# =========================
# Data prep from compiled DataFrame
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

    group_cols = ["_P_grp"]
    seqs = {}
    for key, g in df.groupby(group_cols):
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


def _train_one(model, train_loader, val_loader, epochs, lr, weight_decay, patience, device, loss_placeholder=None):
    import plotly.graph_objects as go

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    loss_fn = torch.nn.MSELoss()
    best_val = float("inf")
    best_state = None
    bad = 0
    hist = {"train": [], "val": []}

    for ep in range(1, epochs + 1):
        model.train()
        tr_loss = 0.0
        n = 0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            opt.step()
            tr_loss += loss.item() * xb.size(0)
            n += xb.size(0)
        tr_loss /= max(n, 1)
        hist["train"].append(tr_loss)

        model.eval()
        va_loss = 0.0
        n = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                va_loss += loss_fn(pred, yb).item() * xb.size(0)
                n += xb.size(0)
        va_loss /= max(n, 1)
        hist["val"].append(va_loss)

        if va_loss < best_val - 1e-6:
            best_val = va_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            bad = 0
        else:
            bad += 1

        # Live loss plot
        if loss_placeholder is not None:
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=hist["train"], mode="lines", name="Train MSE", line=dict(color="#1f77b4")))
            fig.add_trace(go.Scatter(y=hist["val"], mode="lines", name="Val MSE", line=dict(color="#ff7f0e")))
            fig.update_layout(
                title=f"Training loss (epoch {ep}/{epochs})",
                xaxis_title="Epoch",
                yaxis_title="MSE",
                height=320,
                margin=dict(t=48, b=36, l=48, r=24),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            loss_placeholder.plotly_chart(fig, use_container_width=True)

        if bad >= patience:
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    return hist


def _rollout_predict(model, seq, feature_scaler, target_scaler, device, warm_start_steps=1):
    model.eval()
    Pseq = seq["pressure"]
    ctx = seq["ctx"]
    y_true = seq["y"]
    T, O = y_true.shape
    y_pred = np.zeros_like(y_true, dtype=np.float32)
    warm = min(max(1, warm_start_steps), T)
    y_pred[:warm] = y_true[:warm]

    for t in range(warm, T):
        x_t = np.concatenate([Pseq[t], ctx, y_pred[t - 1]], axis=0).reshape(1, -1)
        x_t_s = feature_scaler.transform(x_t).astype(np.float32)
        x_in = torch.from_numpy(x_t_s).unsqueeze(1).to(device)
        with torch.no_grad():
            y_hat_s = model(x_in).cpu().numpy()[0, 0, :]
        y_hat = target_scaler.inverse_transform(y_hat_s.reshape(1, -1))[0]
        y_pred[t] = y_hat.astype(np.float32)
    return y_pred


def _parse_channels(text: str) -> Tuple[int, ...]:
    try:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        return tuple(int(p) for p in parts)
    except Exception:
        return (64, 64, 128, 128)


def _parse_context_cols(text: str) -> List[str]:
    if not text or not str(text).strip():
        return []
    return [c.strip() for c in str(text).split(",") if c.strip()]


# Directory for saving DL training runs (MSE history + prediction plots)
DL_RUNS_DIR = Path(__file__).resolve().parent / "dl_training_runs"


def _dl_run_basename(
    channels: Tuple[int, ...],
    conv_type: str,
    kernel_size: int,
    epochs: int,
    batch_size: int,
    dropout: float,
    activation: str,
    test_pressure: float,
    window_len: int,
    stride: int,
    min_seq_len: int,
) -> str:
    """Build a filesystem-safe base name from key hyperparameters for identifying runs."""
    ch = "-".join(map(str, channels))
    safe = re.sub(r"[^\w\-.]", "_", f"{ch}_{conv_type}_k{kernel_size}_ep{epochs}_bs{batch_size}_drop{dropout}_act{activation}_tp{test_pressure}_w{window_len}_s{stride}_minlen{min_seq_len}")
    return safe


def _get_next_run_path(dir_path: Path, basename: str, ext: str) -> Path:
    """Return path for basename.ext; if exists, use basename_2.ext, basename_3.ext, ..."""
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


def _save_dl_run(
    hist: Dict[str, List[float]],
    pred_fig,  # plotly Figure
    channels: Tuple[int, ...],
    conv_type: str,
    kernel_size: int,
    epochs: int,
    batch_size: int,
    dropout: float,
    activation: str,
    test_pressure: float,
    window_len: int,
    stride: int,
    min_seq_len: int,
    metrics: Dict,
) -> Tuple[Path, Path]:
    """Save MSE history (CSV) and prediction figure (HTML; PNG if kaleido available). Returns (mse_path, pred_path)."""
    base = _dl_run_basename(channels, conv_type, kernel_size, epochs, batch_size, dropout, activation, test_pressure, window_len, stride, min_seq_len)
    mse_path = _get_next_run_path(DL_RUNS_DIR, base, ".csv")
    run_stem = mse_path.stem  # same index as CSV, e.g. base or base_2
    pred_html_path = mse_path.parent / f"pred_{run_stem}.html"
    DL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    # MSE history
    with open(mse_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train_mse", "val_mse"])
        n_epochs = len(hist["train"])
        for i in range(n_epochs):
            w.writerow([i + 1, hist["train"][i], hist["val"][i]])
    # Metrics summary (same run index as CSV)
    import json
    meta_path = mse_path.parent / f"{run_stem}_metrics.json"
    with open(meta_path, "w") as f:
        json.dump(metrics, f, indent=2)
    # Prediction figure: HTML always
    pred_fig.write_html(str(pred_html_path))
    # PNG if kaleido available
    pred_png_path = mse_path.parent / f"pred_{run_stem}.png"
    try:
        pred_fig.write_image(str(pred_png_path))
    except Exception:
        pred_png_path = None
    return mse_path, pred_png_path if pred_png_path and pred_png_path.exists() else pred_html_path


def _draw_tcn_architecture(
    channels: List[int],
    layer_opts: Optional[List[dict]] = None,
    conv_type: str = "Conv1D",
    activation: str = "ReLU",
) -> Optional[object]:
    """Draw TCN architecture: Input → vertical stacks per layer (CONV, BN, activation, Dropout, Pool) → Output. Returns None if matplotlib/numpy fail to import."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError as e:
        return None

    ch_list = channels if channels else [64]
    opts = layer_opts if layer_opts and len(layer_opts) >= len(ch_list) else None
    n_blocks = len(ch_list)
    block_w = 0.75
    cell_h = 0.38
    gap = 0.18
    input_w, output_w = 0.7, 0.7
    total_w = 0.25 + input_w + gap + n_blocks * (block_w + gap) + output_w + 0.25
    max_cells = 5
    total_h = max_cells * cell_h + 0.6
    fig, ax = plt.subplots(figsize=(min(3 + n_blocks * 0.85, 12), 4.5))
    ax.set_xlim(0, total_w)
    ax.set_ylim(0, total_h)
    ax.axis("off")

    colors = {
        "CONV": ("#90caf9", "#1976d2"),
        "Batch Norm": ("#ffb74d", "#e65100"),
        "Activation": ("#fff59d", "#f9a825"),  # ReLU, GELU, Tanh, LeakyReLU
        "Dropout": ("#bdbdbd", "#616161"),
        "Max Pool": ("#81c784", "#2e7d32"),
        "Input": ("#e3f2fd", "#1976d2"),
        "Output": ("#c8e6c9", "#2e7d32"),
    }

    def draw_vertical_box(x: float, y: float, w: float, h: float, label: str, key: str):
        face, edge = colors.get(key, ("#fafafa", "#333"))
        rect = mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", facecolor=face, edgecolor=edge, linewidth=1.2)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=7, rotation=90)

    y_center = total_h / 2
    x = 0.25
    draw_vertical_box(x, y_center - 0.35, input_w, 0.7, "Input", "Input")
    input_right = x + input_w
    x += input_w + gap

    layer_rights = []
    for i, ch in enumerate(ch_list):
        o = opts[i] if opts and i < len(opts) else {}
        cells = [("CONV", f"CONV {ch}")]
        if o.get("use_batch_norm"):
            cells.append(("Batch Norm", "Batch Norm"))
        cells.append(("Activation", activation))
        if o.get("use_dropout"):
            cells.append(("Dropout", "Dropout"))
        if o.get("use_pooling"):
            cells.append(("Max Pool", "Max Pool"))
        n_cells = len(cells)
        stack_h = n_cells * cell_h
        y_start = y_center - stack_h / 2
        for j, (key, label) in enumerate(cells):
            draw_vertical_box(x, y_start + j * cell_h, block_w, cell_h, label, key)
        layer_rights.append(x + block_w)
        x += block_w + gap

    draw_vertical_box(x, y_center - 0.35, output_w, 0.7, "Output", "Output")
    output_left = x
    x += output_w

    arrow_y = y_center
    # Arrow: Input -> first layer
    first_layer_left = 0.25 + input_w + gap
    ax.annotate("", xy=(first_layer_left - 0.02, arrow_y), xytext=(input_right + 0.02, arrow_y),
                arrowprops=dict(arrowstyle="->", color="#1565c0", lw=2))
    # Arrows: between consecutive layers
    for i in range(len(layer_rights) - 1):
        x_from = layer_rights[i] + 0.02
        x_to = layer_rights[i + 1] - block_w - 0.02
        ax.annotate("", xy=(x_to, arrow_y), xytext=(x_from, arrow_y),
                    arrowprops=dict(arrowstyle="->", color="#1565c0", lw=2))
    # Arrow: last layer -> Output
    ax.annotate("", xy=(output_left - 0.02, arrow_y), xytext=(layer_rights[-1] + 0.02, arrow_y),
                arrowprops=dict(arrowstyle="->", color="#1565c0", lw=2))
    ax.set_title(f"TCN architecture ({conv_type}) — parameters per layer", fontsize=10)
    plt.tight_layout()
    return fig


def render_dl_model_tab(compiled: pd.DataFrame, summary: pd.DataFrame, pn: List[str], cfg: dict) -> None:
    """Render the DL Model tab: configurable TCN with layer options and text inputs."""
    section(
        "🧠",
        "blue",
        "DL Model (TCN)",
        "Forward: pressure u(t) → measured force & derived bending angle at varying time (train on 9 pressures). "
        "Inverse: target force & angle → predicted pressure; use on finger to validate (feedback propagation).",
    )

    try:
        _ensure_torch()
    except ImportError as e:
        st.warning(str(e))
        return

    df = compiled
    if df is None or len(df) < 10:
        st.info("Process data in the **Process** tab first to use the DL model.")
        return
    if "Time" not in df.columns:
        st.warning("Compiled data must contain a **Time** column.")
        return

    pressure_col = "Pressure (kPa)" if "Pressure (kPa)" in df.columns else None
    if not pressure_col or df[pressure_col].nunique() < 2:
        st.warning("Need at least 2 pressure levels for train/validation split.")
        return

    time_col = "Time"
    angle_cols = [c for c in ["angle1", "angle2"] if c in df.columns]
    other_targets = [c for c in ["p8_disp", "Contact Force (N)", "Contact Area (mm²)", "Contact Arc Length (mm)", "Tip Stiffness (N/mm)", "Tip Work (N·mm)"] if c in df.columns]
    target_candidates = list(dict.fromkeys(angle_cols + other_targets))
    # Input feature candidates: numeric columns (context per sequence), exclude Time and Pressure (used separately)
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    input_candidates = [c for c in numeric_cols if c not in (time_col, pressure_col)]
    default_inputs = [c for c in ["Finger Length (mm)", "Finger Width (mm)", "Speed (m/s)"] if c in input_candidates]
    if not default_inputs and input_candidates:
        default_inputs = input_candidates[:3]

    if not target_candidates:
        st.warning("No target columns (angle1, angle2, etc.) found in data.")
        return

    # ── 1) Data & validation ──
    st.markdown("#### 1. Data & validation")
    pressures = sorted(df[pressure_col].dropna().unique().astype(float).tolist())
    test_pressure = st.selectbox(
        "Hold-out pressure for validation",
        pressures,
        index=len(pressures) - 1 if len(pressures) > 1 else 0,
        key="dl_test_pressure",
    )
    target_cols_sel = st.multiselect(
        "Target(s) to predict (multiselect)",
        target_candidates,
        default=angle_cols[:1] if angle_cols else target_candidates[:1],
        key="dl_target_cols",
    )
    context_cols = st.multiselect(
        "Input features for training (multiselect)",
        input_candidates,
        default=default_inputs,
        key="dl_input_features",
    )
    min_seq_len = st.number_input("Min sequence length", min_value=10, value=80, step=5, key="dl_min_seq_len")

    if not target_cols_sel:
        st.warning("Select at least one target.")
        return

    # ── 2) Windowing ──
    st.markdown("#### 2. Windowing")
    window_len = st.number_input("Window length (timesteps)", min_value=8, value=64, step=8, key="dl_window_len")
    stride = st.number_input("Stride", min_value=1, value=8, step=1, key="dl_stride")

    # ── 3) Training hyperparameters ──
    st.markdown("#### 3. Training")
    seed = st.number_input("Random seed", min_value=0, value=42, step=1, key="dl_seed")
    batch_size = st.number_input("Batch size", min_value=1, value=128, step=16, key="dl_batch_size")
    st.caption("Recommended: **32–64** for small data (few pressure levels/short sequences), **64–128** for medium, **128–256** for large. Default 128 is a good starting point.")
    epochs = st.number_input("Epochs", min_value=1, value=100, step=10, key="dl_epochs")
    lr = st.text_input("Learning rate", value="1e-3", key="dl_lr")
    weight_decay = st.text_input("Weight decay", value="1e-6", key="dl_weight_decay")
    patience = st.number_input("Early stopping patience", min_value=1, value=25, step=5, key="dl_patience")
    rollout_warm_start = st.number_input("Rollout warm-start steps", min_value=1, value=1, key="dl_rollout_warm")

    # ── 4) Model / layer options ──
    st.markdown("#### 4. Model & layers")
    if "_dl_channels_list" not in st.session_state:
        st.session_state["_dl_channels_list"] = [64, 64, 128, 128]
    if "_dl_layer_opts" not in st.session_state:
        st.session_state["_dl_layer_opts"] = [
            {"use_batch_norm": False, "use_dropout": True, "use_pooling": False},
            {"use_batch_norm": False, "use_dropout": True, "use_pooling": False},
            {"use_batch_norm": False, "use_dropout": True, "use_pooling": False},
            {"use_batch_norm": False, "use_dropout": True, "use_pooling": False},
        ]

    col_params, col_arch = st.columns([1, 1])
    with col_params:
        conv_type = st.selectbox(
            "Conv type",
            ["Conv1D", "Conv2D"],
            index=0,
            key="dl_conv_type",
            help="Conv1D: standard for time series. Conv2D: experimental (reshapes 1D→2D); try if Conv1D gives high MSE.",
        )
        if conv_type == "Conv1D":
            st.caption("Conv1D is recommended for this time-series data. Use Conv2D only to experiment.")
        kernel_size = st.number_input("Kernel size", min_value=2, value=3, step=1, key="dl_kernel_size")
        dropout_rate = st.number_input("Dropout rate", min_value=0.0, max_value=1.0, value=0.1, step=0.05, format="%.2f", key="dl_dropout")
        activation = st.selectbox("Activation function", ["ReLU", "Tanh", "LeakyReLU", "GELU"], index=0, key="dl_activation")

        st.markdown("**Channels & per-layer options** — ➕ / ➖ to add or remove layers. Per layer: choose BN, Dropout, Pool.")
        st.caption("For **~3700 training samples**: use **3–4 layers** with channels **64, 64, 128** or **64, 64, 128, 128**. Start with 64 in early layers and 128 in deeper layers; add dropout (e.g. 0.1–0.2) to reduce overfitting.")
        ch_list = st.session_state["_dl_channels_list"]
        layer_opts = st.session_state["_dl_layer_opts"]
        while len(layer_opts) < len(ch_list):
            layer_opts.append({"use_batch_norm": False, "use_dropout": True, "use_pooling": False})
        while len(layer_opts) > len(ch_list):
            layer_opts.pop()
        st.session_state["_dl_layer_opts"] = layer_opts

        new_list = []
        new_opts = []
        for i in range(len(ch_list)):
            with st.container():
                r1, r2 = st.columns([2, 3])
                with r1:
                    v = st.number_input(f"Layer {i+1} channels", min_value=1, value=ch_list[i], step=8, key=f"dl_ch_{i}")
                    new_list.append(int(v))
                with r2:
                    o = layer_opts[i] if i < len(layer_opts) else {"use_batch_norm": False, "use_dropout": True, "use_pooling": False}
                    bn = st.checkbox("BN", value=o.get("use_batch_norm", False), key=f"dl_bn_{i}", help="Batch norm")
                    drop = st.checkbox("Dropout", value=o.get("use_dropout", True), key=f"dl_drop_{i}", help="Use dropout in this layer")
                    pool = st.checkbox("Pool", value=o.get("use_pooling", False), key=f"dl_pool_{i}", help="MaxPool after this block")
                    new_opts.append({"use_batch_norm": bn, "use_dropout": drop, "use_pooling": pool})
        btn_col1, btn_col2, _ = st.columns([1, 1, 3])
        with btn_col1:
            if st.button("➕ Add layer", key="dl_add_layer"):
                last_o = new_opts[-1] if new_opts else {"use_batch_norm": False, "use_dropout": True, "use_pooling": False}
                st.session_state["_dl_channels_list"] = new_list + [new_list[-1] if new_list else 64]
                st.session_state["_dl_layer_opts"] = new_opts + [dict(last_o)]
                st.rerun()
        with btn_col2:
            if st.button("➖ Remove layer", key="dl_remove_layer") and len(new_list) > 1:
                st.session_state["_dl_channels_list"] = new_list[:-1]
                st.session_state["_dl_layer_opts"] = new_opts[:-1]
                st.rerun()
        st.session_state["_dl_channels_list"] = new_list
        st.session_state["_dl_layer_opts"] = new_opts

    with col_arch:
        channels = tuple(st.session_state["_dl_channels_list"])
        layer_opts_display = st.session_state["_dl_layer_opts"]
        arch_fig = _draw_tcn_architecture(list(channels), layer_opts_display, conv_type, activation)
        if arch_fig is not None:
            st.pyplot(arch_fig)
            import matplotlib.pyplot as plt
            plt.close(arch_fig)
        else:
            st.warning(
                "Architecture diagram could not be drawn (NumPy/matplotlib import error). "
                "Try: **pip install --upgrade numpy** then restart the app."
            )

    st.markdown("#### Live training loss")
    loss_placeholder = st.empty()

    if st.button("▶ Train DL model", type="primary", key="dl_train_btn"):
        with st.spinner("Building sequences and training…"):
            _run_dl_training(
                df=df,
                pressure_col=pressure_col,
                time_col=time_col,
                context_cols=context_cols,
                target_cols=target_cols_sel,
                test_pressure=float(test_pressure),
                min_seq_len=int(min_seq_len),
                window_len=int(window_len),
                stride=int(stride),
                seed=int(seed),
                batch_size=int(batch_size),
                epochs=int(epochs),
                lr=float(lr),
                weight_decay=float(weight_decay),
                patience=int(patience),
                kernel_size=int(kernel_size),
                channels=channels,
                dropout=float(dropout_rate),
                layer_opts=st.session_state["_dl_layer_opts"],
                activation=activation,
                conv_type=conv_type,
                rollout_warm_start_steps=int(rollout_warm_start),
                loss_placeholder=loss_placeholder,
            )

    if "_dl_hist" in st.session_state:
        st.markdown("#### Training curve")
        hist = st.session_state["_dl_hist"]
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(hist["train"], label="Train MSE")
        ax.plot(hist["val"], label="Val MSE")
        ax.set_xlabel("Epoch")
        ax.set_ylabel("MSE")
        ax.set_title("DL model training")
        ax.legend()
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)
        plt.close()

    if "_dl_metrics" in st.session_state:
        st.markdown("#### Test metrics")
        st.json(st.session_state["_dl_metrics"])
    if "_dl_pred_fig" in st.session_state:
        st.plotly_chart(st.session_state["_dl_pred_fig"], use_container_width=True)

    st.markdown("---")
    render_inverse_prediction_section(df, key_prefix="dl_inv")


def _run_dl_training(
    df: pd.DataFrame,
    pressure_col: str,
    time_col: str,
    context_cols: List[str],
    target_cols: List[str],
    test_pressure: float,
    min_seq_len: int,
    window_len: int,
    stride: int,
    seed: int,
    batch_size: int,
    epochs: int,
    lr: float,
    weight_decay: float,
    patience: int,
    kernel_size: int,
    channels: Tuple[int, ...],
    dropout: float,
    layer_opts: List[dict],
    activation: str,
    conv_type: str = "Conv1D",
    rollout_warm_start_steps: int = 1,
    loss_placeholder=None,
) -> None:
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split

    _ensure_torch()
    TCNRegressor, WindowDataset = _get_dl_classes()
    torch.manual_seed(seed)
    np.random.seed(seed)

    seqs = _build_sequences_from_compiled(
        df=df,
        pressure_col=pressure_col,
        time_col=time_col,
        ctx_cols=context_cols,
        target_cols=target_cols,
        pressure_round_decimals=3,
        min_len=min_seq_len,
    )
    if not seqs:
        st.error("No valid sequences built. Increase min sequence length or check columns.")
        return

    def _key_to_pressure(k):
        return float(k[0]) if isinstance(k, tuple) else float(k)

    train_seqs = [s for k, s in seqs.items() if _key_to_pressure(k) != test_pressure]
    test_seqs = [s for k, s in seqs.items() if _key_to_pressure(k) == test_pressure]
    if not train_seqs or not test_seqs:
        st.error("Train or test split is empty.")
        return

    ctx_len = len(context_cols) if context_cols else 0
    feature_scaler = StandardScaler()
    target_scaler = StandardScaler()

    full_train = WindowDataset(
        train_seqs, window_len, stride, feature_scaler, target_scaler,
        fit_scalers=True, ctx_len=ctx_len,
    )
    idx = np.arange(len(full_train))
    tr_idx, va_idx = train_test_split(idx, test_size=0.15, random_state=seed, shuffle=True)
    train_loader = torch.utils.data.DataLoader(
        torch.utils.data.Subset(full_train, tr_idx),
        batch_size=batch_size, shuffle=True, drop_last=False,
    )
    val_loader = torch.utils.data.DataLoader(
        torch.utils.data.Subset(full_train, va_idx),
        batch_size=batch_size, shuffle=False, drop_last=False,
    )

    x0, y0 = full_train[0]
    in_features = x0.shape[-1]
    out_features = y0.shape[-1]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    opts = layer_opts if layer_opts and len(layer_opts) == len(channels) else None
    model = TCNRegressor(
        in_features=in_features,
        out_features=out_features,
        channels=channels,
        kernel_size=kernel_size,
        dropout=dropout,
        layer_opts=opts,
        activation=activation,
        conv_type=conv_type or "Conv1D",
    ).to(device)

    hist = _train_one(model, train_loader, val_loader, epochs, lr, weight_decay, patience, device, loss_placeholder=loss_placeholder)
    st.session_state["_dl_hist"] = hist

    all_true, all_pred = [], []
    for s in test_seqs:
        y_pred = _rollout_predict(model, s, feature_scaler, target_scaler, device, rollout_warm_start_steps)
        all_true.append(s["y"])
        all_pred.append(y_pred)
    Y_true = np.concatenate(all_true, axis=0)
    Y_pred = np.concatenate(all_pred, axis=0)

    metrics = {}
    for j, name in enumerate(target_cols):
        metrics[name] = {
            "RMSE": float(np.sqrt(np.mean((Y_true[:, j] - Y_pred[:, j]) ** 2))),
            "MAE": float(np.mean(np.abs(Y_true[:, j] - Y_pred[:, j]))),
        }
    st.session_state["_dl_metrics"] = {"test_pressure": test_pressure, "targets": target_cols, "metrics": metrics}

    s0 = test_seqs[0]
    t0 = s0["time"]
    y0_true = s0["y"]
    y0_pred = all_pred[0]
    import plotly.graph_objects as go
    fig = go.Figure()
    for j, name in enumerate(target_cols):
        fig.add_trace(go.Scatter(x=t0, y=y0_true[:, j], name=f"{name} (true)", mode="lines"))
        fig.add_trace(go.Scatter(x=t0, y=y0_pred[:, j], name=f"{name} (pred)", mode="lines", line=dict(dash="dash")))
    fig.update_layout(title=f"True vs predicted (test pressure={test_pressure})", xaxis_title="Time", height=400)
    st.session_state["_dl_pred_fig"] = fig
    metrics_for_save = {"test_pressure": test_pressure, "targets": target_cols, "metrics": metrics}
    try:
        mse_path, pred_path = _save_dl_run(
            hist=hist,
            pred_fig=fig,
            channels=channels,
            conv_type=conv_type or "Conv1D",
            kernel_size=kernel_size,
            epochs=epochs,
            batch_size=batch_size,
            dropout=dropout,
            activation=activation,
            test_pressure=test_pressure,
            window_len=window_len,
            stride=stride,
            min_seq_len=min_seq_len,
            metrics=metrics_for_save,
        )
        st.success(f"Training finished. **Saved:** MSE `{mse_path.name}`, prediction `{pred_path.name}` in `{DL_RUNS_DIR}`. See metrics and plot below.")
    except Exception as e:
        st.success("Training finished. See metrics and plot below.")
        st.warning(f"Could not save run to disk: {e}")
