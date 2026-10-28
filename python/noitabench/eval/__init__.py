"""The evaluation: encounter scores, global metrics, capability scores, depth and the composite.

    python -m noitabench eval <run_dir> [--out profile.json] [--world-files PNG JSON]
    python -m noitabench eval <family_dir> [--control <control family_dir>]

It reads a finished run folder (the harness, the human play server or the scripted bot) and
writes `profile.json` (`profile.py` documents the schema). A family folder (`run-01`, `run-02`,
... from `harness run --runs N`) is evaluated game by game and also gets `family_profile.json`
(`family.py`); games after the first are compared with game 1 (`metrics/growth.py`). It uses the
recording files only: no re-simulation. **Nothing in `noitabench.agent` or `noitabench.harness`
imports this package, and nothing it computes is shown to an agent** (a test greps for the
imports).

Modules: `recording` (the run folder), `worldinfo` (the world file pair), `encounters` (one
scoring rule per implemented encounter), `metrics` (the global indicators), `scoring`
(capabilities, composite), `depth` (the depth score and the depth over time), `games` (the games
of a family folder), `family` (the family profile and its control), `awareness` (the
test-awareness spot-check), `profile` (the output), `cli`, `knowledge` (the answer key for the
notes: facts, claims, the judge, the extractor that is the only thing here that calls a model, and
only from its own command).
"""

__version__ = "0.5.0"

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
