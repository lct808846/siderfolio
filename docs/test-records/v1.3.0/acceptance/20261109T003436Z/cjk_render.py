"""Rerun saved, real-model scripts against synthetic data with Chinese fonts."""
import json
import traceback
from pathlib import Path
from uuid import uuid4

from astroagent.config import LocalSettings
from astroagent.plot_sandbox import Sandbox

root = Path('docs/test-records/v1.3.0/acceptance/20261109T003436Z').resolve()
runner = Sandbox(LocalSettings(data_dir=root / 'isolated-jobs'))
data = b'x,y\n1,2\n2,4\n3,3\n4,5\n'
results = {}
for engine, suffix in (('python', 'py'), ('gnuplot', 'plt')):
    try:
        script = (root / f'model-script.{suffix}').read_text(encoding='utf-8')
        files, _ = runner.run({'engine': engine, 'script': script}, data, str(uuid4()), runner.admit(engine))
        (root / f'{engine}-chinese.png').write_bytes(files['figure.png'])
        results[engine] = {'passed': True, 'png_bytes': len(files['figure.png'])}
    except Exception as exc:
        results[engine] = {'passed': False, 'message': str(exc), 'diagnostic': getattr(exc, 'plot_diagnostic', None), 'traceback': traceback.format_exc()}
    print(engine, 'passed' if results[engine]['passed'] else 'failed', flush=True)
(root / 'cjk-render.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
