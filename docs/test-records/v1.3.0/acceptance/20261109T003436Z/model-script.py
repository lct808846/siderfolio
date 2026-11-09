import csv
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV_PATH = "/input/data.csv"
OUT_PNG = "/output/figure.png"
OUT_PDF = "/output/figure.pdf"

xs, ys = [], []
with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            xv = float(str(row["x"]).strip())
            yv = float(str(row["y"]).strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(xv) and math.isfinite(yv):
            xs.append(xv)
            ys.append(yv)

fig, ax = plt.subplots(figsize=(6.0, 4.5), dpi=200)
ax.scatter(xs, ys, s=36, color="#1f77b4", edgecolors="black", linewidths=0.5,
           label="数据点 (n=%d)" % len(xs))
ax.set_xlabel("x (无单位)")
ax.set_ylabel("y (无单位)")
ax.set_title("x 与 y 的散点图")
ax.grid(True, linestyle=":", linewidth=0.6, alpha=0.6)
ax.legend(loc="best", fontsize=9)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=200)
fig.savefig(OUT_PDF)
plt.close(fig)