"""The compiled simulation core.

maturin builds the Rust crate `crates/py` into `noitabench_core/noitabench_core.*.so` (a mixed
layout, because `python-source` is set); this shim makes `import noitabench_core` expose the
classes directly, as the contract (`.trellis/spec/backend/contracts.md` section 6) says.
"""

from .noitabench_core import (
    RECORDING_FORMAT,
    Env,
    Game,
    Rules,
    __version__,
    recipes,
    rules,
    wand_trial,
)

__all__ = [
    "RECORDING_FORMAT",
    "Env",
    "Game",
    "Rules",
    "__version__",
    "recipes",
    "rules",
    "wand_trial",
]
