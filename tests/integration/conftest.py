"""Live fixtures never load a .env file or infer an instance."""

import os
import warnings
from pathlib import Path

import pytest

from dotmatics_api import Browser, Inventory


def params():
    required = ("DOTMATICS_USER", "DOTMATICS_INSTANCE")
    if any(not os.environ.get(key) for key in required):
        pytest.skip("Set DOTMATICS_USER and DOTMATICS_INSTANCE to run live tests")
    values = {
        "user": os.environ["DOTMATICS_USER"],
        "dotmatics_instance": os.environ["DOTMATICS_INSTANCE"],
    }
    if os.environ.get("DOTMATICS_TOKEN"):
        values["token"] = os.environ["DOTMATICS_TOKEN"]
    elif os.environ.get("DOTMATICS_PASSWORD"):
        values["password"] = os.environ["DOTMATICS_PASSWORD"]
    else:
        pytest.skip("Set DOTMATICS_PASSWORD or DOTMATICS_TOKEN")
    if os.environ.get("DOTMATICS_PROXY"):
        values["socks5_proxy"] = os.environ["DOTMATICS_PROXY"]
    return values


@pytest.fixture
def mutation_opt_in():
    if os.environ.get("DOTMATICS_TEST_MUTATIONS") != "isolated-test-instance":
        pytest.skip("Mutations require DOTMATICS_TEST_MUTATIONS=isolated-test-instance")


@pytest.fixture(scope="session")
def browser():
    with Browser(**params()) as value:
        yield value


class OwnedInventory:
    """Retry cleanup only for IDs returned by this run's creates; never sweep names."""

    def __init__(self, client):
        self.client = client
        self.owned = []

    def __getattr__(self, name):
        method = getattr(self.client, name)
        if (
            not callable(method)
            or not name.startswith(("create_", "delete_"))
            or name == "create_configuration"
        ):
            return method

        def call(*args, **kwargs):
            if os.environ.get("DOTMATICS_TEST_MUTATIONS") != "isolated-test-instance":
                pytest.skip("Mutation opt-in required")
            if name.startswith("delete_") and (
                not args or (name, args[0]) not in self.owned
            ):
                raise ValueError(
                    "Refusing to delete an ID not created by this test run"
                )
            result = method(*args, **kwargs)
            if name.startswith("create_"):
                current = result
                if isinstance(current, dict) and isinstance(current.get("data"), dict):
                    current = current["data"]
                pk = (
                    next((current[k] for k in ("id", "ID", "Id") if k in current), None)
                    if isinstance(current, dict)
                    else current
                )
                delete = "delete_" + name[len("create_") :]
                if pk is not None and hasattr(self.client, delete):
                    self.owned.append((delete, pk))
            elif args:
                self.owned = [
                    (delete, pk)
                    for delete, pk in self.owned
                    if (delete, pk) != (name, args[0])
                ]
            return result

        return call

    def cleanup(self):
        for method, pk in reversed(self.owned):
            try:
                getattr(self.client, method)(pk)
            except Exception as exc:
                warnings.warn(
                    f"Cleanup failed for this run's {method} ID {pk}: {type(exc).__name__}",
                    RuntimeWarning,
                )


@pytest.fixture(scope="session")
def inventory():
    with Inventory(**params()) as client:
        owned = OwnedInventory(client)
        try:
            yield owned
        finally:
            owned.cleanup()


@pytest.fixture(scope="session")
def input_dir():
    return Path(__file__).parent / "input"


@pytest.fixture
def browser_mapping():
    keys = (
        "DOTMATICS_TEST_PROJECT",
        "DOTMATICS_TEST_DATASOURCE",
        "DOTMATICS_TEST_COLUMN",
        "DOTMATICS_TEST_VALUE",
    )
    if any(not os.environ.get(key) for key in keys):
        pytest.skip(
            "Configure DOTMATICS_TEST_PROJECT/DATASOURCE/COLUMN/VALUE for Browser query tests"
        )
    return tuple(os.environ[key] for key in keys)
