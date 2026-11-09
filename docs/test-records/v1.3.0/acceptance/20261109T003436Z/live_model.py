"""Exercise each requested plot tool with a real model and synthetic data."""
import json
import traceback
from pathlib import Path
from uuid import uuid4

from astroagent.config import LocalSettings, Settings
from astroagent.plot_data import dataset, table
from astroagent.plot_planner import generate
from astroagent.plot_sandbox import Sandbox
from astroagent.plot_schemas import PlotPlanRequest

root = Path('docs/test-records/v1.3.0/acceptance/20261109T003436Z').resolve()
raw = b'x,y\n1,2\n2,4\n3,3\n4,5\n'
header, rows = table(raw, 'synthetic.csv')
info, data = dataset(str(uuid4()), str(uuid4()), 'synthetic.csv', raw, header, rows)
settings = Settings()
runner = Sandbox(LocalSettings(data_dir=root / 'isolated-jobs'))
results = {}
for engine in ('python', 'gnuplot'):
    request = PlotPlanRequest(dataset_id=info['id'], model_id=settings.deepseek_model,
                              engine=engine, question='使用 x 列和 y 列绘制散点图，不筛选数据，坐标无单位。',
                              confirm_external_data=True)
    try:
        proposal, usage = generate(request, info, data)
        files, metadata = runner.run(proposal, data, str(uuid4()), runner.admit(engine))
        (root / ('model-script.' + ('py' if engine == 'python' else 'plt'))).write_text(proposal['script'], encoding='utf-8')
        results[engine] = {'passed': True, 'model': settings.deepseek_model, 'usage': usage,
                           'chart': proposal['chart'], 'columns': proposal['columns'],
                           'png_bytes': len(files['figure.png']), 'pdf_bytes': len(files['figure.pdf'])}
    except Exception as exc:
        results[engine] = {'passed': False, 'exception': type(exc).__name__, 'message': str(exc),
                           'diagnostic': getattr(exc, 'plot_diagnostic', None),
                           'traceback': traceback.format_exc()}
    print(engine, 'passed' if results[engine]['passed'] else 'failed', flush=True)
    (root / 'live-model.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
