from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def now():
    return datetime(2026, 10, 26, 7, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture
def fixtures_dir():
    return FIXTURES
