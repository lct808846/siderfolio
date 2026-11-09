"""Run synthetic scatter plots using the real isolated execution adapter."""
import json
import os
import traceback
from pathlib import Path
from uuid import uuid4

from astroagent.config import LocalSettings
from astroagent.plot_sandbox import Sandbox

root = Path('docs/test-records/v1.3.0/acceptance/20261109T003436Z').resolve()
settings = LocalSettings(data_dir=root / 'isolated-jobs')
runner = Sandbox(settings)
data = b'x,y\n1,2\n2,4\n3,3\n'
scripts = {
    'python': '''import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
with open("/input/data.csv", newline="") as f:
    rows = list(csv.DictReader(f))
plt.scatter([float(r["x"]) for r in rows], [float(r["y"]) for r in rows])
plt.savefig("/output/figure.png")
plt.savefig("/output/figure.pdf")
''',
    'gnuplot': '''set datafile separator comma
set terminal pngcairo size 640,480
set output '/output/figure.png'
plot '/input/data.csv' using 1:2 every ::1 with points notitle
set terminal pdfcairo
set output '/output/figure.pdf'
replot
''',
}
results = {}
for engine, script in scripts.items():
    try:
        files, metadata = runner.run({'engine': engine, 'script': script}, data, str(uuid4()), runner.admit(engine))
        (root / (engine + '-scatter.png')).write_bytes(files['figure.png'])
        results[engine] = {'passed': True, 'png_bytes': len(files['figure.png']), 'pdf_bytes': len(files['figure.pdf']), 'runtime': metadata}
    except Exception as exc:
        results[engine] = {'passed': False, 'exception': type(exc).__name__, 'code': getattr(exc, 'code', None), 'message': str(exc), 'diagnostic': getattr(exc, 'plot_diagnostic', None), 'traceback': traceback.format_exc()}
    print(engine, 'passed' if results[engine]['passed'] else 'failed', flush=True)
(root / 'sandbox-check.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
raise SystemExit(0 if all(x['passed'] for x in results.values()) else 1)
