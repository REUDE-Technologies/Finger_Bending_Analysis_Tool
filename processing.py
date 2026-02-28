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
import re
import zipfile
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
def calculate_angle_at_vertex(
    vertex_x: float,
    vertex_y: float,
    ray1_x: float,
    ray1_y: float,
    ray2_x: float,
    ray2_y: float,
) -> float:
    """
    Calculate angle at vertex formed by rays to ray1 and ray2.

    Uses atan-based formula. Returns angle in degrees [0, 180].
    """
    numerator = (
        ray1_y * (vertex_x - ray2_x)
        + vertex_y * (ray2_x - ray1_x)
        + ray2_y * (ray1_x - vertex_x)
    )
    denominator = (
        (ray1_x - vertex_x) * (vertex_x - ray2_x)
        + (ray1_y - vertex_y) * (vertex_y - ray2_y)
    )

    if abs(denominator) < DENOMINATOR_EPSILON:
        return 90.0 if abs(numerator) > DENOMINATOR_EPSILON else 0.0

    angle_rad = math.atan(numerator / denominator)
    angle_deg = math.degrees(angle_rad)

    if angle_deg < 0:
        angle_deg += 180.0

    return angle_deg


def add_angle_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add angle1 and angle2 columns to the merged DataFrame.

    angle1: angle at P1 formed by P7-P1-P8
    angle2: angle at P2 formed by P5-P2-P6
    """
    result = df.copy()

    vertex, r1, r2 = ANGLE1_DEFINITION
    required = [f"{p}_x" for p in [vertex, r1, r2]] + [f"{p}_y" for p in [vertex, r1, r2]]
    if all(c in result.columns for c in required):
        result["angle1"] = result.apply(
            lambda r: calculate_angle_at_vertex(
                r[f"{vertex}_x"], r[f"{vertex}_y"],
                r[f"{r1}_x"], r[f"{r1}_y"],
                r[f"{r2}_x"], r[f"{r2}_y"],
            ),
            axis=1,
        )

    vertex, r1, r2 = ANGLE2_DEFINITION
    required = [f"{p}_x" for p in [vertex, r1, r2]] + [f"{p}_y" for p in [vertex, r1, r2]]
    if all(c in result.columns for c in required):
        result["angle2"] = result.apply(
            lambda r: calculate_angle_at_vertex(
                r[f"{vertex}_x"], r[f"{vertex}_y"],
                r[f"{r1}_x"], r[f"{r1}_y"],
                r[f"{r2}_x"], r[f"{r2}_y"],
            ),
            axis=1,
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

    Sheet "Data": config metadata + compiled data
    Sheet "Summary": max displacement, std dev per point
    """
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        config_df = pd.DataFrame([config])
        config_df.to_excel(writer, sheet_name="Data", index=False, startrow=0)
        compiled_df.to_excel(
            writer,
            sheet_name="Data",
            index=False,
            startrow=len(config_df) + 2,
        )

        if summary_df is not None:
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

    output.seek(0)
    return output.getvalue()


