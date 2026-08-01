# `prevalidate` — pre-submission dry-run diagnostics for Slurm cluster jobs

Status: early concept / working code sketch
Author: (fill in)
Context: Aalto Scientific Computing, Triton (Slurm)

## 1. Problem statement

Many cluster users — especially those newer to HPC — submit jobs without a
good sense of the resources their task actually needs, or of side effects
their code has on a shared system. Two failure modes come up repeatedly:

1. **Memory misestimation.** Users guess `--mem`, either causing OOM kills
   (too low) or wasting allocation / delaying scheduling for others (too
   high).
2. **Unintentional nested parallelism.** A task spawns N worker processes
   (e.g. Python `multiprocessing`, R `parallel`) and each worker also uses
   a multi-threaded library (OpenBLAS/MKL/OpenMP), silently creating
   N × M threads on hardware allocated for N or M. This is explicitly
   called out as a common problem in Aalto's own Triton documentation
   ("double-booked parallelism").

Existing tooling (Slurm's `seff`/`sacct`/`sstat`, `time -v`) is **entirely
retrospective** — it tells you what a job did after you already ran it on
the cluster, burned queue time, and possibly got OOM-killed or triggered a
support ticket. There is no lightweight, standard **pre-submission** check.

**Goal:** a fast, language-agnostic dry-run tool users can run *before*
`sbatch`, that profiles their task and flags cluster-unfriendly behavior
early, with actionable suggestions.

## 2. Is this a novel idea? (prior art check)

Nothing found that does exactly this (pre-submission, generic, automated
dry-run + Slurm-aware advice). Related/adjacent tools:

| Tool | What it does | Why it's not this |
|---|---|---|
| `seff`, `sacct`, `sstat` | Slurm's own post-hoc efficiency reports (CPU%, mem%) | Retrospective only, Slurm-only interface, no pre-submission check |
| `time -v` / `/usr/bin/time` | Peak RSS of a single process | No process-tree awareness, no cluster-specific advice, manual |
| `threadpoolctl` | Introspects/controls thread pools (OpenBLAS, MKL, OpenMP) in-process | Python-only, library-level, not a full dry-run tool |
| XALT (TACC et al.) | Site-wide, admin-facing tracking of executables/libraries linked at run time | Retrospective, cluster-wide accounting tool, not a user-facing pre-flight check |
| ReFrame (CSCS) | HPC regression testing framework | For validating known apps across systems, not ad hoc user code |
| Nextflow/Snakemake resource reporting | Track & retry with more resources | Reactive (fails first), tied to specific workflow engines |

**Conclusion:** there's a real, currently-unfilled niche here. Worth
checking directly with ASC staff whether there's an internal wishlist or
prior attempt before going further, since this addresses a documented,
recurring support-ticket-generating problem.

## 3. Design principles

- **Empirical, not static.** True prediction of memory/thread usage
  without running anything is generally impossible for arbitrary code.
  `prevalidate` is a **dry-run profiler**: it runs the task (ideally on
  reduced/synthetic input or under a time cap), samples the process tree,
  and reports peak usage + diagnostics — not a magic predictor from source
  code alone. This should be stated explicitly to users so expectations
  are correct.
- **Language-agnostic by construction.** Instead of wrapping a language
  object (`prevalidate(fun)`), wrap a **command** (shell string or argv
  list) and monitor it via the OS process tree (`psutil`/`/proc`). This
  works identically for Python, R, MATLAB, compiled binaries, or MPI
  launchers. Thin per-language wrappers (e.g. a Python decorator that
  pickles a function call into a subprocess invocation) can sit on top.
- **Fast.** Sampling interval and dry-run timeout are tunable; default
  dry run should complete in seconds using a reduced problem size, not
  require a full-scale run.
- **Additive / rule-based checks.** Each diagnostic is an independent
  function `(report, allocation) -> [Finding]`, so new checks (per-cluster
  policy, new failure modes) can be added without touching the core
  runner. Findings carry a severity (`info`/`warning`/`critical`), a
  category, a message, and a concrete suggestion.
- **Honest about extrapolation limits.** Memory/runtime scaling with input
  size is often but not always linear (e.g. non-linear algorithms, caching
  effects, one-time startup costs amortized differently at scale). Any
  extrapolation feature must say so.

## 4. Architecture (as sketched)

```
prevalidate/
├── __init__.py     # public API: prevalidate()
├── core.py         # subprocess launch + monitor + checks orchestration
├── monitor.py       # ProcessTreeMonitor: psutil-based sampling thread
├── checks.py        # individual rule functions -> list[Finding]
└── report.py         # Snapshot / Finding / Report dataclasses
examples/
├── nested_parallelism_demo.py   # reproduces N processes x M threads
└── memory_hog_demo.py           # reproduces memory over-allocation
```

Core flow (`prevalidate.core.prevalidate`):

1. Launch `command` via `subprocess.Popen` (shell string or argv list).
2. Start a background thread (`ProcessTreeMonitor`) that polls every
   `sample_interval` seconds: walks `psutil.Process(pid).children(recursive=True)`,
   sums RSS, thread counts (total + per-process), open file handles, and
   flags connections to non-private/non-loopback IPs as "external".
   Also polls GPU memory via `pynvml` if available/present.
3. Wait for the process to finish or hit `timeout` (kill + mark
   `timed_out=True` if so).
4. Aggregate peak values across all samples into a `Report`.
5. Run all registered checks against the report + user-declared
   allocation (`cpus_allocated`, `mem_allocated_gb`, `gpu_allocated`),
   collecting `Finding`s.
6. Print/return the `Report`.

This has been smoke-tested against two toy scripts and correctly flags
both target failure modes:
- 4 processes × 4 threads with `cpus_allocated=4` → CRITICAL: peak thread
  count (24, incl. main overhead) exceeds allocation; WARNING: nested
  parallelism pattern detected.
- ~500MB allocation with `mem_allocated_gb=0.2` → CRITICAL: peak memory
  exceeds declared allocation.

## 5. Checks implemented in the sketch

| Check | Trigger | Category |
|---|---|---|
| Memory over allocation | peak RSS > declared `--mem` | memory (critical) |
| Memory under-utilization | peak RSS < 30% of declared `--mem` | memory (info) |
| Nested parallelism pattern | >1 process AND >1 thread in some process | parallelism (warning) |
| Thread/CPU oversubscription | peak total threads > declared CPUs | parallelism (critical) |
| GPU used but not requested | GPU memory > 0, `gpu_allocated=False` | gpu (critical) |
| GPU requested but unused | `gpu_allocated=True`, no GPU memory seen | gpu (info) |
| External network access | connection to non-private IP detected | network (warning) |
| High open-file count | peak open files > threshold (metadata-heavy I/O) | io (warning) |
| Dry run timed out | process still running at timeout | runtime (info) |
| Non-zero exit code | process failed | runtime (warning) |

## 6. Additional checks to consider (not yet implemented)

Roughly in priority order for a v1/v2:

- **Wall-time extrapolation.** Run on a reduced input/iteration count,
  fit a simple scaling model (or just report raw time + explicit caveat),
  to help set `--time` sensibly. Needs a way for the user to indicate
  what "reduced" means (e.g. `n_reduced` vs `n_full` parameter) since this
  can't be inferred generically.
- **Filesystem-target awareness.** Distinguish writes to scratch vs. home
  vs. network-mounted paths (Triton has different filesystems with
  different performance/quota characteristics); warn if writing heavily
  to home or to storage not meant for job I/O.
- **Small-file / metadata-heavy I/O pattern detection.** Beyond just open
  file *count*, look at file open rate and average file size — many small
  files hit Lustre-style parallel filesystems hard even without high
  concurrent handle counts.
- **Checkpoint/resume presence heuristic.** For jobs likely to run long
  (based on declared `--time` or extrapolated runtime), warn if there's no
  evidence of a checkpoint mechanism (heuristic only — hard to detect
  reliably; maybe just a reminder/checklist item rather than an automated
  check).
- **Interactive/GUI dependency detection.** Catch jobs that depend on X11,
  interactive prompts (stdin reads that will hang in batch mode), or
  license servers/services only reachable from login nodes.
- **Environment/reproducibility check.** Snapshot loaded modules / active
  conda-env / R library paths so a failure can be correlated with the
  environment later; also flag if critical env vars the code depends on
  aren't set.
- **MPI-awareness.** For MPI-launched commands, some of the "process
  count" logic needs adjusting since many processes are expected — the
  checks should accept an expected process count baseline rather than
  assuming 1 is always normal.
- **Disk space / quota check.** Estimate scratch usage growth during the
  dry run and compare against known quota if that's queryable.
- **Site-policy layer.** A config file (per-cluster, e.g. Triton-specific)
  defining thresholds (e.g. "flag if open files > X", partition-specific
  GPU memory sizes, default margins) so the same package can be reused
  across clusters with different tuning without code changes.

## 7. Open questions / things to discuss with colleagues

- **Reduced-input convention.** How do we ask users to provide a
  "small/fast" version of their task for the dry run? Options: (a) users
  write a `--dry-run`/`--n-small` flag into their own scripts, (b) the
  tool subsamples input files automatically for known formats (risky/
  format-specific), (c) just document it as a required user step and rely
  on a `timeout` cap as the fallback.
- **Where should this run?** On the login node (fast, but login nodes
  often forbid heavy compute — need a lightweight dry run only) vs. as a
  tiny interactive Slurm allocation (`srun --pty`) launched by the tool
  itself for a more representative environment (cgroups, module system).
  Probably want to support both.
- **Packaging / distribution.** Standalone pip package vs. something ASC
  bundles/recommends centrally (e.g. exposed as a module on Triton).
  Central distribution would also let ASC maintain the Triton-specific
  threshold config (see site-policy layer above).
- **False positives / trust.** Overly noisy warnings will get ignored.
  Need sensible defaults and possibly a `--strict`/`--quiet` verbosity
  knob, plus the ability to suppress specific checks per project.
  Aggregate real usage data over time (opt-in) to make the info/warning
  thresholds (e.g. "30% under allocation") empirically grounded rather
  than arbitrary.
- **Per-language convenience wrappers.** Should there be a Python
  decorator (`@prevalidate` on a function) and an R equivalent that
  handle serializing the call into a subprocess automatically, on top of
  the generic command-based core? Likely yes, as a thin second layer.
- **Relationship to XALT / existing ASC monitoring**, if any exists —
  worth checking before building further, both to avoid duplicating
  effort and to see whether post-hoc data ASC already has could calibrate
  the pre-flight thresholds.

## 8. Next steps

1. Share this note + code sketch with colleagues at ASC for feedback:
   does this duplicate anything, is there appetite for a supported tool?
2. Decide on the reduced-input / representative-run convention (open
   question above) — this materially affects the API.
3. Pick 2–3 more checks from section 6 to prototype next (wall-time
   extrapolation and filesystem-target awareness seem highest value).
4. Test against real user scripts (with permission) from common
   ASC/Triton use cases (Python/R/MATLAB data science pipelines) to see
   what the noise/signal ratio actually looks like in practice.
