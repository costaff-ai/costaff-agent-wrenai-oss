"""pytest fixtures for the WrenAI agent.

The save tools write to a hardcoded `/app/data/shared/costaff-agent-wrenai/`
inside the container — tests run on the host, so we need to redirect that
path to a pytest `tmp_path` per-test. Done by monkeypatching the
`_SHARED_ROOT` module-level constant on `tools.save` for each test.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def tmp_shared_root(monkeypatch, tmp_path):
    """Redirect tools.save._SHARED_ROOT to a per-test tmp dir.

    Autouse so every test in this package gets an isolated write target
    without remembering to opt in. The fixture also yields the path so
    tests that want to assert on the underlying filesystem can use it.
    """
    import tools.save as save  # noqa: WPS433 — late import keeps coverage of the import path

    new_root = tmp_path / "shared" / "costaff-agent-wrenai"
    monkeypatch.setattr(save, "_SHARED_ROOT", new_root)
    return new_root
