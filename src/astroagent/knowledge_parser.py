"""有超时/内存/输出上限的离线提取器；不支持的保护方式明确失败。"""

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from astroagent.errors import ServiceError
from astroagent.project_archives import strict_json


def windows_job(process, memory_bytes=768 * 1024**2):
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t),
            ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class Counters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", Counters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("Job object unavailable")
    limits = Extended()
    limits.basic.flags = 0x2000 | 0x100 | 0x200  # kill-on-close, process and job memory
    limits.process_memory = limits.job_memory = memory_bytes
    if not kernel.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        kernel.CloseHandle(job)
        raise OSError("Cannot impose parser limits")
    return lambda: kernel.CloseHandle(job)


def parse_document(content, media):
    if os.name != "nt" and not sys.platform.startswith("linux"):
        raise ServiceError(503, "knowledge_parser_unavailable", "当前平台不能实施解析资源限制。")
    environment = {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if key in os.environ
    }
    process, close_job, temporary = None, None, None
    try:
        temporary = tempfile.TemporaryDirectory(prefix="astroagent-parser-")
        root = Path(temporary.name)
        source, target = root / "input", root / "result.json"
        source.write_bytes(content)
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("knowledge_worker.py")),
                str(source),
                media,
                str(target),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            cwd=root,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if os.name == "nt":
            close_job = windows_job(process)
        process.communicate(input=b"1", timeout=30)
        if process.returncode == 3:
            raise ServiceError(
                503, "knowledge_parser_limits_unavailable", "无法实施所需资源限制，未读取用户文件。"
            )
        if process.returncode or not target.is_file() or target.stat().st_size > 64 * 1024**2:
            raise ServiceError(
                422,
                "knowledge_parser_resource_limit",
                "提取进程未完成，可能超过时间、内存或输出限制；原文件保留。",
            )
        result = strict_json(target.read_bytes())
        if not result.get("ok"):
            code = result.get("error", "extraction_failed")
            raise ServiceError(
                503 if code.endswith("unavailable") else 422,
                "knowledge_" + code,
                "文件未能解析，错误代码已记录；原文件保留，未执行OCR或自动重试。",
            )
        return result
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(
            422, "knowledge_parser_timeout", "解析超过30秒，已终止子进程；原文件保留。"
        ) from exc
    except (OSError, ValueError) as exc:
        raise ServiceError(
            503, "knowledge_parser_unavailable", "无法实施受限解析或读取结果，未取消资源保护。"
        ) from exc
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        if close_job is not None:
            close_job()
        if temporary is not None:
            temporary.cleanup()
