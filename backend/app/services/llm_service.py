from urllib.parse import urlparse

from openai import OpenAI

from app.core.config import settings
from app.models.llm_provider import LLMProvider
from app.schemas.provider import ProviderTestResult
from app.services.crypto import decrypt_secret


class ProviderUrlError(ValueError):
    """Provider base_url 不合法或指向被禁用的网络位置。"""


# 始终拦截的域名：云厂商实例元数据服务。
_ALWAYS_BLOCKED_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "instance-data.ec2.internal",
}


def _address_forbidden(address) -> bool:
    """链路本地（169.254.0.0/16，云元数据服务所在段）与未指定/组播地址一律拒绝。
    私有网段与回环地址不在此列：Ollama 等本地模型服务是平台的核心场景。"""
    return address.is_link_local or address.is_unspecified or address.is_multicast


def _host_is_blocked(host: str) -> bool:
    """判断主机名是否指向必须拦截的目标（SSRF 防护）。"""
    import ipaddress
    import socket

    hostname = host.strip().lower().strip("[]")
    if not hostname:
        return True
    if hostname in _ALWAYS_BLOCKED_HOSTS:
        return True

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        return _address_forbidden(literal)

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except OSError:
        # 无法解析的主机交给后续请求处理，避免在校验阶段误判。
        return False
    for info in resolved:
        try:
            address = ipaddress.ip_address(info[4][0].strip("[]"))
        except (ValueError, IndexError):
            continue
        if _address_forbidden(address):
            return True
    return False


def validate_base_url(base_url: str) -> None:
    """校验 Provider 的 base_url：协议、白名单与内网地址。"""
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ProviderUrlError("base_url 必须以 http:// 或 https:// 开头")
    if not parsed.hostname:
        raise ProviderUrlError("base_url 缺少主机名")

    allowed = {
        host.strip().lower()
        for host in settings.allowed_provider_hosts
        if host and host.strip()
    }
    if allowed:
        if parsed.hostname.lower() not in allowed:
            raise ProviderUrlError(
                f"base_url 主机 {parsed.hostname} 不在允许的白名单内"
            )
    elif _host_is_blocked(parsed.hostname):
        raise ProviderUrlError(
            f"base_url 指向内网或本机地址（{parsed.hostname}），已拒绝连接"
        )


def build_openai_client(provider: LLMProvider) -> OpenAI:
    validate_base_url(provider.base_url)
    api_key = decrypt_secret(provider.api_key_enc) if provider.api_key_enc else "ollama"
    return OpenAI(
        base_url=provider.base_url,
        api_key=api_key,
        timeout=30.0,
        max_retries=0,
    )


def test_provider_connection(provider: LLMProvider) -> ProviderTestResult:
    try:
        validate_base_url(provider.base_url)
    except ProviderUrlError as exc:
        return ProviderTestResult(ok=False, message=str(exc), models=[])
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
        return ProviderTestResult(ok=False, message=str(exc)[:1000], models=[])
