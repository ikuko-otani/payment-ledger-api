# Alembic: `failed to resolve host 'db'` エラー

## 発生日
2026-05-06

## 症状

`alembic revision --autogenerate` をホスト（Windows）から直接実行すると以下のエラーで失敗する。

```
psycopg.OperationalError: failed to resolve host 'db': [Errno 11001] getaddrinfo failed

sqlalchemy.exc.OperationalError: (psycopg.OperationalError) failed to resolve host 'db'
```

## 原因

2 つの問題が重なっていた。

### 原因 1: `DATABASE_URL` のホストが `db`（Docker サービス名）のまま

`docker-compose.yml` の `db` サービス名は Docker ネットワーク内でのみ名前解決できる。  
ホスト OS から直接 `alembic` を実行する場合は `localhost` を使う必要がある。

```dotenv
# .env（変更前）
DATABASE_URL=postgresql+psycopg://ledger_user:password@db:5432/ledger_db

# .env（変更後）
DATABASE_URL=postgresql+psycopg://ledger_user:password@localhost:5432/ledger_db
```

### 原因 2: `alembic/env.py` が `.env` を読み込んでいない

`uv run alembic` は `.env` を自動的に読み込まない。  
`python-dotenv` の `load_dotenv()` を明示的に呼び出す必要がある。

```python
# alembic/env.py の冒頭に追加
import os
from dotenv import load_dotenv

load_dotenv()  # .env を環境変数として読み込む
```

`python-dotenv` が未インストールの場合はインストールする。

```bash
uv add python-dotenv
```

## 解決手順

1. `.env` の `DATABASE_URL` ホストを `db` → `localhost` に変更する
2. `uv add python-dotenv` を実行する
3. `alembic/env.py` の冒頭に `load_dotenv()` を追加する
4. Docker で PostgreSQL が起動していることを確認する

```bash
docker compose up -d db
```

5. マイグレーションを再実行する

```bash
uv run alembic revision --autogenerate -m "your message"
```

## 補足: 実行コンテキストによるホスト名の使い分け

| 実行場所 | `DATABASE_URL` のホスト |
|---|---|
| ホスト OS（`uv run alembic` など） | `localhost` |
| Docker コンテナ内（`api` サービスなど） | `db`（Docker サービス名） |

## 参考

- [python-dotenv ドキュメント](https://saurabh-kumar.com/python-dotenv/)
- [Alembic: env.py のカスタマイズ](https://alembic.sqlalchemy.org/en/latest/tutorial.html#editing-the-migration-script)
