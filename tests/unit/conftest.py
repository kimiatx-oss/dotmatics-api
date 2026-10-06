from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def input_dir():
    return str(Path(__file__).parent / "input")
