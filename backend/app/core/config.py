from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仅用于开发环境的内置密钥；非开发环境使用该值会直接拒绝启动。
DEFAULT_SECRET_KEY = "dev-secret-key-change-me-please-0123456789"

DEV_ENVIRONMENTS = {"development", "dev", "local", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SDLC Agent"
    env: str = "development"
    database_url: str = "sqlite:///./data/sdlc.db"
    project_workspace_root: str = "./data/projects"
    secret_key: str = DEFAULT_SECRET_KEY
    access_token_expire_minutes: int = 1440
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 本地单机模式：未携带 token 时自动降级为内置 local 用户。
    # 仅在开发环境允许开启，生产环境下会被强制关闭。
    allow_local_user_fallback: bool = True

    # 编码 Agent 的 run_command 是否允许执行任意 Python 代码（python -c / -m xxx）。
    # 默认关闭：只允许运行工作区内的脚本与 pytest。
    allow_unsafe_commands: bool = False

    # LLM Provider base_url 白名单（主机名，留空表示不限制）。
    # 无论是否配置，内网/回环地址始终会被拦截（SSRF 防护）。
    allowed_provider_hosts: list[str] = []

    # 目录浏览接口的根目录限制，留空表示登录后不限制。
    fs_browse_root: str = ""

    @model_validator(mode="after")
    def _apply_environment_policy(self) -> "Settings":
        if self.env.lower() not in DEV_ENVIRONMENTS:
            if self.secret_key == DEFAULT_SECRET_KEY:
                raise ValueError(
                    "非开发环境必须显式设置 SECRET_KEY 环境变量，"
                    "禁止使用内置默认密钥。"
                )
            # 生产环境强制关闭本地用户兜底，避免鉴权被绕过。
            self.allow_local_user_fallback = False
            self.allow_unsafe_commands = False
        if "*" in self.cors_origins:
            # allow_credentials=True 与通配源不兼容，回退为显式源。
            self.cors_origins = [
                origin for origin in self.cors_origins if origin != "*"
            ]
        return self

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in DEV_ENVIRONMENTS


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
