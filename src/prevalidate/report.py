"""
Data structures shared across prevalidate: point-in-time samples of the
process tree, individual findings ("this looks like a problem"), and the
aggregated Report returned to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Snapshot:
    """One sample of the whole process tree at a point in time."""

    t: float  # seconds since dry-run start
    n_processes: int
    total_threads: int
    threads_per_process: list[int]
    rss_bytes: int  # summed RSS across all processes
    open_files: int
    external_connections: int  # connections to non-local/non-private IPs
    gpu_mem_bytes: int = 0


@dataclass
class Finding:
    """A single diagnostic message produced by a check."""

    level: str  # "info" | "warning" | "critical"
    category: (
        str  # "memory" | "parallelism" | "network" | "io" | "gpu" | "runtime"
    )
    message: str
    suggestion: str | None = None

    def __str__(self) -> str:
        tag = {"info": "INFO", "warning": "WARN", "critical": "CRIT"}[
            self.level
        ]
        s = f"[{tag}][{self.category}] {self.message}"
        if self.suggestion:
            s += f"\n    -> suggestion: {self.suggestion}"
        return s


@dataclass
class Report:
    command: str
    exit_code: int | None
    timed_out: bool
    wall_time_s: float
    snapshots: list[Snapshot] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    # convenience aggregates, filled in by build_report()
    peak_rss_bytes: int = 0
    peak_n_processes: int = 1
    peak_total_threads: int = 1
    peak_threads_single_process: int = 1
    peak_open_files: int = 0
    peak_external_connections: int = 0
    peak_gpu_mem_bytes: int = 0

    def summary(self) -> str:
        gb = self.peak_rss_bytes / 1e9
        lines = [
            f"prevalidate report for: {self.command}",
            (
                f"  exit code:            {self.exit_code}"
                f"{' (killed: timeout)' if self.timed_out else ''}"
            ),
            f"  wall time:            {self.wall_time_s:.2f} s",
            f"  peak memory (RSS):    {gb:.3f} GB",
            f"  peak process count:   {self.peak_n_processes}",
            f"  peak total threads:   {self.peak_total_threads}",
            f"  max threads in 1 proc:{self.peak_threads_single_process}",
            f"  peak open files:      {self.peak_open_files}",
            f"  external connections: {self.peak_external_connections}",
        ]
        if self.peak_gpu_mem_bytes:
            gpu_gb = self.peak_gpu_mem_bytes / 1e9
            lines.append(f"  peak GPU memory:      {gpu_gb:.3f} GB")
        lines.append("")
        if self.findings:
            lines.append("Findings:")
            for f in sorted(
                self.findings,
                key=lambda x: {"critical": 0, "warning": 1, "info": 2}[x.level],
            ):
                lines.append("  " + str(f).replace("\n", "\n  "))
        else:
            lines.append("No issues found.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "wall_time_s": self.wall_time_s,
            "peak_rss_gb": self.peak_rss_bytes / 1e9,
            "peak_n_processes": self.peak_n_processes,
            "peak_total_threads": self.peak_total_threads,
            "peak_threads_single_process": self.peak_threads_single_process,
            "peak_open_files": self.peak_open_files,
            "peak_external_connections": self.peak_external_connections,
            "peak_gpu_mem_gb": self.peak_gpu_mem_bytes / 1e9,
            "findings": [
                {
                    "level": f.level,
                    "category": f.category,
                    "message": f.message,
                    "suggestion": f.suggestion,
                }
                for f in self.findings
            ],
        }
