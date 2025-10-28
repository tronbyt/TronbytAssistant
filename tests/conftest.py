import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _auto_custom_integrations(enable_custom_integrations: None) -> None:
    """Ensure the Home Assistant helper enables custom components."""
    yield
