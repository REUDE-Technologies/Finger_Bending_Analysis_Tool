"""
Features tab — documentation of computed feature names and physics equations.
Equations are shown as images for clarity and visibility.
"""
import io
from pathlib import Path

import streamlit as st
from styles import section

# Directory for pre-generated equation images (run scripts/generate_equation_images.py to create)
_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "equations"

# (feature_name, image_filename, equation_latex_for_fallback, units_notes)
_FEATURE_EQUATIONS = [
    ("Displacement", "displacement.png", r"$d = \sqrt{(x - x_0)^2 + (y - y_0)^2}$",
     "mm — Euclidean distance from initial position (x₀, y₀) at each time step."),
    ("Angle 1 & 2", "angle.png", r"$\theta = \arctan(|\mathbf{a} \times \mathbf{b}| / (\mathbf{a} \cdot \mathbf{b}))$",
     "° (degrees) — Interior angle at vertex. Angle 1: P7–P1–P8; Angle 2: P5–P2–P6."),
    ("Contact arc length", "arc_length.png", r"$L = \sum_i \sqrt{(x_{i+1}-x_i)^2 + (y_{i+1}-y_i)^2}$",
     "mm — Sum of segment lengths along points P8→P7→P6→P5→P4."),
    ("Contact area", "area.png", r"$A = L \times w$",
     "mm² — Arc length L × finger width w."),
    ("Contact force", "force.png", r"$F = P \cdot A$  (P in Pa, A in m²)",
     "N — Pressure × area with unit conversion (1 kPa = 1000 Pa, 1 mm² = 10⁻⁶ m²)."),
    ("Tip work", "work.png", r"$\mathrm{d}W = F \,\mathrm{d}(\mathrm{disp})$  (cumulative)",
     "N·mm — Incremental work at tip; summed per pressure level."),
    ("Tip stiffness", "stiffness.png", r"$k = F / d$",
     "N/mm — Force divided by displacement at the tip."),
    ("Speed", "speed.png", r"$v = \mathrm{displacement} / \mathrm{time}$",
     "mm/s — Per tracking point. Time = 0 → value omitted (no division by zero)."),
]


def _equation_image_from_latex(latex_str: str, dpi: int = 300) -> bytes | None:
    """Render a LaTeX/math string to PNG bytes. Returns None if matplotlib unavailable."""
    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 1.0))
        ax.set_facecolor("white")
        fig.patch.set_facecolor("white")
        ax.axis("off")
        ax.text(0.5, 0.5, latex_str, fontsize=26, color="black", ha="center", va="center", transform=ax.transAxes)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0.3, facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _show_image(source, *, width_stretch=True):
    """Show image; use width='stretch' (Streamlit 1.29+) or no arg for older versions."""
    if width_stretch:
        try:
            st.image(source, width="stretch")
            return
        except TypeError:
            pass
    st.image(source)


def render_features_tab():
    """Render the Features tab: feature names and physics equations as images."""
    section("📐", "teal", "Feature Definitions",
            "Computed features and the physics equations used in this tool")

    for name, img_name, latex, notes in _FEATURE_EQUATIONS:
        with st.container(border=True):
            st.markdown(f"**{name}**")
            img_path = _ASSETS_DIR / img_name
            if img_path.is_file():
                _show_image(str(img_path))
            else:
                img_bytes = _equation_image_from_latex(latex)
                if img_bytes:
                    _show_image(img_bytes)
                else:
                    try:
                        st.latex(latex.strip("$"))
                    except Exception:
                        st.code(latex, language="latex")
            st.caption(notes)

    st.markdown("---")
    st.markdown("**Column naming:** Displacement: `p1_disp`, `p2_disp`, …; Speed: `p1_speed`, `p2_speed`, …; Angles: `angle1`, `angle2`. Geometry: `Contact Arc Length (mm)`, `Contact Area (mm²)`, `Contact Force (N)`, `Tip Stiffness (N/mm)`, `Tip Work (N·mm)`.")
