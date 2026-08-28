from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def load_malformed(name: str) -> str:
    return (FIXTURES_DIR / "malformed" / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURES_DIR
