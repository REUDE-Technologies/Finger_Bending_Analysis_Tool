"""
Local run presets — save and load full analysis sessions.

This first version is **local-only** (no Supabase) and is safe to use both
on desktop and in Railway containers (writes under the app directory).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from processing import to_excel_bytes


_APP_DIR = Path(__file__).resolve().parent
_RUNS_DIR = _APP_DIR / "runs"


def _ensure_runs_dir() -> Path:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNS_DIR


def _slugify(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in (name or "").strip()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "run"


def save_run_preset(
    name: str,
    disp_cfg: Dict[str, Any],
    db_cfg: Dict[str, Any],
    compiled_df: pd.DataFrame,
    summary_df: pd.DataFrame | None = None,
) -> Path:
    """
    Save current session to a local 'runs/<timestamp>_<name>/' folder.

    Stores:
      - config.json       → display + db config and metadata
      - compiled.csv      → compiled dataframe
      - summary.csv       → summary dataframe (if present)
      - export.xlsx       → the same Excel export the user can download
    """
    if compiled_df is None or compiled_df.empty:
        raise ValueError("compiled_df is empty; nothing to save")

    runs_dir = _ensure_runs_dir()
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(name)
    run_id = f"{ts}_{slug}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Config & metadata
    cfg_payload = {
        "name": name or run_id,
        "created_at_utc": ts,
        "display_config": disp_cfg,
        "db_config": db_cfg,
    }
    (run_dir / "config.json").write_text(json.dumps(cfg_payload, indent=2), encoding="utf-8")

    # Dataframes
    compiled_df.to_csv(run_dir / "compiled.csv", index=False)
    if summary_df is not None:
        summary_df.to_csv(run_dir / "summary.csv", index=False)

    # Excel export
    excel_bytes = to_excel_bytes(compiled_df, db_cfg or {}, summary_df)
    (run_dir / "export.xlsx").write_bytes(excel_bytes)

    return run_dir


def list_run_presets(max_items: int = 20) -> List[Dict[str, Any]]:
    """Return recent presets from the local runs directory."""
    runs_dir = _ensure_runs_dir()
    entries: List[Tuple[float, Path]] = []
    for p in runs_dir.iterdir():
        if p.is_dir():
            entries.append((p.stat().st_mtime, p))
    entries.sort(reverse=True)
    presets: List[Dict[str, Any]] = []
    for _, p in entries[:max_items]:
        cfg_path = p / "config.json"
        name = p.name
        label = name
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                label = data.get("name") or label
            except Exception:
                pass
        presets.append({"id": p.name, "label": label, "path": p})
    return presets


def load_run_preset(run_id: str) -> Dict[str, Any]:
    """Load a preset's config and dataframes by ID."""
    runs_dir = _ensure_runs_dir()
    run_dir = runs_dir / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run preset not found: {run_id}")

    cfg_path = run_dir / "config.json"
    cfg: Dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    compiled_csv = run_dir / "compiled.csv"
    summary_csv = run_dir / "summary.csv"

    compiled_df = pd.read_csv(compiled_csv) if compiled_csv.is_file() else None
    summary_df = pd.read_csv(summary_csv) if summary_csv.is_file() else None

    return {
        "id": run_id,
        "config": cfg,
        "compiled_df": compiled_df,
        "summary_df": summary_df,
    }

