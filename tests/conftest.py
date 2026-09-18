import os

import pytest

# The dbt functional-test fixtures (project, adapter, run_dbt, ...) live in
# dbt-tests-adapter.  Only load them for the functional suite so unit tests do
# not pay the import cost.
pytest_plugins = ["dbt.tests.fixtures.project"]


def pytest_collection_modifyitems(config, items):
    """Skip functional tests unless a Kinetica server has been configured."""
    if os.getenv("KINETICA_HOST"):
        return
    skip = pytest.mark.skip(reason="KINETICA_HOST is not set; functional tests need a live server")
    for item in items:
        if "functional" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
