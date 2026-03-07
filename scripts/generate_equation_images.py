"""
One-off script to generate equation images for the Features tab.
Run from project root:  python scripts/generate_equation_images.py
Requires: matplotlib
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "assets" / "equations"

EQUATIONS = [
    ("displacement", r"$d = \sqrt{(x - x_0)^2 + (y - y_0)^2}$"),
    ("angle", r"$\theta = \arctan\left(\frac{|\mathbf{a} \times \mathbf{b}|}{\mathbf{a} \cdot \mathbf{b}}\right)$"),
    ("arc_length", r"$L = \sum_i \sqrt{(x_{i+1}-x_i)^2 + (y_{i+1}-y_i)^2}$"),
    ("area", r"$A = L \times w$"),
    ("force", r"$F = P \cdot A$  (P in Pa, A in m²)"),
    ("work", r"$\mathrm{d}W = F \,\mathrm{d}(\mathrm{disp})$  (cumulative)"),
    ("stiffness", r"$k = F / d$"),
    ("speed", r"$v = \frac{\mathrm{displacement}}{\mathrm{time}}$"),
]


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, latex in EQUATIONS:
        fig, ax = plt.subplots(figsize=(7, 1.0))
        ax.set_facecolor("white")
        fig.patch.set_facecolor("white")
        ax.axis("off")
        ax.text(0.5, 0.5, latex, fontsize=26, color="black", ha="center", va="center", transform=ax.transAxes)
        out_path = OUT_DIR / f"{name}.png"
        fig.savefig(out_path, format="png", dpi=300, bbox_inches="tight", pad_inches=0.3, facecolor="white")
        plt.close(fig)
        print(f"Wrote {out_path}")
    print("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)
