from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.llm_provider import LLMProvider, LLMProviderModel
from app.models.user import User
from app.schemas.provider import (
    ProviderCreate,
    ProviderModelOut,
    ProviderOut,
    ProviderTestResult,
    ProviderUpdate,
)
from app.services.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.services.llm_service import test_provider_connection

router = APIRouter(prefix="/providers", tags=["providers"])


def get_owned_provider(provider_id: int, user: User, db: Session) -> LLMProvider:
    provider = db.scalar(
        select(LLMProvider)
        .where(LLMProvider.id == provider_id, LLMProvider.user_id == user.id)
        .options(selectinload(LLMProvider.models))
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")
    return provider


def provider_out(provider: LLMProvider) -> ProviderOut:
    masked = None
    if provider.api_key_enc:
        masked = mask_secret(decrypt_secret(provider.api_key_enc))
    return ProviderOut(
        id=provider.id,
        name=provider.name,
        type=provider.type,
        base_url=provider.base_url,
        api_key_masked=masked,
        default_model=provider.default_model,
        enabled=provider.enabled,
        models=[ProviderModelOut.model_validate(model) for model in provider.models],
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def sync_models(provider: LLMProvider, model_names: list[str], db: Session) -> None:
    provider.models.clear()
    db.flush()
    for name in model_names:
        db.add(
            LLMProviderModel(
                provider_id=provider.id,
                model_name=name,
                is_default=name == provider.default_model,
            )
        )
    db.flush()


@router.get("", response_model=list[ProviderOut])
def list_providers(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.user_id == user.id)
            .options(selectinload(LLMProvider.models))
            .order_by(LLMProvider.created_at.desc())
        )
    )
    return [provider_out(provider) for provider in providers]


@router.post("", response_model=ProviderOut, status_code=201)
def create_provider(
    payload: ProviderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = LLMProvider(
        user_id=user.id,
        name=payload.name,
        type=payload.type,
        base_url=payload.base_url,
        api_key_enc=encrypt_secret(payload.api_key) if payload.api_key else None,
        default_model=payload.default_model,
        enabled=payload.enabled,
    )
    db.add(provider)
    db.flush()
    sync_models(provider, payload.models, db)
    db.commit()

    provider = get_owned_provider(provider.id, user, db)
    return provider_out(provider)


@router.get("/{provider_id}", response_model=ProviderOut)
def get_provider(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return provider_out(get_owned_provider(provider_id, user, db))


@router.patch("/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = get_owned_provider(provider_id, user, db)
    if payload.name is not None:
        provider.name = payload.name
    if payload.type is not None:
        provider.type = payload.type
    if payload.base_url is not None:
        provider.base_url = payload.base_url
    if payload.api_key is not None:
        provider.api_key_enc = encrypt_secret(payload.api_key) if payload.api_key else None
    if payload.default_model is not None:
        provider.default_model = payload.default_model
    if payload.models is not None:
        sync_models(provider, payload.models, db)
    if payload.enabled is not None:
        provider.enabled = payload.enabled
    db.commit()
    provider = get_owned_provider(provider_id, user, db)
    return provider_out(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = get_owned_provider(provider_id, user, db)
    db.delete(provider)
    db.commit()


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
def test_provider(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = get_owned_provider(provider_id, user, db)
    result = test_provider_connection(provider)
    if result.ok and result.models and not provider.models:
        sync_models(provider, result.models, db)
        db.commit()
    return result


@router.get("/{provider_id}/models", response_model=list[ProviderModelOut])
def list_provider_models(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = get_owned_provider(provider_id, user, db)
    return provider.models
