"""
Session store — save and load complete analysis sessions locally.

Saves all settings, compiled/summary DataFrames, Excel export, and chart PNGs
so that loading a session restores the full state without recomputation.

Directory layout per session:
    saves/<timestamp>_<slug>/
        session.json      — all config, metadata, point names
        compiled.csv      — compiled DataFrame
        summary.csv       — summary DataFrame (if present)
        export.xlsx       — pre-generated Excel report
        charts/           — Plotly chart snapshots as HTML
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from processing import to_excel_bytes


_APP_DIR = Path(__file__).resolve().parent
_SAVES_DIR = _APP_DIR / "saves"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_saves_dir() -> Path:
    _SAVES_DIR.mkdir(parents=True, exist_ok=True)
    return _SAVES_DIR


def _slugify(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in (name or "").strip()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "session"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
def save_session(
    name: str,
    disp_cfg: Dict[str, Any],
    db_cfg: Dict[str, Any],
    compiled_df: pd.DataFrame,
    summary_df: Optional[pd.DataFrame] = None,
    point_names: Optional[List[str]] = None,
    chart_html_map: Optional[Dict[str, str]] = None,
) -> Path:
    """
    Save a full analysis session to `saves/<timestamp>_<slug>/`.

    Args:
        name:           Human-readable session name.
        disp_cfg:       Display config dict (Finger, Body Material, etc.).
        db_cfg:         DB config dict (finger_type, body_material, speed, etc.).
        compiled_df:    The compiled DataFrame from processing.
        summary_df:     The summary DataFrame (optional).
        point_names:    List of point names (e.g. ['p1', 'p2', ...]).
        chart_html_map: {chart_name: html_string} for chart snapshots.

    Returns:
        Path to the created session directory.
    """
    if compiled_df is None or compiled_df.empty:
        raise ValueError("compiled_df is empty; nothing to save")

    saves_dir = _ensure_saves_dir()
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(name)
    session_id = f"{ts}_{slug}"
    session_dir = saves_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # ── Session metadata (JSON) ──
    meta = {
        "name": name or session_id,
        "created_at_utc": ts,
        "display_config": _serializable(disp_cfg),
        "db_config": _serializable(db_cfg),
        "point_names": point_names or [],
        "num_rows": len(compiled_df),
        "num_pressures": int(compiled_df["Pressure (kPa)"].nunique())
            if "Pressure (kPa)" in compiled_df.columns else 0,
        "columns": list(compiled_df.columns),
    }
    (session_dir / "session.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8"
    )

    # ── DataFrames ──
    compiled_df.to_csv(session_dir / "compiled.csv", index=False)
    if summary_df is not None and not summary_df.empty:
        summary_df.to_csv(session_dir / "summary.csv", index=False)

    # ── Excel export (pre-generated) ──
    try:
        excel_bytes = to_excel_bytes(compiled_df, db_cfg or {}, summary_df)
        (session_dir / "export.xlsx").write_bytes(excel_bytes)
    except Exception:
        pass  # non-critical; user can re-export

    # ── Chart HTML snapshots ──
    if chart_html_map:
        charts_dir = session_dir / "charts"
        charts_dir.mkdir(exist_ok=True)
        for chart_name, html_str in chart_html_map.items():
            safe_name = _slugify(chart_name) + ".html"
            (charts_dir / safe_name).write_text(html_str, encoding="utf-8")

    return session_dir


def _serializable(d: Any) -> Any:
    """Make a dict JSON-serializable (convert numpy types, etc.)."""
    if d is None:
        return None
    if isinstance(d, dict):
        return {k: _serializable(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [_serializable(v) for v in d]
    try:
        import numpy as np
        if isinstance(d, (np.integer,)):
            return int(d)
        if isinstance(d, (np.floating,)):
            return float(d)
        if isinstance(d, np.ndarray):
            return d.tolist()
    except ImportError:
        pass
    return d


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
def list_saved_sessions(max_items: int = 30) -> List[Dict[str, Any]]:
    """Return recent saved sessions, newest first."""
    saves_dir = _ensure_saves_dir()
    entries = []
    for p in saves_dir.iterdir():
        if p.is_dir() and (p / "session.json").is_file():
            entries.append((p.stat().st_mtime, p))
    entries.sort(reverse=True)

    sessions = []
    for _, p in entries[:max_items]:
        try:
            meta = json.loads((p / "session.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        sessions.append({
            "id": p.name,
            "label": meta.get("name") or p.name,
            "path": p,
            "created": meta.get("created_at_utc", ""),
            "num_rows": meta.get("num_rows", 0),
            "num_pressures": meta.get("num_pressures", 0),
            "display_config": meta.get("display_config", {}),
            "db_config": meta.get("db_config", {}),
            "point_names": meta.get("point_names", []),
        })
    return sessions


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_saved_session(session_id: str) -> Dict[str, Any]:
    """
    Load a saved session by ID.

    Returns dict with:
        - id, config (the raw session.json contents)
        - display_config, db_config
        - compiled_df, summary_df
        - point_names
        - chart_html_map: {chart_name: html_string}
    """
    saves_dir = _ensure_saves_dir()
    session_dir = saves_dir / session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Session not found: {session_id}")

    # Metadata
    meta_path = session_dir / "session.json"
    meta: Dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    # DataFrames
    compiled_csv = session_dir / "compiled.csv"
    summary_csv = session_dir / "summary.csv"
    compiled_df = pd.read_csv(compiled_csv) if compiled_csv.is_file() else None
    summary_df = pd.read_csv(summary_csv) if summary_csv.is_file() else None

    # Chart HTML files
    chart_html_map: Dict[str, str] = {}
    charts_dir = session_dir / "charts"
    if charts_dir.is_dir():
        for f in charts_dir.iterdir():
            if f.suffix == ".html":
                try:
                    chart_html_map[f.stem] = f.read_text(encoding="utf-8")
                except Exception:
                    pass

    return {
        "id": session_id,
        "config": meta,
        "display_config": meta.get("display_config", {}),
        "db_config": meta.get("db_config", {}),
        "point_names": meta.get("point_names", []),
        "compiled_df": compiled_df,
        "summary_df": summary_df,
        "chart_html_map": chart_html_map,
    }


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
def delete_saved_session(session_id: str) -> bool:
    """Delete a saved session directory. Returns True on success."""
    saves_dir = _ensure_saves_dir()
    session_dir = saves_dir / session_id
    if not session_dir.is_dir():
        return False
    try:
        shutil.rmtree(session_dir)
        return True
    except Exception:
        return False
