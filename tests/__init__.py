"""Test package bootstrap.

Importing any module from this package (e.g. ``tests.base``) runs this file
first, which points the app at a throwaway database and a fixed test
configuration — the job the old pytest ``conftest.py`` did at collection
time.
"""

import logging
import os
import tempfile

# Use a temp directory for test databases
_tmpdir = tempfile.mkdtemp(prefix="pheme-test-")
os.environ["DATABASE_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["BASE_URL"] = "http://testserver"

# unittest (unlike pytest) does not capture logs, so every record prints and
# floods the run. Keep it readable: the test client's per-request logs and
# the app's INFO chatter are noise in tests — warnings and errors still show.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("pheme").setLevel(logging.WARNING)
