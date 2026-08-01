"""
Each check is a plain function: (report, allocation) -> list[Finding].
Keeping them as small, independent functions makes it easy to add more
later (per-cluster policies, site-specific quirks, etc.) without touching
the core runner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .report import Finding, Report

THREAD_ENV_VARS = [
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
]

OPEN_FILES_WARN_THRESHOLD = 200


@dataclass
class Allocation:
    """User-declared resource request, mirroring typical Slurm flags."""

    cpus: int | None = None
    mem_gb: float | None = None
    gpu: bool = False
    timeout_s: float | None = None


CheckFn = Callable[[Report, Allocation], list[Finding]]


def check_memory(report: Report, alloc: Allocation) -> list[Finding]:
    findings = []
    peak_gb = report.peak_rss_bytes / 1e9
    if alloc.mem_gb is not None:
        if peak_gb > alloc.mem_gb:
            findings.append(
                Finding(
                    "critical",
                    "memory",
                    f"Peak memory ({peak_gb:.2f} GB) exceeded the declared "
                    f"allocation ({alloc.mem_gb:.2f} GB) during this dry run — "
                    f"a full-scale run is likely to be OOM-killed.",
                    suggestion=(
                        f"Request at least {peak_gb * 1.3:.1f} GB "
                        f"(peak + ~30% margin), or profile with representative "
                        f"input size if this run used reduced/synthetic data."
                    ),
                )
            )
        elif peak_gb < 0.3 * alloc.mem_gb:
            findings.append(
                Finding(
                    "info",
                    "memory",
                    f"Peak memory ({peak_gb:.2f} GB) was well under the "
                    f"declared allocation ({alloc.mem_gb:.2f} GB).",
                    suggestion=(
                        "Consider requesting less memory so the job can "
                        "schedule faster / leave more for others, unless this "
                        "dry run used a smaller-than-real input."
                    ),
                )
            )
    return findings


def check_process_thread_oversubscription(
    report: Report, alloc: Allocation
) -> list[Finding]:
    findings = []
    total = report.peak_total_threads
    n_procs = report.peak_n_processes
    max_single = report.peak_threads_single_process

    if n_procs > 1 and max_single > 1:
        findings.append(
            Finding(
                "warning",
                "parallelism",
                f"Detected {n_procs} processes AND multi-threading within at "
                f"least one process (up to {max_single} threads/process). "
                f"This is the classic 'nested parallelism' pattern "
                f"(e.g. multiprocessing/parallel-library combined with a "
                f"threaded BLAS/OpenMP library) that can oversubscribe CPUs "
                f"by n_processes x n_threads.",
                suggestion=(
                    f"Set {', '.join(THREAD_ENV_VARS[:2])} etc. to 1 inside "
                    f"worker processes, or explicitly cap threads-per-process "
                    f"so processes x threads <= allocated CPUs."
                ),
            )
        )

    if alloc.cpus is not None and total > alloc.cpus:
        findings.append(
            Finding(
                "critical",
                "parallelism",
                f"Peak total thread count ({total}) exceeds the declared CPU "
                f"allocation ({alloc.cpus}). This will oversubscribe the "
                f"node/cgroup and slow down (or interfere with neighbours on) "
                f"shared nodes.",
                suggestion=(
                    "Reduce internal parallelism (env vars above, or "
                    "library-specific thread settings) or increase "
                    "--cpus-per-task to match actual usage."
                ),
            )
        )
    return findings


def check_gpu(report: Report, alloc: Allocation) -> list[Finding]:
    findings = []
    used_gpu = report.peak_gpu_mem_bytes > 0
    if used_gpu and not alloc.gpu:
        findings.append(
            Finding(
                "critical",
                "gpu",
                "GPU memory usage was detected during the dry run, but no GPU "
                "allocation was declared.",
                suggestion=(
                    "Add a GPU request (e.g. --gres=gpu:1) to the Slurm "
                    "submission, or confirm this was unintentional GPU "
                    "initialization (e.g. a library defaulting to CUDA)."
                ),
            )
        )
    if alloc.gpu and not used_gpu:
        findings.append(
            Finding(
                "info",
                "gpu",
                "A GPU allocation was declared, but no GPU memory usage was "
                "observed during this dry run.",
                suggestion=(
                    "Confirm the code path that uses the GPU is actually "
                    "exercised by this dry-run input; otherwise you may be "
                    "requesting a GPU allocation you don't need."
                ),
            )
        )
    return findings


def check_network(report: Report, _alloc: Allocation) -> list[Finding]:
    findings = []
    if report.peak_external_connections > 0:
        findings.append(
            Finding(
                "warning",
                "network",
                f"Detected connection(s) to external (non-private) IP "
                f"addresses ({report.peak_external_connections} at peak). "
                f"Many cluster compute nodes have no internet access, so "
                f"calls like pip installs, dataset/model downloads, or API "
                f"calls made at runtime may hang or fail on the real cluster "
                f"even though they worked here.",
                suggestion=(
                    "Move downloads/installs to the login node or a build "
                    "step before submission, and cache data on "
                    "shared/scratch storage."
                ),
            )
        )
    return findings


def check_open_files(report: Report, _alloc: Allocation) -> list[Finding]:
    findings = []
    if report.peak_open_files > OPEN_FILES_WARN_THRESHOLD:
        findings.append(
            Finding(
                "warning",
                "io",
                f"Peak open file handle count was high "
                f"({report.peak_open_files}). If this reflects many small "
                f"files being opened rapidly, it can be a metadata-heavy "
                f"access pattern that performs poorly on shared parallel "
                f"filesystems.",
                suggestion=(
                    "Consider batching small files (e.g. into "
                    "HDF5/tar/zip/Parquet) or staging data to local/fast "
                    "scratch instead of many small reads on shared storage."
                ),
            )
        )
    return findings


def check_runtime(report: Report, alloc: Allocation) -> list[Finding]:
    findings = []
    if report.timed_out:
        findings.append(
            Finding(
                "info",
                "runtime",
                f"The dry run was still executing after the {alloc.timeout_s}s "
                f"dry-run timeout and was terminated. This is expected for "
                f"long/full-scale tasks; treat the reported peaks as a lower "
                f"bound, not final values.",
                suggestion=(
                    "For a fuller picture, dry-run with a reduced "
                    "input/iteration count that finishes naturally, then "
                    "extrapolate."
                ),
            )
        )
    elif report.exit_code not in (0, None):
        findings.append(
            Finding(
                "warning",
                "runtime",
                f"The dry run exited with a non-zero exit code "
                f"({report.exit_code}). If this is not expected under "
                f"normal/full-scale conditions, investigate before "
                f"submitting to the cluster.",
            )
        )
    return findings


ALL_CHECKS: list[CheckFn] = [
    check_memory,
    check_process_thread_oversubscription,
    check_gpu,
    check_network,
    check_open_files,
    check_runtime,
]
