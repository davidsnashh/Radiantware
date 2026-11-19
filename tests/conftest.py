"""Shared test setup."""

import os
import tempfile

# Keep the tests away from the real cache and browser profile.
os.environ["TRN_DATA_DIR"] = tempfile.mkdtemp(prefix="trn-tests-")
