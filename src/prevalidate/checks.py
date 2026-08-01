"""
Each check is a plain function: (report, allocated) -> list[Finding].
Keeping them as small, independent functions makes it easy to add more
later (per-cluster policies, site-specific quirks, etc.) without touching
the core runner.
"""
from __future__ import annotations

from typing import List, Optional

from .report import Report, Finding


THREAD_ENV_VARS = ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"]


def check_memory(report: Report, cpus_allocated: Optional[int], mem_allocated_gb: Optional[float]) -> List[Finding]:
    findings = []
    peak_gb = report.peak_rss_bytes / 1e9
    if mem_allocated_gb is not None:
        if peak_gb > mem_allocated_gb:
            findings.append(Finding(
                "critical", "memory",
                f"Peak memory ({peak_gb:.2f} GB) exceeded the declared allocation ({mem_allocated_gb:.2f} GB) "
                f"during this dry run — a full-scale run is likely to be OOM-killed.",
                suggestion=f"Request at least {peak_gb * 1.3:.1f} GB (peak + ~30% margin), "
                           f"or profile with representative input size if this run used reduced/synthetic data."
            ))
        elif peak_gb < 0.3 * mem_allocated_gb:
            findings.append(Finding(
                "info", "memory",
                f"Peak memory ({peak_gb:.2f} GB) was well under the declared allocation "
                f"({mem_allocated_gb:.2f} GB).",
                suggestion="Consider requesting less memory so the job can schedule faster / leave more for others, "
                           "unless this dry run used a smaller-than-real input."
            ))
    return findings


def check_process_thread_oversubscription(report: Report, cpus_allocated: Optional[int]) -> List[Finding]:
    findings = []
    total = report.peak_total_threads
    n_procs = report.peak_n_processes
    max_single = report.peak_threads_single_process

    if n_procs > 1 and max_single > 1:
        findings.append(Finding(
            "warning", "parallelism",
            f"Detected {n_procs} processes AND multi-threading within at least one process "
            f"(up to {max_single} threads/process). This is the classic 'nested parallelism' "
            f"pattern (e.g. multiprocessing/parallel-library combined with a threaded BLAS/OpenMP "
            f"library) that can oversubscribe CPUs by n_processes x n_threads.",
            suggestion=f"Set {', '.join(THREAD_ENV_VARS[:2])} etc. to 1 inside worker processes, "
                       f"or explicitly cap threads-per-process so processes x threads <= allocated CPUs."
        ))

    if cpus_allocated is not None and total > cpus_allocated:
        findings.append(Finding(
            "critical", "parallelism",
            f"Peak total thread count ({total}) exceeds the declared CPU allocation ({cpus_allocated}). "
            f"This will oversubscribe the node/cgroup and slow down (or interfere with neighbours on) "
            f"shared nodes.",
            suggestion="Reduce internal parallelism (env vars above, or library-specific thread settings) "
                       "or increase --cpus-per-task to match actual usage."
        ))
    return findings


def check_gpu(report: Report, gpu_allocated: bool) -> List[Finding]:
    findings = []
    used_gpu = report.peak_gpu_mem_bytes > 0
    if used_gpu and not gpu_allocated:
        findings.append(Finding(
            "critical", "gpu",
            "GPU memory usage was detected during the dry run, but no GPU allocation was declared.",
            suggestion="Add a GPU request (e.g. --gres=gpu:1) to the Slurm submission, or confirm this "
                       "was unintentional GPU initialization (e.g. a library defaulting to CUDA)."
        ))
    if gpu_allocated and not used_gpu:
        findings.append(Finding(
            "info", "gpu",
            "A GPU allocation was declared, but no GPU memory usage was observed during this dry run.",
            suggestion="Confirm the code path that uses the GPU is actually exercised by this dry-run input; "
                       "otherwise you may be requesting a GPU allocation you don't need."
        ))
    return findings


def check_network(report: Report) -> List[Finding]:
    findings = []
    if report.peak_external_connections > 0:
        findings.append(Finding(
            "warning", "network",
            f"Detected connection(s) to external (non-private) IP addresses "
            f"({report.peak_external_connections} at peak). Many cluster compute nodes have no "
            f"internet access, so calls like pip installs, dataset/model downloads, or API calls "
            f"made at runtime may hang or fail on the real cluster even though they worked here.",
            suggestion="Move downloads/installs to the login node or a build step before submission, "
                       "and cache data on shared/scratch storage."
        ))
    return findings


def check_open_files(report: Report, warn_threshold: int = 200) -> List[Finding]:
    findings = []
    if report.peak_open_files > warn_threshold:
        findings.append(Finding(
            "warning", "io",
            f"Peak open file handle count was high ({report.peak_open_files}). If this reflects many small "
            f"files being opened rapidly, it can be a metadata-heavy access pattern that performs poorly on "
            f"shared parallel filesystems.",
            suggestion="Consider batching small files (e.g. into HDF5/tar/zip/Parquet) or staging data to "
                       "local/fast scratch instead of many small reads on shared storage."
        ))
    return findings


def check_runtime(report: Report, timeout_used: Optional[float]) -> List[Finding]:
    findings = []
    if report.timed_out:
        findings.append(Finding(
            "info", "runtime",
            f"The dry run was still executing after the {timeout_used}s dry-run timeout and was terminated. "
            f"This is expected for long/full-scale tasks; treat the reported peaks as a lower bound, not final "
            f"values.",
            suggestion="For a fuller picture, dry-run with a reduced input/iteration count that finishes "
                       "naturally, then extrapolate."
        ))
    elif report.exit_code not in (0, None):
        findings.append(Finding(
            "warning", "runtime",
            f"The dry run exited with a non-zero exit code ({report.exit_code}). If this is not expected "
            f"under normal/full-scale conditions, investigate before submitting to the cluster.",
        ))
    return findings


ALL_CHECKS = [
    check_memory,
    check_process_thread_oversubscription,
    check_gpu,
    check_network,
    check_open_files,
    check_runtime,
]
