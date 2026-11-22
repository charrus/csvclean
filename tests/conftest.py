"""Shared test fixtures."""

from __future__ import annotations

import urllib.error
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any real HTTP request; tests patch ``urlopen`` when they need one."""

    def urlopen(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("network access is disabled in unit tests")

    monkeypatch.setattr("txnclassify.llm.urllib.request.urlopen", urlopen)
