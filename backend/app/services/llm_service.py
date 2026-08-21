from openai import OpenAI

from app.models.llm_provider import LLMProvider
from app.schemas.provider import ProviderTestResult
from app.services.crypto import decrypt_secret


def build_openai_client(provider: LLMProvider) -> OpenAI:
    api_key = decrypt_secret(provider.api_key_enc) if provider.api_key_enc else "ollama"
    return OpenAI(
        base_url=provider.base_url,
        api_key=api_key,
        timeout=30.0,
        max_retries=0,
    )


def test_provider_connection(provider: LLMProvider) -> ProviderTestResult:
    try:
        client = build_openai_client(provider)
        models = [item.id for item in client.models.list().data]
        message = "连接成功"
        if provider.default_model:
            client.chat.completions.create(
                model=provider.default_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            message = f"连接成功，模型 {provider.default_model} 可用"
        return ProviderTestResult(ok=True, message=message, models=models)
    except Exception as exc:
        return ProviderTestResult(ok=False, message=str(exc), models=[])
