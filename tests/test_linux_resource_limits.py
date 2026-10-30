"""Exercise the real Linux worker limits in disposable child processes."""

import json
import os
import signal
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux limits")


def worker(tmp_path, body, timeout=40):
    script = (
        textwrap.dedent(
            """
        import resource, sys
        from astroagent import knowledge_worker as worker
        sys.argv = ['worker', sys.argv[1], 'text/markdown', sys.argv[2]]
        def probe(path, media):
        """
        )
        + textwrap.indent(textwrap.dedent(body), "    ")
        + textwrap.dedent(
            """
        worker.extract = probe
        raise SystemExit(worker.main())
        """
        )
    )
    source = tmp_path / "input"
    source.write_text("synthetic", encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-c", script, str(source), str(tmp_path / "output.json")],
        input=b"1",
        capture_output=True,
        timeout=timeout,
        cwd=tmp_path,
    )


def test_linux_worker_memory_and_output_limits(tmp_path):
    result = worker(
        tmp_path,
        """
        assert resource.getrlimit(resource.RLIMIT_AS) == (768 * 1024**2,) * 2
        assert resource.getrlimit(resource.RLIMIT_CPU) == (25, 25)
        assert resource.getrlimit(resource.RLIMIT_FSIZE) == (64 * 1024**2,) * 2
        assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
        try:
            bytearray(800 * 1024**2)
        except MemoryError:
            pass
        else:
            raise AssertionError('address-space limit did not reject allocation')
        try:
            with open('limit-test', 'wb') as output:
                output.write(b'x' * (64 * 1024**2 + 1))
        except OSError:
            pass
        else:
            raise AssertionError('file-size limit did not reject write')
        return {'sources': []}
        """,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads((tmp_path / "output.json").read_text())["ok"] is True
    assert os.path.getsize(tmp_path / "limit-test") <= 64 * 1024**2


def test_linux_worker_cpu_limit_kills_child(tmp_path):
    result = worker(tmp_path, "while True:\n    pass\n", timeout=90)
    assert result.returncode == -signal.SIGKILL, result.stderr.decode(errors="replace")
