"""Functional tests run the official dbt adapter test-suite against a live
Kinetica.  Configure the target with environment variables:

    KINETICA_HOST=http://localhost:9191
    KINETICA_USER=admin
    KINETICA_PASSWORD=...
    KINETICA_SCHEMA_PREFIX=dbt_test      (optional)

Without KINETICA_HOST the whole folder is skipped (see tests/conftest.py)."""

import os

import pytest


@pytest.fixture(scope="class")
def dbt_profile_target():
    return {
        "type": "kinetica",
        "threads": int(os.getenv("KINETICA_THREADS", "1")),
        "host": os.getenv("KINETICA_HOST", "http://localhost:9191"),
        "user": os.getenv("KINETICA_USER", "admin"),
        "password": os.getenv("KINETICA_PASSWORD", ""),
        "skip_ssl_cert_verification": os.getenv("KINETICA_SKIP_SSL", "false").lower() == "true",
    }


@pytest.fixture(scope="class")
def prefix():
    return os.getenv("KINETICA_SCHEMA_PREFIX", "dbt_test")
