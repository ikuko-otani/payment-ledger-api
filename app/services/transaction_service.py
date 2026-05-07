"""Transaction service — orchestrates DB writes and enforces double-entry rule.

Double-entry rule: debit_sum == credit_sum.
PostgreSQL CHECK cannot aggregate across rows, so we enforce here.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry, EntryType
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate


async def create_transaction(
    db: AsyncSession,
    payload: TransactionCreate,
) -> Transaction:
    """Validate double-entry balance and persist Transaction + Entries."""

    # 🔧 穴埋め: debit / credit の合計を計算して等しくなければ 422 を返す
    debit_sum = sum(
        e.amount for e in payload.entries if e.entry_type == EntryType.DEBIT
    )
    credit_sum = sum(
        # TODO: ここを実装（ヒント: entry_type == EntryType.CREDIT のものを sum）
        e.amount for e in payload.entries if e.entry_type == EntryType.CREDIT
    )

    if debit_sum != credit_sum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Entries are not balanced: "
                f"debit={debit_sum} credit={credit_sum}"
            ),
        )

    # 🔧 穴埋め: Transaction オブジェクトを作成して db.add する
    transaction = Transaction(
        description=payload.description,
        transaction_date=payload.transaction_date,
        # TODO: ここを実装（ヒント: payload.amount を渡す）
        amount=payload.amount,
    )
    db.add(transaction)
    # flush して transaction.id を確定させる（commit 前でも id が必要）
    await db.flush()

    # 🔧 穴埋め: Entry オブジェクトのリストを作成して db.add_all する
    entries = [
        Entry(
            transaction_id=transaction.id,
            account_id=entry.account_id,
            entry_type=entry.entry_type,
            # TODO: ここを実装（ヒント: entry.amount を渡す）
            amount=entry.amount,
        )
        for entry in payload.entries
    ]
    db.add_all(entries)
    await db.flush()

    # Reload entries so transaction.entries is populated before returning
    await db.refresh(transaction)
    return transaction
