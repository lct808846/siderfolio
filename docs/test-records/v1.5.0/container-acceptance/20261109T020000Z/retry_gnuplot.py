"""Retry a synthetic Gnuplot plan after improving terminal syntax guidance."""
import io
import json
import time
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import requests

base = 'http://127.0.0.1:5173'
session = requests.Session()
session.trust_env = False
root = Path(__file__).parent
started = time.monotonic()
result = {}
try:
    projects = session.get(base + '/api/v1/projects', timeout=10).json()
    project = next(value for value in projects if value['name'].startswith('容器验收合成项目'))
    prefix = '/api/v1/projects/' + project['id'] + '/plotting'
    page = session.get(base + prefix, timeout=10).json()
    for op in page['operations']:
        if op['kind'] == 'plan' and (op.get('proposal') or {}).get('engine') == 'gnuplot':
            (root / 'gnuplot-first-model-script.plt').write_text(op['proposal']['script'], encoding='utf8')
    dataset = page['datasets'][0]['id']
    model = session.get(base + '/api/v1/models', timeout=10).json()['default_model']
    plan_id, run_id = str(uuid4()), str(uuid4())
    response = session.put(base + prefix + '/plans/' + plan_id, json={
        'dataset_id': dataset, 'model_id': model, 'engine': 'gnuplot',
        'question': '用 x、y 绘制散点图，无筛选无单位，标题使用中文。', 'confirm_external_data': True,
    }, timeout=180)
    response.raise_for_status()
    plan = response.json()
    assert plan['state'] == 'completed' and plan['proposal']['engine'] == 'gnuplot', plan.get('error')
    (root / 'gnuplot-retry-model-script.plt').write_text(plan['proposal']['script'], encoding='utf8')
    response = session.put(base + prefix + '/runs/' + run_id,
                           json={'plan_id': plan_id, 'confirm_execute': True}, timeout=180)
    response.raise_for_status()
    operation = response.json()
    assert operation['state'] == 'completed', operation.get('error')
    names = ['figure.png', 'figure.pdf', 'data.csv', 'script.plt']
    files = {name: session.get(base + prefix + '/runs/' + run_id + '/files/' + name, timeout=20).content for name in names}
    assert files['figure.png'].startswith(b'\x89PNG') and files['figure.pdf'].startswith(b'%PDF-')
    bundle = session.post(base + prefix + '/runs/' + run_id + '/bundle', json={'files': names}, timeout=20)
    bundle.raise_for_status()
    with ZipFile(io.BytesIO(bundle.content)) as archive:
        assert all(archive.read(name) == content for name, content in files.items())
    (root / 'container-gnuplot.png').write_bytes(files['figure.png'])
    result = {'passed': True, 'run_id': run_id, 'bundle_matches': True,
              'isolation': operation['runtime']['isolation']}
except Exception as exc:
    result = {'passed': False, 'error': str(exc)}
result['seconds'] = round(time.monotonic() - started, 2)
(root / 'gnuplot-retry.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print('gnuplot_retry', 'passed' if result['passed'] else 'failed', flush=True)
raise SystemExit(0 if result['passed'] else 1)
