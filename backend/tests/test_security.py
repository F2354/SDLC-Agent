"""安全加固相关测试：鉴权、SSRF、命令执行、依赖净化、级联删除。"""
import uuid

from app.core.config import settings
from app.services.code_service import _sanitize_requirements
from app.services.coding_agent import _build_command, _validate_pip_args
from app.services.llm_service import ProviderUrlError, validate_base_url


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def register(client) -> dict:
    username = unique_name("sec")
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------- 鉴权 ----------


def test_filesystem_rejects_anonymous_when_fallback_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_local_user_fallback", False)
    response = client.get("/api/filesystem")
    assert response.status_code == 401


def test_filesystem_accepts_authenticated_user(client):
    headers = register(client)
    response = client.get("/api/filesystem", headers=headers)
    assert response.status_code == 200
    assert "entries" in response.json()


def test_invalid_token_rejected_when_fallback_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_local_user_fallback", False)
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer bogus"})
    assert response.status_code == 401


# ---------- SSRF ----------


def test_link_local_base_url_rejected():
    try:
        validate_base_url("http://169.254.169.254/latest/meta-data/")
        raise AssertionError("链路本地地址应被拒绝")
    except ProviderUrlError:
        pass


def test_non_http_scheme_rejected():
    try:
        validate_base_url("file:///etc/passwd")
        raise AssertionError("非 http 协议应被拒绝")
    except ProviderUrlError:
        pass


def test_allowlist_blocks_unlisted_host():
    original = settings.allowed_provider_hosts
    settings.allowed_provider_hosts = ["api.deepseek.com"]
    try:
        validate_base_url("https://api.deepseek.com/v1")
        try:
            validate_base_url("https://evil.example.com/v1")
            raise AssertionError("白名单外的主机应被拒绝")
        except ProviderUrlError:
            pass
    finally:
        settings.allowed_provider_hosts = original


def test_local_ollama_url_allowed():
    """Ollama 本地服务是核心场景，必须允许。"""
    validate_base_url("http://127.0.0.1:11434/v1")


def test_provider_creation_rejects_metadata_url(client):
    headers = register(client)
    response = client.post(
        "/api/providers",
        headers=headers,
        json={
            "name": "metadata",
            "type": "openai_compatible",
            "base_url": "http://169.254.169.254/v1",
            "api_key": "sk-test",
            "default_model": "m",
        },
    )
    assert response.status_code == 400


# ---------- 命令执行白名单 ----------


def test_python_dash_c_rejected():
    command, error = _build_command(1, ["python", "-c", "__import__('os').system('id')"])
    assert command is None
    assert "-c" in error


def test_python_module_whitelist():
    command, error = _build_command(1, ["python", "-m", "os"])
    assert command is None
    assert error is not None

    command, error = _build_command(1, ["python", "-m", "pytest", "-q"])
    assert error is None
    assert command is not None


def test_pip_index_url_rejected():
    assert _validate_pip_args(["install", "--extra-index-url", "http://evil.tld"]) is not None
    assert _validate_pip_args(["install", "requests"]) is None


def test_pytest_config_override_rejected():
    command, error = _build_command(1, ["pytest", "-c", "/tmp/evil.ini"])
    assert command is None


def test_unknown_program_rejected():
    command, error = _build_command(1, ["curl", "http://evil.tld"])
    assert command is None
    assert error is not None


# ---------- 依赖净化 ----------


def test_requirements_options_stripped(tmp_path):
    target = tmp_path / "code"
    target.mkdir()
    (target / "requirements.txt").write_text(
        "fastapi\n"
        "uvicorn==0.34.0\n"
        "--extra-index-url http://evil.tld/simple\n"
        "--trusted-host evil.tld\n"
        "# comment\n"
        "requests[security]>=2.0\n",
        encoding="utf-8",
    )
    safe = _sanitize_requirements(target)
    assert safe is not None
    content = safe.read_text(encoding="utf-8").splitlines()
    assert "fastapi" in content
    assert "uvicorn" in content
    assert "requests" in content
    assert not any(line.strip().startswith("-") for line in content)


def test_requirements_empty_returns_none(tmp_path):
    target = tmp_path / "code"
    target.mkdir()
    (target / "requirements.txt").write_text("--index-url http://evil.tld\n", encoding="utf-8")
    assert _sanitize_requirements(target) is None


# ---------- 级联删除 ----------


def test_delete_project_cascades_child_rows(client):
    from app.db.session import SessionLocal
    from app.models.stage_run import ActivityEvent, Artifact, Message, StageRun

    headers = register(client)
    created = client.post(
        "/api/projects",
        headers=headers,
        json={"name": unique_name("cascade"), "description": "", "process_model_code": "waterfall"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    with SessionLocal() as db:
        run = StageRun(project_id=project_id, stage_id=1, status="failed")
        db.add(run)
        db.flush()
        db.add(Artifact(project_id=project_id, stage_run_id=run.id, type="doc", title="t"))
        db.add(Message(project_id=project_id, stage_run_id=run.id, role="user", content="hi"))
        db.add(
            ActivityEvent(
                project_id=project_id, stage_run_id=run.id, event_type="test", message="m"
            )
        )
        db.commit()
        run_id = run.id

    assert client.delete(f"/api/projects/{project_id}", headers=headers).status_code == 204

    with SessionLocal() as db:
        assert db.get(StageRun, run_id) is None
        assert db.scalar(
            __import__("sqlalchemy").select(Artifact).where(Artifact.project_id == project_id)
        ) is None
        assert db.scalar(
            __import__("sqlalchemy").select(Message).where(Message.project_id == project_id)
        ) is None
        assert db.scalar(
            __import__("sqlalchemy")
            .select(ActivityEvent)
            .where(ActivityEvent.project_id == project_id)
        ) is None
