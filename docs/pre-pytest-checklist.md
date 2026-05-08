<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# pytestの前に走らせておくとよいmypy   のようなコマンドのチートシート的なものを教えてください。

今日は **Sprint Day 20 / S2** です。`payment-ledger-api` の実装フェーズにぴったりなので、このプロジェクト用のチートシートとして整理します。

***

## pytest 前に走らせるコマンド チートシート

### 🔵 レイヤー①：型チェック（実行前）

```bash
uv run mypy app/
```

| 何を検出するか | 例 |
| :-- | :-- |
| 戻り値の型の矛盾 | `return` → `None` を返している |
| 引数の型の不一致 | `str` を渡すべき所に `int` |
| `None` の可能性がある変数の未チェック | `Optional[X]` を `.attribute` で直接参照 |


***

### 🟠 レイヤー②：コード品質（実行前）

```bash
uv run ruff check app/        # lint（未使用import、構文の問題など）
uv run ruff format --check app/  # フォーマットのズレ確認（修正はしない）
uv run ruff format app/       # 自動フォーマット（修正する）
```


***

### 🟢 レイヤー③：テスト（実行）

```bash
uv run pytest -v                        # 全テスト
uv run pytest tests/test_transactions.py -v  # ファイル指定
uv run pytest -v -k "test_entry_amount" # テスト名で絞り込み
uv run pytest --tb=short               # エラーの traceback を短く
```


***

### 推奨実行順序（毎回）

```bash
# 1. フォーマット → 2. lint → 3. 型 → 4. テスト
uv run ruff format app/ && \
uv run ruff check app/ && \
uv run mypy app/ && \
uv run pytest -v
```

> `&&` は前のコマンドが成功した時だけ次に進むので、型エラーがある状態でテストを走らせる無駄がなくなります。

***

### 💡 各ツールの役割まとめ

```
ruff format  → 見た目の統一（インデント、スペースなど）
ruff check   → 悪い書き方の検出（実行前）
mypy         → 型の矛盾の検出（実行前）  ← 今日発見したバグはここ
pytest       → 動作の正しさを検証（実行）
```

`pyproject.toml` に mypy の設定を追加しておくと、プロジェクト全体で一貫したルールになります：

```toml
[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]  # Pydantic を使っているので必須
```

