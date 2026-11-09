"""Exercise Linux sandbox adapter with a redirected Docker Desktop socket.

The error class is a tiny stand-in so this isolated probe needs no WSL packages.
"""
import importlib.util
import json
import os
import sys
import traceback
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

root = Path('/mnt/d/project/astroagent')
evidence = root / 'docs/test-records/v1.3.0/acceptance/20261109T003436Z'
wrapper = evidence / 'wsl-bin'
wrapper.mkdir(exist_ok=True)
binary = wrapper / 'docker'
binary.write_text('''#!/usr/bin/python3
import os, sys
args = sys.argv[1:]
if args[:1] == ["--host"]: args = args[2:]
args = [arg.replace("src=/mnt/d/", "src=/run/desktop/mnt/host/d/") for arg in args]
cli = "/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker"
os.execv(cli, [cli, "--host", "unix:///mnt/wsl/docker-desktop/shared-sockets/host-services/docker.proxy.sock", *args])
''')
binary.chmod(0o755)
os.environ['PATH'] = str(wrapper) + ':' + os.environ['PATH']


class ServiceError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.error = SimpleNamespace(code=code, message=message)


fake = types.ModuleType('astroagent.errors')
fake.ServiceError = ServiceError
sys.modules['astroagent.errors'] = fake
spec = importlib.util.spec_from_file_location('wsl_plot_sandbox', root / 'src/astroagent/plot_sandbox.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
settings = SimpleNamespace(
    data_dir=evidence / 'wsl-jobs', plot_execution_enabled=True,
    plot_python_image='sha256:fd4b97c08fc6c0bb530644720111b870fed2447fb86e05d894b9837827046cfa',
    plot_gnuplot_image='sha256:606fea82eef7cd702d88f894fb4b0f4efe028c7924c44801b31319221ebb1bbc',
    plot_timeout_seconds=30, plot_docker_host='unix:///var/run/docker.sock',
)
runner = module.Sandbox(settings)
results = {}
for engine, suffix in (('python', 'py'), ('gnuplot', 'plt')):
    try:
        script = (evidence / f'model-script.{suffix}').read_text(encoding='utf-8')
        files, _ = runner.run({'engine': engine, 'script': script}, b'x,y\n1,2\n2,4\n3,3\n4,5\n', str(uuid4()), runner.admit(engine))
        results[engine] = {'passed': True, 'png_bytes': len(files['figure.png']), 'pdf_bytes': len(files['figure.pdf'])}
    except Exception as exc:
        results[engine] = {'passed': False, 'message': str(exc), 'traceback': traceback.format_exc()}
    print(engine, 'passed' if results[engine]['passed'] else 'failed', flush=True)
    (evidence / 'wsl-sandbox.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
binary.unlink()
wrapper.rmdir()
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
