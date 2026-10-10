"""Project root for data files, in the repo and inside a Lambda package.

Repo:   <root>/src/lfw/paths.py  -> data in <root>/data
Lambda: /var/task/lfw/paths.py   -> data in /var/task/data (copied by `make package`)
Override with env LFW_ROOT.
"""

from __future__ import annotations

import os
from pathlib import Path

_here = Path(__file__).resolve()
if os.environ.get("LFW_ROOT"):
    ROOT = Path(os.environ["LFW_ROOT"])
elif (_here.parents[1] / "data").is_dir():
    ROOT = _here.parents[1]
else:
    ROOT = _here.parents[2]

DATA = ROOT / "data"
