from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["openai_compatible", "ollama"] = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    default_model: str = Field(default="", max_length=120)
    models: list[str] = []
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: Literal["openai_compatible", "ollama"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=120)
    models: list[str] | None = None
    enabled: bool | None = None


class ProviderModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model_name: str
    is_default: bool
    context_window: int | None = None


class ProviderOut(BaseModel):
    id: int
    name: str
    type: str
    base_url: str
    api_key_masked: str | None
    default_model: str
    enabled: bool
    models: list[ProviderModelOut]
    created_at: datetime
    updated_at: datetime


class ProviderTestResult(BaseModel):
    ok: bool
    message: str
    models: list[str] = []
