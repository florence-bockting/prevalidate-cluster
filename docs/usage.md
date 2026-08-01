# Usage

To use prevalidate-cluster in a project:

```python
import prevc

report = prevc.prevalidate(
    "python my_job.py",
    cpus_allocated=4,
    mem_allocated_gb=8,
)
```

Or import the main entry point directly:

```python
from prevc import prevalidate
```

The CLI is available as `prevc` after install.
