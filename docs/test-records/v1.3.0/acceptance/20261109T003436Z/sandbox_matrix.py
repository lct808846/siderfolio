"""Run four synthetic chart kinds in each real isolation image."""
import json
import traceback
from pathlib import Path
from uuid import uuid4

from astroagent.config import LocalSettings
from astroagent.plot_sandbox import Sandbox

root = Path('docs/test-records/v1.3.0/acceptance/20261109T003436Z').resolve()
runner = Sandbox(LocalSettings(data_dir=root / 'isolated-jobs'))
data = b'x,y,err\n1,2,0.1\n2,4,0.2\n3,3,0.3\n4,5,0.4\n'
py_actions = {
    'scatter': 'plt.scatter(x, y)', 'line': 'plt.plot(x, y)',
    'histogram': 'plt.hist(y, bins=3)', 'errorbar': 'plt.errorbar(x, y, yerr=e)',
}
gnu_actions = {
    'scatter': 'using 1:2 with points', 'line': 'using 1:2 with lines',
    'histogram': 'using 2:(1.0) smooth frequency with boxes',
    'errorbar': 'using 1:2:3 with yerrorbars',
}
results = {}
for engine in ('python', 'gnuplot'):
    for chart in py_actions:
        if engine == 'python':
            script = '''import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
with open("/input/data.csv", newline="") as f: rows = list(csv.DictReader(f))
x = [float(r["x"]) for r in rows]
y = [float(r["y"]) for r in rows]
e = [float(r["err"]) for r in rows]
''' + py_actions[chart] + '''
plt.savefig("/output/figure.png")
plt.savefig("/output/figure.pdf")
'''
        else:
            script = """set datafile separator comma
set terminal pngcairo size 640,480
set output '/output/figure.png'
plot '/input/data.csv' every ::1 """ + gnu_actions[chart] + """ notitle
set terminal pdfcairo
set output '/output/figure.pdf'
replot
"""
        key = engine + '-' + chart
        try:
            files, _ = runner.run({'engine': engine, 'script': script}, data, str(uuid4()), runner.admit(engine))
            results[key] = {'passed': True, 'png_bytes': len(files['figure.png']), 'pdf_bytes': len(files['figure.pdf'])}
        except Exception as exc:
            results[key] = {'passed': False, 'message': str(exc), 'diagnostic': getattr(exc, 'plot_diagnostic', None), 'traceback': traceback.format_exc()}
        print(key, 'passed' if results[key]['passed'] else 'failed', flush=True)
        (root / 'sandbox-matrix.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
