import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp_dir = tempfile.mkdtemp(prefix="sdlc-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp_dir, 'test.db')}"
os.environ["PROJECT_WORKSPACE_ROOT"] = os.path.join(_tmp_dir, "projects")

from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_dir():
    """测试结束后删除临时目录，避免残留。"""
    yield
    shutil.rmtree(_tmp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
