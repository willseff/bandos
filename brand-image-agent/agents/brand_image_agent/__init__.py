import sys
from pathlib import Path

# ADK adds agents/ to sys.path; add the project root so `database` is importable
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .agent import root_agent

__all__ = ["root_agent"]
