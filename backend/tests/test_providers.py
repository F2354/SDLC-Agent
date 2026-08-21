import uuid

from app.services.crypto import decrypt_secret, encrypt_secret, mask_secret


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_crypto_round_trip():
    secret = "sk-test-abcdef123456"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret
    assert "abcdef123456" not in mask_secret(secret)


def test_provider_crud(client):
    username = unique_name("provider_owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    created = client.post(
        "/api/providers",
        headers=headers,
        json={
            "name": "我的 DeepSeek",
            "type": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-test-1234567890123456",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["api_key_masked"] is not None
    assert "sk-test-1234567890123456" not in str(body)
    provider_id = body["id"]

    listed = client.get("/api/providers", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(
        f"/api/providers/{provider_id}",
        headers=headers,
        json={"name": "DeepSeek 主服务"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "DeepSeek 主服务"

    deleted = client.delete(f"/api/providers/{provider_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/providers", headers=headers).json() == []
