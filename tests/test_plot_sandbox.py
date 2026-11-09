"""Output must be collected before container tmpfs is destroyed."""

import io
import json
import struct
import tarfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

from astroagent.errors import ServiceError
from astroagent.plot_sandbox import Sandbox


def output_archive(*, link=False):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 2, 2)
    items = {
        "status.json": b'{"exit_code": 0}',
        "runtime.json": b'{"engine":"python"}',
        "figure.png": png,
        "figure.pdf": b"%PDF-synthetic",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in items.items():
            entry = tarfile.TarInfo(name)
            if name == "figure.png" and link:
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/etc/passwd"
                archive.addfile(entry)
            else:
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
    return buffer.getvalue()


@pytest.mark.parametrize("malicious", [False, True])
def test_streamed_container_output_and_cleanup(tmp_path, monkeypatch, malicious):
    runner = Sandbox(SimpleNamespace(data_dir=tmp_path, plot_timeout_seconds=30))
    actions = []
    details = [
        {
            "Image": "image-id",
            "Config": {"User": "65532:65532"},
            "HostConfig": {
                "NetworkMode": "none",
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges=true"],
                "ReadonlyRootfs": True,
                "Memory": 256 * 1024**2,
                "MemorySwap": 256 * 1024**2,
                "PidsLimit": 32,
                "NanoCpus": 1000000000,
            },
            "Mounts": [{"Type": "bind", "RW": False, "Destination": "/input"}],
        }
    ]

    def call(*args, timeout=10):
        actions.append(args)
        if args[0] == "inspect":
            return json.dumps(details).encode()
        if args[:2] == ("start", "--attach"):
            return output_archive(link=malicious)
        return b""

    monkeypatch.setattr(runner, "call", call)
    args = (
        {"engine": "python", "script": "pass"},
        b"x\n1\n",
        str(uuid4()),
        ("image-id", "image-id"),
    )
    if malicious:
        with pytest.raises(ServiceError) as exc:
            runner.run(*args)
        assert exc.value.error.code == "plot_output_invalid"
    else:
        files, _ = runner.run(*args)
        assert files["figure.png"].startswith(b"\x89PNG")
        assert files["figure.pdf"].startswith(b"%PDF-")
    assert any(action[:2] == ("start", "--attach") for action in actions)
    assert actions[-1][:2] == ("rm", "--force")
