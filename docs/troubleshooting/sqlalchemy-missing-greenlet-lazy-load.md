# SQLAlchemy: `MissingGreenlet` — リレーションの遅延ロードエラー

## 発生日

2026-05-07

## 症状

Swagger UI から `POST /api/v1/transactions` を実行すると、レスポンス返却時に 500 エラーが発生する。

```
fastapi.exceptions.ResponseValidationError: 1 validation error:
  {
    'type': 'get_attribute_error',
    'loc': ('response', 'entries'),
    'msg': "Error extracting attribute: MissingGreenlet: greenlet_spawn has not been called;
            can't call await_only() here. Was IO attempted in an unexpected place?
            (Background on this error at: https://sqlalche.me/e/20/xd2s)",
    'input': <Transaction id=... date=2026-05-07 amount=1000.0000>,
    'ctx': {'error': "MissingGreenlet: ..."}
  }
```

エンドポイント: `POST /api/v1/transactions`（`app/api/v1/routes/transactions.py` 内）

## 原因

`db.refresh(transaction)` はスカラー列（`id`, `date`, `amount` など）しか再読み込みしない。  
リレーション（`entries`）は **lazy load** のままであり、DB に問い合わせが走っていない。

FastAPI がレスポンスをシリアライズする際に `transaction.entries` へアクセスしようとするが、  
その時点では `AsyncSession` がすでに閉じているため `MissingGreenlet` エラーが発生する。

```
db.refresh(transaction)
  ↓
スカラー列は更新される
  ↓
entries リレーションは lazy load のまま（未ロード）
  ↓
FastAPI がシリアライズ時に transaction.entries にアクセス
  ↓
AsyncSession が閉じている → MissingGreenlet 💥
```

### なぜ AsyncSession では lazy load が使えないのか

SQLAlchemy の非同期セッション（`AsyncSession`）では、暗黙的な IO（lazy load）が禁止されている。  
セッションスコープ外で属性にアクセスすると greenlet コンテキストが存在せず、上記エラーになる。

## 解決手順

`db.refresh()` の代わりに `selectinload` を使って明示的に eager load する。

```python
# 修正前（❌ entries が lazy load のまま）
await db.refresh(transaction)
return transaction

# 修正後（✅ AsyncSession 内で entries を eager load）
from sqlalchemy import select
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(Transaction)
    .where(Transaction.id == transaction.id)
    .options(selectinload(Transaction.entries))
)
return result.scalar_one()
```

## 動作確認

```bash
git pull origin feature/s1-2-double-entry-db-constraints
docker compose restart api
# → "Application startup complete." が出ればOK
```

その後 Swagger UI から `POST /api/v1/transactions` を再実行し、  
レスポンスに `entries` フィールドが含まれることを確認する。

## まとめ: AsyncSession でリレーションを扱う指針

| 方法 | 使えるか | 備考 |
|---|---|---|
| `db.refresh(obj)` | ⚠️ 一部のみ | スカラー列のみ。リレーションは再ロードされない |
| lazy load（属性へのアクセス） | ❌ 不可 | AsyncSession 外では MissingGreenlet になる |
| `selectinload` / `joinedload` | ✅ 推奨 | `select().options(selectinload(...))` で明示的に eager load |
| `AsyncSession.refresh(obj, attribute_names=[...])` | ✅ 可 | 特定の属性だけ再ロードしたい場合の代替手段 |

## 参考

- [SQLAlchemy: Preventing Implicit IO — Asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#preventing-implicit-io-when-using-asyncsession)
- [SQLAlchemy エラーコード xd2s](https://sqlalche.me/e/20/xd2s)
- [SQLAlchemy: selectinload](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html#select-in-loading)
