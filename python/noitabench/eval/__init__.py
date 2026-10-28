"""The evaluation: encounter scores, global metrics, capability scores, depth and the composite.

    python -m noitabench eval <run_dir> [--out profile.json] [--world-files PNG JSON]

It reads a finished run folder (the harness, the human play server or the scripted bot) and
writes `profile.json` (`profile.py` documents the schema). It uses the recording files only: no
re-simulation. **Nothing in `noitabench.agent` or `noitabench.harness` imports this package, and
nothing it computes is shown to an agent** (a test greps for the imports).

Modules: `recording` (the run folder), `worldinfo` (the world file pair), `encounters` (one
scoring rule per implemented encounter), `metrics` (the global indicators), `scoring`
(capabilities, depth, composite), `awareness` (the test-awareness spot-check), `profile`
(the output), `cli`, `knowledge` (the answer key for the notes: facts, claims, the judge, the
extractor that is the only thing here that calls a model, and only from its own command).
"""

__version__ = "0.4.1"

from .profile import PROFILE_FORMAT, build_profile, evaluate_run, write_profile
from .recording import load_run

__all__ = [
    "PROFILE_FORMAT",
    "__version__",
    "build_profile",
    "evaluate_run",
    "load_run",
    "write_profile",
]
