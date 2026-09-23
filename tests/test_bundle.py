"""dist/agent_single.py must be a fresh build of tools/bundle_agent.py."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import bundle_agent


def test_bundle_is_fresh():
    assert bundle_agent.bundle() == bundle_agent.OUTPUT.read_text(encoding="utf-8"), \
        "dist/agent_single.py is stale: run python tools/bundle_agent.py"
