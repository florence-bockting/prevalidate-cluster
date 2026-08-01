from __future__ import annotations

import subprocess
import time
from typing import List, Optional, Sequence, Union

from .monitor import ProcessTreeMonitor
from .report import Report, Snapshot
from .checks import (
    check_memory,
    check_process_thread_oversubscription,
    check_gpu,
    check_network,
    check_open_files,
    check_runtime,
)

CommandLike = Union[str, Sequence[str]]


def _aggregate(report: Report) -> None:
    if not report.snapshots:
        return
    report.peak_rss_bytes = max(s.rss_bytes for s in report.snapshots)
    report.peak_n_processes = max(s.n_processes for s in report.snapshots)
    report.peak_total_threads = max(s.total_threads for s in report.snapshots)
    report.peak_threads_single_process = max(
        (max(s.threads_per_process) if s.threads_per_process else 0) for s in report.snapshots
    )
    report.peak_open_files = max(s.open_files for s in report.snapshots)
    report.peak_external_connections = max(s.external_connections for s in report.snapshots)
    report.peak_gpu_mem_bytes = max(s.gpu_mem_bytes for s in report.snapshots)


def prevalidate(
    command: CommandLike,
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: float = 60.0,
    sample_interval: float = 0.2,
    cpus_allocated: Optional[int] = None,
    mem_allocated_gb: Optional[float] = None,
    gpu_allocated: bool = False,
    print_report: bool = True,
) -> Report:
    """
    Run `command` as a subprocess, sample its whole process tree while it
    runs, and return a Report with peak resource usage and diagnostic
    Findings relevant to running this on a shared Slurm cluster.

    `command` can be a shell string or an argv list -- this is what makes
    the tool language-agnostic: it wraps any executable via the OS process
    tree, not a specific language runtime.

    Parameters mirroring Slurm allocation flags (cpus_allocated,
    mem_allocated_gb, gpu_allocated) are optional but strongly recommended:
    without them, prevalidate can only report *what happened*, not whether
    it fits your intended #SBATCH request.
    """
    is_shell = isinstance(command, str)
    t_start = time.monotonic()

    proc = subprocess.Popen(
        command,
        shell=is_shell,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    monitor = ProcessTreeMonitor(proc.pid, interval=sample_interval)
    monitor.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    finally:
        monitor.stop()

    wall_time = time.monotonic() - t_start
    cmd_str = command if is_shell else " ".join(command)

    report = Report(
        command=cmd_str,
        exit_code=proc.returncode,
        timed_out=timed_out,
        wall_time_s=wall_time,
        snapshots=monitor.snapshots,
    )
    _aggregate(report)

    for check_fn, kwargs in [
        (check_memory, dict(cpus_allocated=cpus_allocated, mem_allocated_gb=mem_allocated_gb)),
        (check_process_thread_oversubscription, dict(cpus_allocated=cpus_allocated)),
        (check_gpu, dict(gpu_allocated=gpu_allocated)),
        (check_network, dict()),
        (check_open_files, dict()),
        (check_runtime, dict(timeout_used=timeout)),
    ]:
        report.findings.extend(check_fn(report, **kwargs))

    if print_report:
        print(report.summary())

    return report
