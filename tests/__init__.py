"""Test package bootstrap.

Importing any module from this package (e.g. ``tests.base``) runs this file
first, which points the app at a throwaway database and a fixed test
configuration — the job the old pytest ``conftest.py`` did at collection
time.
"""

import os
import tempfile

# Use a temp directory for test databases
_tmpdir = tempfile.mkdtemp(prefix="fedreviews-test-")
os.environ["DATABASE_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["BASE_URL"] = "http://testserver"

# `python -m unittest discover` from the repo root imports every package it
# walks — including `app.*` — before it reaches `tests/`, so `app.config` can
# already be cached with production defaults by the time we get here. Env
# vars alone are too late for it, so re-point the singleton as well.
from app.config import config as _config

_config.base_url = os.environ["BASE_URL"]
_config.database_path = os.environ["DATABASE_PATH"]
_config.secret_key = os.environ["SECRET_KEY"]
