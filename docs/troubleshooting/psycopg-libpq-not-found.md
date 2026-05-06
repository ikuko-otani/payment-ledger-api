# psycopg: `libpq library not found` エラー

## 発生日
2026-05-06

## 症状

`alembic revision --autogenerate` 実行時に以下のエラーで失敗する。

```
ImportError: no pq wrapper available.
- couldn't import psycopg 'c' implementation: No module named 'psycopg_c'
- couldn't import psycopg 'binary' implementation: No module named 'psycopg_binary'
- couldn't import psycopg 'python' implementation: libpq library not found
```

## 原因

`python:3.12-slim` ベースイメージには PostgreSQL クライアントライブラリ（`libpq`）が含まれていない。  
`psycopg`（psycopg3）の純粋 Python 実装は実行時に `libpq` を動的リンクするため、
ライブラリが存在しないコンテナ内では起動できない。

## 解決策

`pyproject.toml` の依存を `psycopg[binary]` に変更する。  
`[binary]` エクストラは `libpq` を静的にバンドルしたホイールを使用するため、
OS 側にライブラリをインストールする必要がない。

```toml
# pyproject.toml（変更前）
"psycopg>=3.3.4",

# pyproject.toml（変更後）
"psycopg[binary]>=3.3.4",
```

変更後、コンテナを再ビルドする。

```bash
docker compose build --no-cache api
docker compose up -d
```

## 参考

- [psycopg3 installation docs](https://www.psycopg.org/psycopg3/docs/basic/install.html)
