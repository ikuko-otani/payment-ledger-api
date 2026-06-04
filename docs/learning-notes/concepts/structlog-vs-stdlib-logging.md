# structlog.get_logger() vs logging.getLogger()

**Date**: 2026-06-04
**Context**: S5-3 — OTel instrumentation scaffold で logging.getLogger() を誤用したことを契機に整理

---

## Q. `structlog.get_logger()` と `logging.getLogger()` はどう違うのか？

---

## `logging.getLogger()` — Python 標準ライブラリ

Python に最初から入っているロギング機能。

```python
import logging
logger = logging.getLogger(__name__)
logger.info("User created: id=%s email=%s", user_id, email)
```

出力（デフォルト）:
```
INFO:app.services.user:User created: id=42 email=alice@example.com
```

- 値は `%s` フォーマット文字列で埋め込む
- 出力先・フォーマットは `Handler` と `Formatter` で設定する
- ハンドラを設定しなければ **何も出力されない**
- JSON 構造化するには追加設定が必要

---

## `structlog.get_logger()` — structlog ライブラリ

「最初から JSON 構造化ロギング」を目的に作られたライブラリ。

```python
import structlog
logger = structlog.get_logger(__name__)
logger.info("user_created", user_id=42, email="alice@example.com")
```

出力（`configure_structlog()` 設定後）:
```json
{"event": "user_created", "user_id": 42, "email": "alice@example.com", "level": "info", "timestamp": "2026-06-04T..."}
```

- 値はキーワード引数で渡す（各フィールドが独立した JSON キーになる）
- ログ自体がデータ構造（辞書）として扱われる
- `configure_structlog()` で定義したプロセッサチェーンを通って出力される
- `get_logger()` はレイジープロキシを返す — `.info()` が呼ばれたときに初めてプロセッサが評価される

---

## このプロジェクトで最も重要な違い：`merge_contextvars`

`logging.getLogger()` では `merge_contextvars` プロセッサが **走らない**。

```python
# RequestLoggingMiddleware がリクエストごとにバインドしている
structlog.contextvars.bind_contextvars(request_id="abc", trace_id="000...fff")

# logging.getLogger() → request_id / trace_id は付かない
logging.getLogger(__name__).info("payment processed")
# → {"event": "payment processed"}   ← フィールドが欠けている

# structlog.get_logger() → 自動付与される
structlog.get_logger(__name__).info("payment processed")
# → {"event": "payment processed", "request_id": "abc", "trace_id": "000...fff", ...}
```

`logging.getLogger()` を使うと、**同じリクエスト内のログなのに `request_id` / `trace_id` が付いていないログが混在**する。
ログ集約ツールでリクエスト単位の追跡をしようとしたとき、そのログだけ追跡できなくなる。

---

## まとめ

| | `logging.getLogger()` | `structlog.get_logger()` |
|---|---|---|
| 出力形式 | プレーンテキスト（デフォルト） | JSON 構造化 |
| 値の渡し方 | `"msg %s" % value` | `key=value` |
| `request_id` / `trace_id` 自動付与 | ❌ | ✅（`merge_contextvars` 経由） |
| ハンドラ設定なしで出力 | ❌ | ✅（`PrintLoggerFactory` 設定後） |

---

## このプロジェクトでのルール

- **全ファイルで `structlog.get_logger(__name__)` を使う**
- `logging.getLogger()` を使う積極的な理由はない
- ログの書き方は `logger.info("event_name", key=value)` スタイルに統一

---

## 関連

- `app/core/logging.py` — `configure_structlog()` でプロセッサチェーンを定義
- `app/middleware/logging.py` — `bind_contextvars()` で `request_id` / `trace_id` をバインド
- `docs/learning-notes/s5-3-otel-fastapi-instrumentation.md`
