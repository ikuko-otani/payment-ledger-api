"""Account creation service."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.user import User
from app.schemas.account import AccountCreate
from app.services.audit_service import log_action


async def create_account(
    db: AsyncSession,
    payload: AccountCreate,
    current_user: User,
) -> Account:
    account = Account(
        code=payload.code,
        name=payload.name,
        account_type=payload.account_type,
        currency=payload.currency,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)

    after_value: dict[str, Any] = {
        "id": str(account.id),
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type.value,
        "currency": account.currency,
    }
    await log_action(
        db,
        user_id=current_user.id,
        entity_type="account",
        entity_id=account.id,
        action="create",
        before=None,
        after=after_value,
    )
    return account
