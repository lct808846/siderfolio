"""Run inside the isolated backend; no token or untrusted data is printed."""
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from astroagent.errors import ServiceError
from astroagent.plot_executor_client import ExecutorClient


class Secret:
    def get_secret_value(self):
        return Path('/run/secrets/executor_token').read_text().strip()


settings = SimpleNamespace(
    plot_executor_token=Secret(), plot_execution_enabled=True,
    plot_python_image=os.environ['ASTROAGENT_PLOT_PYTHON_IMAGE'],
    plot_gnuplot_image=os.environ['ASTROAGENT_PLOT_GNUPLOT_IMAGE'],
    plot_executor_url='http://plot-executor:8090', plot_timeout_seconds=30,
)
client = ExecutorClient(settings)
data = b'x,y\n1,2\n2,3\n'
scripts = {
    'isolation': '''import os, socket, time
assert not os.path.exists("/var/run/docker.sock")
assert not os.path.exists("/run/secrets")
assert not any(k in os.environ for k in ("DEEPSEEK_API_KEY", "ASTROAGENT_DATABASE_URL"))
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
    raise RuntimeError("network unexpectedly available")
except OSError: pass
try:
    open("/not-writable", "w")
    raise RuntimeError("root unexpectedly writable")
except OSError: pass
time.sleep(10)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.plot([1,2],[2,3])
plt.savefig("/output/figure.png")
plt.savefig("/output/figure.pdf")
''',
    'symlink': '''import os
os.symlink('/etc/passwd','/output/figure.png')
open('/output/figure.pdf','wb').write(b'%PDF-fake')
''',
    'timeout': 'import time\ntime.sleep(40)\n',
}
results = {}
for name, script in scripts.items():
    identifier = str(uuid4())
    print('running', name, identifier, flush=True)
    start = time.monotonic()
    try:
        files, runtime = client.run({'engine': 'python', 'script': script}, data, identifier, client.admit('python'))
        passed = name == 'isolation' and files['figure.png'].startswith(b'\x89PNG') and runtime['network'] == 'none'
        outcome = 'completed'
    except ServiceError as exc:
        outcome = exc.error.code
        passed = (name == 'symlink' and outcome == 'plot_output_invalid') or (name == 'timeout' and outcome in ('plot_script_failed', 'plot_execution_timeout'))
    results[name] = {'passed': passed, 'outcome': outcome, 'seconds': round(time.monotonic()-start,2), 'run_id': identifier}
    print('result', name, 'passed' if passed else 'failed', outcome, flush=True)
print('results_json', json.dumps(results), flush=True)
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
