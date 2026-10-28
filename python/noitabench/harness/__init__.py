"""The harness: what lets a language model play a game through the agent interface.

    from noitabench.harness import RunConfig, ModelConfig, run_family
    run_family(RunConfig(ModelConfig("anthropic", "claude-haiku-5-5"), out=Path("runs/h1")))

or from the command line: `python -m noitabench harness run --help`.

Layers (design 6.2): L0 game tools, L1 the workspace (notebook), L2 Code Mode, L3 hooks and L5
plugins and libraries are here (L2, L3 and L5 run the player's code in the box of `sandbox.py`);
L4 (sub-agents) plugs in the same way. A layer is added through `layers.LAYER_REGISTRARS` and
`ToolBox.register`.
Everything that leaves the box, and everything the model is shown or the run writes, is passed
through the redactor of `redact.py`, which hides the secrets the box could have read.
Contract text: `.trellis/spec/backend/contracts.md`, "Harness".
"""

from .budget import Budget
from .errors import ConfigError, HarnessError, ModelError, StopRun
from .layers import DEFAULT_LAYERS, MINIMAL_LAYERS, build_toolbox, resolve_layers
from .loop import AgentLoop, LoopConfig, LoopResult
from .model import (
    Conversation,
    ModelAdapter,
    ModelConfig,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolSpec,
    UserText,
)
from .prices import PRICES, ModelPrice, resolve_price
from .prompt import system_prompt
from .runner import RunConfig, play_game, run_family
from .toolbox import ToolBox, ToolDef
from .usage import Usage
from .workspace import Workspace

__all__ = [
    "DEFAULT_LAYERS",
    "MINIMAL_LAYERS",
    "PRICES",
    "AgentLoop",
    "Budget",
    "ConfigError",
    "Conversation",
    "HarnessError",
    "LoopConfig",
    "LoopResult",
    "ModelAdapter",
    "ModelConfig",
    "ModelError",
    "ModelPrice",
    "ModelTurn",
    "RunConfig",
    "StopRun",
    "ToolBox",
    "ToolCall",
    "ToolDef",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "UserText",
    "Workspace",
    "build_toolbox",
    "play_game",
    "resolve_layers",
    "resolve_price",
    "run_family",
    "system_prompt",
]
