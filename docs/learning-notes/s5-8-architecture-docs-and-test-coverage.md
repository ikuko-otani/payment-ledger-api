# S5-8: ARCHITECTURE.md 記載 + S5 テスト補完

**Date**: 2026-06-09
**Branch**: `feature/s5-8-architecture-docs-and-test-coverage`
**Goal**: S5 の実装を採用アピール素材に昇華する。ARCHITECTURE.md に設計判断を英語で記述し、テストカバレッジを補完する。

---

## Step C Walkthrough

### What was done

#### 1. ARCHITECTURE.md — Section 9 追加（3サブセクション）

`ARCHITECTURE.md` に `## 9. Observability & Caching Design (S5)` を新設し、以下の3つの設計判断を ADR 形式（Decision / What was rejected / Rationale / Trade-off）で英語記述した。

**9.1 Why async SQLAlchemy over sync**
- Decision: SQLAlchemy 2.0 async engine + asyncpg + `AsyncSession`
- What was rejected: sync SQLAlchemy + `run_in_threadpool`
- Core rationale: FastAPI のイベントループモデルとの一貫性。I/O 待機中に他のリクエストを進められる（PHP-FPM のプロセス占有モデルとの対比で説明）。
- Trade-off: `await` 規律の徹底、`MissingGreenlet` エラーのリスク、async 対応 extension のエコシステムの狭さ。

**9.2 Observability stack (structlog + OTel + Jaeger)**
- Decision: structlog（JSON 構造化ログ）+ OTel（トレーシング計装）+ Jaeger（バックエンド）。`trace_id` を structlog contextvars に bind して両者を連結。
- What was rejected: stdlib `logging`（非構造化）、トレーシングのみ、ログのみ。
- Core rationale: 「ログは何が起きたか」「トレースはどこで時間を使ったか」— trace_id を軸に双方向でピボットできる設計。
- Trade-off: 設定が複雑で失敗が無音（S5-3 で `trace_id = 0` バグを実際に踏んだ経緯を記録）。メトリクス柱（Prometheus）は未実装。

**9.3 Caching strategy (Cache-Aside for account balances)**
- Decision: Cache-Aside パターン。キー `balance:{account_id}:{as_of_date}`、取引投稿時に明示的 invalidation。
- What was rejected: Write-through（書き込み経路をキャッシュの可用性に依存させる）、TTL のみの invalidation（残高の陳腐化ウィンドウが許容できない）。
- Core rationale: 残高が変化するイベント（取引投稿）が明確に特定できるため、明示的 invalidation で常に正確な値を返せる。Redis 障害時もフォールバックで PostgreSQL を直接参照できる。
- Trade-off: `as_of` 日付が異なるキーごとに invalidation が必要（「キャッシュ無効化はコンピュータサイエンスの2大難問の1つ」）。Cache stampede リスク（MVP では許容）。

---

#### 2. テストカバレッジ補完

##### 発見 1: OTel TracerProvider がテストで設定されていなかった

`tests/conftest.py` の `async_client` フィクスチャは `httpx.ASGITransport` を直接ラップするため、FastAPI の lifespan が発火しない。`configure_telemetry()`（lifespan 内）が呼ばれないため、グローバル TracerProvider は OTel デフォルトの no-op のまま。結果、テストスイート全体で `trace_id` が常に `"00000000000000000000000000000000"`（INVALID_SPAN）だった。

**対応**: `conftest.py` に session スコープ・autouse の `_configure_test_tracer_provider` フィクスチャを追加。`InMemorySpanExporter` バックエンドの `TracerProvider` を1回だけ設定することで、ネットワーク（Jaeger）なしに本物の trace_id が生成されるようになった。`trace.set_tracer_provider()` は1プロセスにつき1回のみ有効（2回目は警告を出して無視）なため、session スコープにする必要がある。

**追加したテスト（`tests/test_middleware_logging.py`）**:
- `test_request_log_trace_id_is_valid_otel_span_not_zero`: 既存の「trace_id キーが存在する」チェックに加え、値が `"0" * 32` でなく長さが32文字であることを確認。S5-3 で踏んだ `trace_id = 0` バグのリグレッションテストとして機能する。

---

##### 発見 2: S5 の設定関数（wiring functions）がテストで未実行だった

`configure_structlog()`、`configure_telemetry()`、`get_redis_client()` はいずれも lifespan または `dependency_overrides` によりテストでは一度も実行されず、カバレッジが 56〜67% に留まっていた。

**対応方針（「意味のある80%」vs「形式的な80%」の観点から）**:
これらは「外部ライブラリにこういう設定で接続して」と指示するだけの配線コード。「ライブラリが動くか」ではなく「正しい引数・設定値で呼び出しているか」を検証する単体テストを新規ファイル `tests/test_observability_config.py` として追加。

既存テストスイートでは初めて `unittest.mock` を使うパターン。使い分けの基準：
- 統合テスト（実際の DB/Redis コンテナ）: 「エンドポイントが正しく動くか」
- 単体テスト（モック）: 「配線関数が正しい引数でライブラリを呼び出しているか」

追加した3テスト：

1. `test_configure_structlog_wires_json_renderer_and_print_logger`
   - `configure_structlog()` 呼び出し後 `structlog.get_config()` を検査し、`JSONRenderer`・`TimeStamper`・`PrintLoggerFactory` が設定されていることを確認。
   - teardown: `structlog.reset_defaults()` で元に戻す（structlog 標準 API）。

2. `test_configure_telemetry_builds_provider_tagged_with_service_name`
   - `trace.set_tracer_provider` をモックに差し替えて `configure_telemetry()` を実行。
   - `set_tracer_provider` が呼ばれた引数（`TracerProvider`）の `resource.attributes[SERVICE_NAME]` が `"payment-ledger-api"` であることを確認。
   - `set_tracer_provider` の「1回限り」制約をモックで回避できる利点がある。

3. `test_get_redis_client_builds_from_settings_and_closes_on_exit`
   - `aioredis.from_url` をモックに差し替え、`settings.redis_url` + `decode_responses=True` で呼ばれることを確認（`decode_responses=True` を忘れると `balance.py` の文字列処理が壊れるため重要）。
   - ジェネレータが終了した際に `client.aclose()` が `await` されることを確認（リソースリークなし）。

**結果**: S5 新規モジュール全件 100%、全体 90%（91件全テストグリーン）。

---

#### 3. S5 全 DONE 条件の最終確認（Step 6 で判明したこと）

| 項目 | 結果 |
|---|---|
| JSON 構造化ログ（trace_id/request_id/latency_ms） | ✅ テストグリーン |
| Jaeger UI でトレース表示確認 | ✅ 手動確認済み |
| balance キャッシュヒット < 10ms | ✅ Redis レイテンシ avg 0.93ms（`redis-cli --latency` で確認） |
| mypy strict エラーゼロ | ✅ `no issues found in 51 source files` |
| ruff エラーゼロ | ✅ `All checks passed!` |

**注意**: curl `time_total`（HTTP 全体往復）はキャッシュヒット時でも約99ms。Redis 自体は1ms未満で応答しており、残り約98ms は `get_current_user` が毎リクエスト DB 問い合わせしているオーバーヘッドと推測される（TD-015 として登録済み）。

---

## Files Changed

| ファイル | 変更内容 |
|---|---|
| `ARCHITECTURE.md` | Section 9（Why async SQLAlchemy / Observability stack / Caching strategy）を ADR 形式で英語追記 |
| `tests/conftest.py` | session スコープの `_configure_test_tracer_provider` フィクスチャを追加（OTel TracerProvider をテストで有効化） |
| `tests/test_middleware_logging.py` | `test_request_log_trace_id_is_valid_otel_span_not_zero` を追加（trace_id の非ゼロ検証） |
| `tests/test_observability_config.py` | S5 wiring functions（structlog/OTel/Redis）の単体テストを新規作成 |
| `docs/tech-debt.md` | TD-015 登録（`get_current_user` の per-request DB ラウンドトリップ） |

## Key Takeaways

_（Step D で追記予定）_
