import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp_dir = tempfile.mkdtemp(prefix="sdlc-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp_dir, 'test.db')}"

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
