from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes
from functools import cache
from typing import Any, ClassVar

CREATE_NO_WINDOW = 0x08000000
KILL_ON_JOB_CLOSE = 0x00002000
EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class BasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
    _fields_: ClassVar[list[Any]] = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):  # IO_COUNTERS
    _fields_: ClassVar[list[Any]] = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class ExtendedLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_: ClassVar[list[Any]] = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


@cache
def kernel32() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    signatures = {
        "CreateJobObjectW": ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = argtypes, restype
    return api


def own(pid: int) -> int | None:
    """
    A Job Object holding the process ``pid`` and every process it starts from now on; ``None`` when the system
    refuses. Closing the handle ends the processes still in it, and so does the death of this process.
    """
    api = kernel32()
    job = api.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE
    process = None
    held = bool(
        api.SetInformationJobObject(job, EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits))
    )
    if held:
        process = api.OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA, False, pid)
        held = bool(process) and bool(api.AssignProcessToJobObject(job, process))
    if process:
        api.CloseHandle(process)
    if not held:
        api.CloseHandle(job)
        return None
    return int(job)


def terminate(job: int) -> bool:
    """End every process in the job."""
    return bool(kernel32().TerminateJobObject(job, 1))


def close(job: int) -> None:
    kernel32().CloseHandle(job)


def taskkill(pid: int) -> None:
    """End the process ``pid`` and the processes below it in the process table."""
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
