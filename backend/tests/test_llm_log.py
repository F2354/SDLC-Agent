"""LLM 调用日志测试：表建了很久却没数据，这里保证它真的被写入并聚合。

覆盖：记录成功/失败调用、按项目聚合总量与分组、极端情况（db 为空）不抛错。
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.llm_provider import LLMCallLog, LLMProvider
from app.services.llm_log import (
    extract_token_usage,
    recent_calls,
    record_llm_call,
    usage_summary,
)


def _headers(client) -> dict:
    username = f"llmlog_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _project(client, headers, folder: str) -> int:
    resp = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "调用日志测试",
            "description": "简单示例",
            "process_model_code": "waterfall",
            "folder": folder,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _provider(db) -> LLMProvider:
    """建一个可被其它测试安全遍历的 Provider。

    注意：密钥必须用真实加密写入 —— 早先图省事写了明文，导致后续遍历
    Provider 的用例在解密时抛 InvalidToken（测试间污染）。
    """
    from app.models.user import User
    from app.services.crypto import encrypt_secret

    owner = db.scalar(select(User).limit(1))
    provider = LLMProvider(
        user_id=owner.id if owner else 1,
        name="log-test",
        type="openai_compatible",
        base_url="http://example.invalid",
        api_key_enc=encrypt_secret("test-key"),
        default_model="m",
        enabled=False,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def test_extract_token_usage_handles_missing_usage():
    class Dummy:
        pass

    assert extract_token_usage(Dummy()) == (0, 0)

    class WithUsage:
        class usage:  # noqa: N801
            prompt_tokens = 12
            completion_tokens = 7

    assert extract_token_usage(WithUsage()) == (12, 7)


def test_record_and_summarize(client, project_folder):
    headers = _headers(client)
    project_id = _project(client, headers, project_folder)

    with SessionLocal() as db:
        provider = _provider(db)
        for purpose, tokens in (("document_generate", 100), ("stage_review", 50)):
            record_llm_call(
                db,
                provider_id=provider.id,
                model="mimo-v2.5",
                purpose=purpose,
                prompt_tokens=tokens,
                completion_tokens=tokens // 2,
                latency_ms=1000,
                project_id=project_id,
            )
        record_llm_call(
            db,
            provider_id=provider.id,
            model="mimo-v2.5",
            purpose="tool_loop",
            latency_ms=200,
            status="failed",
            error="boom",
            project_id=project_id,
        )

        # 其它项目的调用不应混入本项目的统计
        record_llm_call(
            db,
            provider_id=provider.id,
            model="other-model",
            purpose="document_generate",
            prompt_tokens=999,
            project_id=project_id + 1000,
        )

        summary = usage_summary(db, project_id)
        assert summary.calls == 3
        assert summary.failed_calls == 1
        assert summary.prompt_tokens == 150
        assert summary.completion_tokens == 75
        assert summary.total_tokens == 225
        assert {group.key for group in summary.by_model} == {"mimo-v2.5"}
        assert {group.key for group in summary.by_purpose} == {
            "document_generate",
            "stage_review",
            "tool_loop",
        }

        rows = recent_calls(db, project_id, limit=2)
        assert len(rows) == 2
        assert rows[0].id > rows[1].id  # 按时间倒序


def test_record_is_safe_without_session():
    """没有会话上下文时（如纯调用场景）静默跳过，不抛错。"""
    record_llm_call(None, provider_id=None, model="m", purpose="test")


def test_usage_endpoint_exposes_aggregates(client, project_folder):
    headers = _headers(client)
    project_id = _project(client, headers, project_folder)

    with SessionLocal() as db:
        provider = _provider(db)
        record_llm_call(
            db,
            provider_id=provider.id,
            model="mimo-v2.5",
            purpose="document_generate",
            prompt_tokens=120,
            completion_tokens=80,
            latency_ms=1500,
            project_id=project_id,
        )

    resp = client.get(f"/api/projects/{project_id}/llm-usage", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["calls"] == 1
    assert payload["total_tokens"] == 200
    assert payload["by_model"][0]["key"] == "mimo-v2.5"
    assert payload["recent"][0]["purpose"] == "document_generate"
    assert payload["recent"][0]["latency_ms"] == 1500


def test_log_columns_persist_project_link(client, project_folder):
    """日志必须能追到项目与阶段运行（此前表里只有 user/provider）。"""
    headers = _headers(client)
    project_id = _project(client, headers, project_folder)

    with SessionLocal() as db:
        provider = _provider(db)
        record_llm_call(
            db,
            provider_id=provider.id,
            model="mimo-v2.5",
            purpose="tool_loop",
            project_id=project_id,
            stage_run_id=4242,
            latency_ms=10,
        )
        row = db.scalar(
            select(LLMCallLog).where(LLMCallLog.stage_run_id == 4242)
        )
        assert row is not None
        assert row.project_id == project_id
        assert row.purpose == "tool_loop"
        assert row.total_tokens == 0
