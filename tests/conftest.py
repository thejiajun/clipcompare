"""Every test gets its own empty cache folder, never ~/.cache."""

from __future__ import annotations

import pytest

from clipcompare import cache


@pytest.fixture(autouse=True)
def _own_cache(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path_factory.mktemp("cache")))
    monkeypatch.setattr(cache, "enabled", True)
