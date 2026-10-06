import os

import pytest

from examples.sqlite_mirror.incremental import refresh
from examples.sqlite_mirror.mirror import Source, full_load

pytestmark = pytest.mark.integration


def test_fictional_mirror(browser, tmp_path):
    if os.environ.get("DOTMATICS_TEST_DEMO_SCHEMA") != "configured":
        pytest.skip(
            "Configure the fictional schema and set DOTMATICS_TEST_DEMO_SCHEMA=configured"
        )
    path = tmp_path / "live.db"
    source = Source(browser)
    full_load(source, path)
    refresh(source, path)
    assert path.is_file()
