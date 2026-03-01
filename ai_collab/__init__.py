"""AI Collaboration System - Multi-AI orchestration and workflow management."""

__version__ = "0.1.0"
__author__ = "Sky Hua"
__email__ = "skyhua@users.noreply.github.com"

from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationDetector
from ai_collab.core.orchestrator import OrchestrationPlanner
from ai_collab.core.selector import ModelSelector

__all__ = [
    "Config",
    "CollaborationDetector",
    "OrchestrationPlanner",
    "ModelSelector",
]
