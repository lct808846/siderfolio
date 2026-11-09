"""Probe network, host access, malicious outputs, timeout and cleanup."""
import json
from pathlib import Path
from uuid import uuid4

from astroagent.config import LocalSettings
from astroagent.errors import ServiceError
from astroagent.plot_sandbox import Sandbox

root = Path('docs/test-records/v1.3.0/acceptance/20261109T003436Z').resolve()
runner = Sandbox(LocalSettings(data_dir=root / 'isolated-jobs'))
data = b'x,y\n1,2\n2,3\n'
scripts = {
    'network_and_readonly': '''import os, socket
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
    raise RuntimeError("network unexpectedly available")
except OSError: pass
try:
    open("/not-allowed", "w")
    raise RuntimeError("root unexpectedly writable")
except OSError: pass
assert not any(name in os.environ for name in ("DEEPSEEK_API_KEY", "ASTROAGENT_DATABASE_URL"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.plot([1, 2], [2, 3])
plt.savefig("/output/figure.png")
plt.savefig("/output/figure.pdf")
''',
    'symlink_output': '''import os
os.symlink('/etc/passwd', '/output/figure.png')
open('/output/figure.pdf','wb').write(b'%PDF-fake')
''',
    'timeout': 'import time\ntime.sleep(40)\n',
}
results = {}
for name, script in scripts.items():
    identifier = str(uuid4())
    try:
        runner.run({'engine': 'python', 'script': script}, data, identifier, runner.admit('python'))
        passed = name == 'network_and_readonly'
        outcome = 'completed'
    except ServiceError as exc:
        passed = (name == 'symlink_output' and exc.error.code == 'plot_output_invalid') or (
            name == 'timeout' and exc.error.code in ('plot_script_failed', 'plot_execution_timeout')
        )
        outcome = exc.error.code
    try:
        runner.call('inspect', 'astroagent-plot-' + identifier)
        cleaned = False
    except ServiceError:
        cleaned = True
    results[name] = {'passed': passed and cleaned, 'outcome': outcome, 'container_removed': cleaned}
    print(name, 'passed' if results[name]['passed'] else 'failed', flush=True)
    (root / 'sandbox-security.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
raise SystemExit(0 if all(value['passed'] for value in results.values()) else 1)
