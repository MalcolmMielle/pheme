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
