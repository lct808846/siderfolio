"""Synthetic, explicitly confirmed acceptance against the independent Compose stack."""
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import requests

root = Path(__file__).parent
session = requests.Session()
session.trust_env = False
base = 'http://127.0.0.1:5173'
results = {}


def call(method, path, **kwargs):
    response = session.request(method, base + path, timeout=180, **kwargs)
    if response.status_code >= 400:
        try:
            code = response.json().get('error', {}).get('code', 'http_error')
        except ValueError:
            code = 'invalid_json'
        raise RuntimeError(f'{method} {path}: HTTP {response.status_code} {code}')
    return response


def check(name, action):
    started = time.monotonic()
    try:
        value = action()
        results[name] = {'passed': True, 'seconds': round(time.monotonic() - started, 2), 'detail': value}
    except Exception as exc:
        results[name] = {'passed': False, 'seconds': round(time.monotonic() - started, 2), 'error': str(exc)}
    print(name, 'passed' if results[name]['passed'] else 'failed', flush=True)
    (root / 'container-smoke.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')


status = call('GET', '/api/v1/setup/status').json()
if status.get('deployment_mode') != 'container' or not status.get('ready'):
    raise SystemExit('Refusing acceptance: independent container database is not ready')
project = call('POST', '/api/v1/projects', json={'name': '容器验收合成项目 ' + str(uuid4())[:8]}).json()
project_root = '/api/v1/projects/' + project['id']
model = call('GET', '/api/v1/models').json()['default_model']


def security():
    bad_host = session.get(base + '/health', headers={'Host': 'untrusted.example'}, timeout=5)
    bad_origin = session.get(base + '/api/v1/setup/status', headers={'Origin': 'https://untrusted.example'}, timeout=5)
    assert bad_host.status_code == 400 and bad_origin.status_code == 403
    return {'invalid_host': bad_host.status_code, 'invalid_origin': bad_origin.status_code}


def chat():
    c = call('POST', '/api/v1/conversations', json={'title': '容器合成会话'}).json()
    t = call('POST', '/api/v1/conversations/' + c['id'] + '/turns', json={
        'message': '请仅回复：合成测试通过。', 'client_request_id': str(uuid4()), 'expected_revision': 0,
        'model': model,
    }).json()
    assert t.get('execution_status') == 'completed'
    return {'conversation_id': c['id'], 'state': t.get('execution_status')}


def rag():
    rev = call('GET', project_root).json()['revision']
    doc = call('POST', project_root + '/documents', files={'file': ('synthetic.md', b'# Synthetic\nBinary cluster environment synthetic fixture.\n', 'text/markdown')},
               data={'options': json.dumps({'expected_revision': rev, 'client_request_id': str(uuid4())})}).json()
    assert doc['document']['state'] == 'ready'
    rev = call('GET', project_root).json()['revision']
    index = call('POST', project_root + '/rag/indexes', json={'client_request_id': str(uuid4()), 'expected_revision': rev, 'confirmed': True}).json()
    assert index['state'] == 'ready'
    preview = call('POST', project_root + '/rag/previews', json={'question': 'binary cluster', 'document_ids': [], 'version_ids': [], 'history_ids': []}).json()
    assert preview['evidence'] and preview['semantic_status'] == 'ready'
    answer = call('POST', project_root + '/rag/answers', json={
        'client_request_id': str(uuid4()), 'preview_id': preview['id'],
        'confirmation_token': preview['confirmation_token'], 'confirmed': True,
    }).json()
    assert answer['record']['state'] == 'completed'
    return {'index_state': index['state'], 'semantic_status': preview['semantic_status'], 'evidence_count': len(preview['evidence']), 'answer_state': answer['record']['state']}


def plotting(engine):
    setup = call('POST', '/api/v1/setup/plotting', json={'confirm_create_tables': True}).json()
    assert setup['storage_ready'] and setup['execution_configured']
    plot = project_root + '/plotting'
    dataset_id, plan_id, run_id = (str(uuid4()) for _ in range(3))
    call('PUT', plot + '/datasets/' + dataset_id + '/upload', files={'file': ('synthetic.csv', b'x,y\n1,2\n2,4\n3,3\n4,5\n', 'text/csv')})
    plan = call('PUT', plot + '/plans/' + plan_id, json={'dataset_id': dataset_id, 'model_id': model,
        'engine': engine, 'question': '以 x 为横轴、y 为纵轴绘制散点图，不筛选数据，坐标无单位。',
        'confirm_external_data': True}).json()
    assert plan['state'] == 'completed' and plan['proposal']['engine'] == engine, plan.get('error')
    run = call('PUT', plot + '/runs/' + run_id, json={'plan_id': plan_id, 'confirm_execute': True}).json()
    assert run['state'] == 'completed', run.get('error')
    names = ['figure.png', 'figure.pdf', 'data.csv', 'script.' + ('py' if engine == 'python' else 'plt')]
    files = {name: call('GET', plot + '/runs/' + run_id + '/files/' + name).content for name in names}
    assert files['figure.png'].startswith(b'\x89PNG') and files['figure.pdf'].startswith(b'%PDF-')
    bundle = call('POST', plot + '/runs/' + run_id + '/bundle', json={'files': names})
    with ZipFile(io.BytesIO(bundle.content)) as archive:
        assert all(archive.read(name) == data for name, data in files.items())
    return {'run_id': run_id, 'png_sha256': hashlib.sha256(files['figure.png']).hexdigest(), 'bundle_matches': True, 'isolation': run['runtime'].get('isolation')}


check('host_origin', security)
check('chat', chat)
check('rag', rag)
for value in ('python', 'gnuplot'):
    check('plot_' + value, lambda value=value: plotting(value))
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
