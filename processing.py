"""
Data processing module for Finger Bending Analysis.

Responsibilities:
  - Parse point tracking files (t, x, y format)
  - Merge point data on the time column
  - Calculate displacement from initial position
  - Calculate bending angles (3-point method)
  - Build summary statistics and Excel export
"""

import io
import math
import os
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
COL_TIME = "Time"
COL_PRESSURE = "Pressure (kPa)"
COL_SPEED = "Speed (m/s)"
COL_T = "t"
COL_X = "x"
COL_Y = "y"

# Angle definitions: (vertex, ray_endpoint_1, ray_endpoint_2)
ANGLE1_DEFINITION = ("p1", "p7", "p8")  # angle at P1 formed by P7-P1-P8
ANGLE2_DEFINITION = ("p2", "p5", "p6")  # angle at P2 formed by P5-P2-P6

DENOMINATOR_EPSILON = 1e-12


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------
def parse_point_file(content: bytes | str, filename: str = "") -> pd.DataFrame:
    """
    Parse a point tracking file with columns: t, x, y.

    Handles variable columns, blank cells, and header rows (e.g. "p1", "t x y").
    Skips non-numeric rows. Returns DataFrame with columns ['t', 'x', 'y'].
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    rows = []
    for line in content.splitlines():
        tokens = _parse_line_tokens(line)
        if len(tokens) < 3:
            continue
        row = _try_parse_numeric_row(tokens[:3])
        if row is not None:
            rows.append(row)

    if not rows:
        raise ValueError(
            f"File '{filename}' has no valid numeric data (expected t, x, y)"
        )

    return pd.DataFrame(rows, columns=[COL_T, COL_X, COL_Y])


def _parse_line_tokens(line: str) -> List[str]:
    """Split line by whitespace, strip empty tokens (handles blank cells)."""
    return [t.strip() for t in line.split() if t.strip()]


def _try_parse_numeric_row(tokens: List[str]) -> Optional[List[float]]:
    """Try to parse first 3 tokens as floats. Returns None if any fail."""
    try:
        return [float(tokens[0]), float(tokens[1]), float(tokens[2])]
    except (ValueError, IndexError):
        return None


def extract_zip(zip_bytes: bytes) -> Dict[str, bytes]:
    """Extract .txt files from a ZIP. Returns {filename: content}."""
    result = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            basename = name.split("/")[-1]
            if basename.lower().endswith(".txt") and not basename.startswith("."):
                result[basename] = zf.read(name)
    return result



# ---------------------------------------------------------------------------
# Simple ZIP extraction (flat — for per-pressure uploads)
# ---------------------------------------------------------------------------
def extract_zip(zip_bytes: bytes) -> Dict[str, bytes]:
    """
    Extract all .txt files from a ZIP into a flat {filename: content} dict.
    Used when user uploads a ZIP for a single pressure level.
    """
    result: Dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            basename = name.split("/")[-1]
            if basename.lower().endswith(".txt") and not basename.startswith("."):
                result[basename] = zf.read(name)
    return result


# ---------------------------------------------------------------------------
# ZIP structure scanning
# ---------------------------------------------------------------------------
def detect_pressure_from_path(path: str) -> Optional[int]:
    """
    Extract pressure level (kPa) from a folder or file path.

    Recognises patterns like:
      - '10/'  or '10kpa/'  or '10 kPa/'
      - 'pressure_10/' or 'p10/'
      - Direct numeric folder names
    """
    parts = [p.strip() for p in path.replace("\\", "/").split("/") if p.strip()]
    if not parts:
        return None

    # Check each path component for a pressure indicator
    for part in parts:
        part_lower = part.lower().strip()

        # Exact numeric folder name: '10', '20', '100', etc.
        if re.fullmatch(r"\d+", part_lower):
            val = int(part_lower)
            if 1 <= val <= 200:
                return val

        # '10kpa', '10 kpa', '10_kpa', 'kpa10'
        m = re.search(r"(\d+)\s*kpa", part_lower)
        if m:
            return int(m.group(1))
        m = re.search(r"kpa\s*(\d+)", part_lower)
        if m:
            return int(m.group(1))

        # 'pressure_10', 'pressure10', 'p_10'
        m = re.search(r"pressure[_\s-]*(\d+)", part_lower)
        if m:
            return int(m.group(1))

    return None


def scan_zip_structure(
    zip_bytes: bytes,
) -> Dict[int, Dict[str, bytes]]:
    """
    Scan a ZIP archive and auto-detect pressure levels from folder structure.

    Returns:
        {pressure_kpa: {point_filename: content}}

    Expected ZIP layouts:
        data.zip/10/p1.txt          → pressure=10, point=p1
        data.zip/20kpa/p1.txt       → pressure=20, point=p1
        data.zip/pressure_30/p1.txt → pressure=30, point=p1
    """
    pressure_files: Dict[int, Dict[str, bytes]] = {}

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for name in zf.namelist():
            # Skip directories
            if name.endswith("/"):
                continue

            basename = name.split("/")[-1]

            # Only process .txt files, ignore hidden files
            if not basename.lower().endswith(".txt") or basename.startswith("."):
                continue

            # Detect pressure from the path (folder name)
            pressure = detect_pressure_from_path(name)
            if pressure is None:
                continue

            if pressure not in pressure_files:
                pressure_files[pressure] = {}
            pressure_files[pressure][basename] = zf.read(name)

    return pressure_files


def get_zip_summary(pressure_files: Dict[int, Dict[str, bytes]]) -> Dict:
    """
    Generate a summary of scanned ZIP contents.

    Returns dict with:
        - pressures: sorted list of detected pressure levels
        - total_files: total number of point files
        - points_per_pressure: {kpa: [sorted point names]}
        - all_points: sorted list of all unique point names found
    """
    pressures = sorted(pressure_files.keys())
    total_files = sum(len(v) for v in pressure_files.values())

    points_per_pressure = {}
    all_points = set()
    for kpa in pressures:
        point_names = sorted(
            [f.replace(".txt", "").replace(".TXT", "").strip()
             for f in pressure_files[kpa].keys()],
            key=extract_point_number,
        )
        points_per_pressure[kpa] = point_names
        all_points.update(point_names)

    return {
        "pressures": pressures,
        "total_files": total_files,
        "points_per_pressure": points_per_pressure,
        "all_points": sorted(all_points, key=extract_point_number),
    }


def filter_pressure_files(
    pressure_files: Dict[int, Dict[str, bytes]],
    selected_pressures: List[int],
    selected_points: Optional[List[str]] = None,
) -> Dict[int, Dict[str, bytes]]:
    """
    Filter pressure_files dict to only include selected pressures and points.

    Args:
        pressure_files: full scanned data
        selected_pressures: which pressure levels to keep
        selected_points: which point names to keep (None = keep all)

    Returns:
        Filtered {kpa: {filename: content}}
    """
    result = {}
    for kpa in selected_pressures:
        if kpa not in pressure_files:
            continue
        if selected_points is None:
            result[kpa] = pressure_files[kpa]
        else:
            filtered = {}
            for fname, content in pressure_files[kpa].items():
                point_name = fname.replace(".txt", "").replace(".TXT", "").strip()
                if point_name in selected_points:
                    filtered[fname] = content
            if filtered:
                result[kpa] = filtered
    return result


def scan_folder_structure(
    folder_path: str,
) -> Dict[int, Dict[str, bytes]]:
    """
    Scan a local folder and auto-detect pressure levels from subdirectories.

    Expects the same layout as the ZIP:
        folder/10/p1.txt          → pressure=10, point=p1
        folder/20kpa/p1.txt       → pressure=20, point=p1

    Returns:
        {pressure_kpa: {point_filename: content}}
    """
    root = Path(folder_path)
    if not root.is_dir():
        raise ValueError(f"Path is not a directory: {folder_path}")

    pressure_files: Dict[int, Dict[str, bytes]] = {}

    for entry in root.iterdir():
        if not entry.is_dir():
            continue

        # Detect pressure from folder name
        pressure = detect_pressure_from_path(entry.name)
        if pressure is None:
            continue

        # Read all .txt files in this pressure folder
        files = {}
        for txt_file in entry.iterdir():
            if txt_file.is_file() and txt_file.suffix.lower() == ".txt" and not txt_file.name.startswith("."):
                files[txt_file.name] = txt_file.read_bytes()

        if files:
            pressure_files[pressure] = files

    return pressure_files


# ---------------------------------------------------------------------------
# Point name utilities
# ---------------------------------------------------------------------------
def extract_point_number(name: str) -> int:
    """Extract numeric suffix from point name. E.g. 'p1' -> 1, 'p12' -> 12."""
    match = re.search(r"(\d+)", name)
    return int(match.group(1)) if match else 0


def extract_point_names_from_columns(columns: pd.Index) -> List[str]:
    """
    Extract unique point names from compiled DataFrame columns.

    Looks for columns matching pN_x, pN_y, pN_disp. Returns sorted list by point number.
    """
    point_names = set()
    for col in columns:
        if re.match(r"p\d+_", col):
            base = col.replace("_x", "").replace("_y", "").replace("_disp", "")
            point_names.add(base)
    return sorted(point_names, key=extract_point_number)


# ---------------------------------------------------------------------------
# Data merging
# ---------------------------------------------------------------------------
def merge_point_dataframes(
    point_frames: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Merge multiple point DataFrames on the time column.

    Args:
        point_frames: {point_name: DataFrame} with columns [t, x, y]

    Returns:
        Merged DataFrame: Time, p1_x, p1_y, p2_x, p2_y, ...
    """
    if not point_frames:
        return pd.DataFrame()

    sorted_names = sorted(point_frames.keys(), key=extract_point_number)
    merged = None

    for name in sorted_names:
        df = point_frames[name][[COL_T, COL_X, COL_Y]].copy()
        df = df.rename(columns={COL_X: f"{name}_x", COL_Y: f"{name}_y"})

        if merged is None:
            merged = df.rename(columns={COL_T: COL_TIME})
        else:
            df = df.drop(columns=[COL_T], errors="ignore")
            merged = pd.concat(
                [merged.reset_index(drop=True), df.reset_index(drop=True)],
                axis=1,
            )

    return merged


# ---------------------------------------------------------------------------
# Displacement
# ---------------------------------------------------------------------------
def calculate_displacement(
    df: pd.DataFrame,
    point_names: List[str],
) -> pd.DataFrame:
    """
    Add displacement columns for each point.

    Displacement = Euclidean distance from initial position (row 0) at each time step.
    """
    result = df.copy()

    for name in point_names:
        x_col = f"{name}_x"
        y_col = f"{name}_y"
        if x_col not in result.columns or y_col not in result.columns:
            continue

        x0 = result[x_col].iloc[0]
        y0 = result[y_col].iloc[0]
        result[f"{name}_disp"] = np.sqrt(
            (result[x_col] - x0) ** 2 + (result[y_col] - y0) ** 2
        )

    return result


# ---------------------------------------------------------------------------
# Bending angle (3-point method)
# ---------------------------------------------------------------------------
def _calculate_angle_vectorized(
    v_x: pd.Series, v_y: pd.Series,
    r1_x: pd.Series, r1_y: pd.Series,
    r2_x: pd.Series, r2_y: pd.Series
) -> np.ndarray:
    """
    Vectorized calculation of the interior angle at vertex V between rays V->R1 and V->R2.
    Returns angle in [0, 180] degrees. More bending => smaller angle (so pressure up => angle down).
    """
    # Vectors from vertex to ray endpoints
    ax = r1_x - v_x
    ay = r1_y - v_y
    bx = r2_x - v_x
    by = r2_y - v_y
    # Dot product and cross product (2D)
    dot = ax * bx + ay * by
    cross = ax * by - ay * bx
    # Interior angle in [0, pi]: atan2(|cross|, dot); avoid zero denominator
    dot_safe = np.maximum(np.asarray(dot, dtype=float), 1e-12)
    angle_rad = np.arctan2(np.abs(np.asarray(cross, dtype=float)), dot_safe)
    angle_deg = np.degrees(angle_rad)
    # Clamp to [0, 180] (numerical noise can push slightly past)
    angle_deg = np.clip(angle_deg, 0.0, 180.0)
    return angle_deg


def add_angle_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add angle1 and angle2 columns to the merged DataFrame.

    angle1: angle at P1 formed by P7-P1-P8
    angle2: angle at P2 formed by P5-P2-P6
    """
    result = df.copy()

    vertex, r1, r2 = ANGLE1_DEFINITION
    req1 = [f"{p}_x" for p in [vertex, r1, r2]] + [f"{p}_y" for p in [vertex, r1, r2]]
    if all(c in result.columns for c in req1):
        result["angle1"] = _calculate_angle_vectorized(
            result[f"{vertex}_x"], result[f"{vertex}_y"],
            result[f"{r1}_x"], result[f"{r1}_y"],
            result[f"{r2}_x"], result[f"{r2}_y"]
        )

    vertex, r1, r2 = ANGLE2_DEFINITION
    req2 = [f"{p}_x" for p in [vertex, r1, r2]] + [f"{p}_y" for p in [vertex, r1, r2]]
    if all(c in result.columns for c in req2):
        result["angle2"] = _calculate_angle_vectorized(
            result[f"{vertex}_x"], result[f"{vertex}_y"],
            result[f"{r1}_x"], result[f"{r1}_y"],
            result[f"{r2}_x"], result[f"{r2}_y"]
        )

    return result


# ---------------------------------------------------------------------------
# Pipeline: single pressure level
# ---------------------------------------------------------------------------
def process_pressure_level(
    point_files: Dict[str, bytes],
    pressure_kpa: int,
    speed: float = 0.0,
) -> pd.DataFrame:
    """
    Process all point files for one pressure level.

    Args:
        point_files: {filename: content} e.g. {'p1.txt': b'...', 'p2.txt': b'...'}
        pressure_kpa: Pressure in kPa
        speed: Speed in m/s

    Returns:
        Processed DataFrame with all columns.
    """
    parsed = {}
    for fname, content in point_files.items():
        name = fname.replace(".txt", "").replace(".TXT", "").strip()
        try:
            parsed[name] = parse_point_file(content, fname)
        except Exception as e:
            raise ValueError(f"Error parsing {fname}: {e}")

    if not parsed:
        raise ValueError("No valid point files found")

    point_names = sorted(parsed.keys(), key=extract_point_number)
    merged = merge_point_dataframes(parsed)
    merged = calculate_displacement(merged, point_names)
    merged = add_angle_columns(merged)

    merged.insert(0, COL_PRESSURE, pressure_kpa)
    merged.insert(1, COL_SPEED, speed)

    return merged


# ---------------------------------------------------------------------------
# Pipeline: all pressure levels
# ---------------------------------------------------------------------------
def compile_all_pressures(
    pressure_data: Dict[int, Dict[str, bytes]],
    speed: float = 0.0,
) -> pd.DataFrame:
    """
    Process and stack all pressure levels into one DataFrame.
    """
    frames = []
    for kpa in sorted(pressure_data.keys()):
        df = process_pressure_level(pressure_data[kpa], kpa, speed)
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------
def build_summary(
    compiled_df: pd.DataFrame,
    point_names: List[str],
) -> pd.DataFrame:
    """
    Build summary table: max displacement, std dev per point, angle stats.
    One row per pressure level.
    """
    rows = []
    for kpa, group in compiled_df.groupby(COL_PRESSURE):
        row = {COL_PRESSURE: kpa}
        for name in point_names:
            disp_col = f"{name}_disp"
            x_col = f"{name}_x"
            y_col = f"{name}_y"
            if disp_col in group.columns:
                row[f"{name}_max_disp"] = group[disp_col].max()
            if x_col in group.columns:
                row[f"{name}_x_std"] = group[x_col].std()
            if y_col in group.columns:
                row[f"{name}_y_std"] = group[y_col].std()
        if "angle1" in group.columns:
            row["angle1_mean"] = group["angle1"].mean()
            row["angle1_std"] = group["angle1"].std()
        if "angle2" in group.columns:
            row["angle2_mean"] = group["angle2"].mean()
            row["angle2_std"] = group["angle2"].std()
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
def to_excel_bytes(
    compiled_df: pd.DataFrame,
    config: Dict,
    summary_df: Optional[pd.DataFrame] = None,
) -> bytes:
    """
    Export compiled data to Excel bytes.

    Sheet "Data": A single filterable table.
      - Config columns (Finger, Body Material …) are prepended to every row.
      - Max displacement and max bending angle columns appear only in row 1;
        remaining rows are blank for those metrics.
    Sheet "Summary": detailed per-pressure statistics.
    """
    output = io.BytesIO()

    df = compiled_df.copy()

    # ── Prepend config columns to every row (skip if already in data) ──
    for col_name, value in reversed(list(config.items())):
        if col_name not in df.columns:
            df.insert(0, col_name, value)

    # ── Compute max metrics ──
    disp_cols = [c for c in compiled_df.columns if c.endswith("_disp")]
    max_metrics: Dict[str, object] = {}
    for dc in disp_cols:
        point_name = dc.replace("_disp", "").upper()
        max_metrics[f"Max Disp {point_name} (mm)"] = round(compiled_df[dc].max(), 4)
    if "angle1" in compiled_df.columns:
        max_metrics["Max Angle1 (°)"] = round(compiled_df["angle1"].max(), 2)
    if "angle2" in compiled_df.columns:
        max_metrics["Max Angle2 (°)"] = round(compiled_df["angle2"].max(), 2)

    # Add max-metric columns (populated only in the first row)
    for col_name, value in max_metrics.items():
        col_data = [None] * len(df)
        col_data[0] = value
        df[col_name] = col_data

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Data", index=False)

        if summary_df is not None:
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

    output.seek(0)
    return output.getvalue()
