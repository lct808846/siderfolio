"""Read IPv4 TCP listeners from the Windows IP Helper API."""

import ctypes
import socket
from ctypes import wintypes


def listeners(port):
    class Row(ctypes.Structure):
        _fields_ = [
            (name, wintypes.DWORD)
            for name in ("state", "address", "port", "remote_address", "remote_port", "pid")
        ]

    api = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
    fn = api.GetExtendedTcpTable
    fn.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.ULONG),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    fn.restype = wintypes.DWORD
    size = wintypes.ULONG(0)
    result = fn(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    if result != 122:
        raise OSError(result, "GetExtendedTcpTable sizing failed")
    for _ in range(5):
        buffer = ctypes.create_string_buffer(size.value)
        result = fn(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result == 0:
            count = wintypes.DWORD.from_buffer(buffer).value
            rows = (Row * count).from_buffer(buffer, ctypes.sizeof(wintypes.DWORD))
            return [
                {"port": socket.ntohs(row.port & 0xFFFF), "pid": row.pid, "state": row.state}
                for row in rows
                if socket.ntohs(row.port & 0xFFFF) == port
            ]
        if result != 122:
            raise OSError(result, "GetExtendedTcpTable failed")
    raise OSError("GetExtendedTcpTable size changed repeatedly")
