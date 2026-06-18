"""Account creation service."""

from __future__ import annotations

from typing import Any

from app.models.account import Account
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.account import AccountCreate
from app.schemas.token import TokenUser


async def create_account(
    repo: AccountRepository,
    audit_repo: AuditRepository,
    payload: AccountCreate,
    current_user: TokenUser,
) -> Account:
    account = Account(
        code=payload.code,
        name=payload.name,
        account_type=payload.account_type,
        currency=payload.currency,
    )
    saved = await repo.save(account)

    after_value: dict[str, Any] = {
        "id": str(saved.id),
        "code": saved.code,
        "name": saved.name,
        "account_type": saved.account_type.value,
        "currency": saved.currency,
    }
    await audit_repo.log(
        user_id=current_user.id,
        entity_type="account",
        entity_id=saved.id,
        action="create",
        before=None,
        after=after_value,
    )
    return saved
