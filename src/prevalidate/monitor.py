"""
ProcessTreeMonitor polls a process and all of its descendants at a fixed
interval and records memory, thread, file-handle, and network-connection
usage over time. This is what makes prevalidate language-agnostic: it
watches the OS-level process tree, not the language runtime, so it works
the same whether the wrapped command is Python, R, MATLAB, a compiled
binary, or an MPI launcher.
"""

from __future__ import annotations

import ipaddress
import threading
import time

import psutil

from .report import Snapshot

try:
    import pynvml

    _HAVE_NVML = True
except ImportError:
    _HAVE_NVML = False


def _is_external(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local)


def _gpu_mem_bytes() -> int:
    """Best-effort total GPU memory used, summed across visible GPUs.
    Returns 0 if pynvml/nvidia-ml-py isn't available (e.g. no GPU node,
    no driver). Swap/extend this for ROCm (AMD) as needed.
    """
    if not _HAVE_NVML:
        return 0
    try:
        pynvml.nvmlInit()
        total = 0
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            total += pynvml.nvmlDeviceGetMemoryInfo(h).used
        pynvml.nvmlShutdown()
        return total
    except Exception:
        return 0


class ProcessTreeMonitor:
    def __init__(self, pid: int, interval: float = 0.2):
        self.pid = pid
        self.interval = interval
        self.snapshots: list[Snapshot] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = time.monotonic()

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5 * self.interval)

    def _run(self) -> None:
        while not self._stop.is_set():
            snap = self._sample()
            if snap is not None:
                self.snapshots.append(snap)
            self._stop.wait(self.interval)

    def _sample(self) -> Snapshot | None:
        try:
            root = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return None

        try:
            procs = [root] + root.children(recursive=True)
        except psutil.NoSuchProcess:
            return None

        total_rss = 0
        total_threads = 0
        threads_per_process = []
        open_files = 0
        external_conns = 0

        for p in procs:
            try:
                total_rss += p.memory_info().rss
                nt = p.num_threads()
                total_threads += nt
                threads_per_process.append(nt)
                open_files += len(p.open_files())
                for c in p.net_connections(kind="inet"):
                    if c.raddr and _is_external(c.raddr.ip):
                        external_conns += 1
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                continue

        return Snapshot(
            t=time.monotonic() - self._t0,
            n_processes=len(procs),
            total_threads=total_threads,
            threads_per_process=threads_per_process,
            rss_bytes=total_rss,
            open_files=open_files,
            external_connections=external_conns,
            gpu_mem_bytes=_gpu_mem_bytes(),
        )
