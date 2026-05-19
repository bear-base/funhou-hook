# ログ設計

`funhou-hook` のログは、ユーザー向け通知と運用調査用ログを分けて扱う。

新しいログを追加するときは、「ユーザーがリアルタイムに見るべき出来事」なのか、
「挙動が怪しいときに開発者が調べるための情報」なのかを先に分ける。

## ログの種類

### Notification

ユーザー向けの分報。

現行実装では `LogKind.Notification` logger へ直接出力するのではなく、
`LogMessage` / `ApprovalMessage` / `SummaryMessage` を dispatcher が terminal log
や Slack に配送する。

Notification には stack trace、内部 ID、リトライ詳細、外部 API の生レスポンスなどを
混ぜない。

### Operational

開発者・運用者が障害時に調べるためのログ。

出力先は `logs/operational.log`。Slack 配送失敗、hook runtime error、summary 生成失敗、
approval state 破損などを記録する。

ユーザー向け通知に出すとノイズになる内部情報は Operational に寄せる。

### Debug

現行実装では `LogKind.Debug` は定義のみで、出力先は設定しない。

一時的な調査ログは Debug Log として残さず、調査した PR の中で削除する。残す必要が
ある情報は Operational Log に昇格させる。

### StateAudit

現行実装では `LogKind.StateAudit` は定義のみで、出力先は設定しない。

approval state の正式な監査ログは未実装。関連箇所には将来の再設計用に
`TODO(state-audit-redesign)` を残す。

## 出力先

| 種別 | 出力先 |
|---|---|
| Notification | terminal log / Slack |
| Operational | `logs/operational.log` |
| Debug | なし |
| StateAudit | なし |

## Operational Log に記録するもの

| イベント | レベル | 主な context |
|---|---|---|
| 設定ロード成功 | INFO | `config_path` |
| hook 受信成功 | INFO | `event_type`, `source` |
| hook runtime error | ERROR | `event_type`, `error_type`, `error_message`, `stack_trace` |
| Slack 配送失敗 | ERROR | `channel`, `event_type`, `reason` |
| approval state 破損検知 | ERROR | `state_id`, `error_type`, `detail` |
| Summary provider 予期せぬ例外 | WARN | `trigger`, `error_type`, `reason` |
| Summary 生成失敗 | WARN | `trigger`, `reason`, `error_kind`, `retryable`, `metadata` |
| Summary provider 契約違反 | WARN | `trigger`, `error_kind` |

## 原則

- ユーザー向け通知に内部エラー詳細を混ぜない。
- Operational Log はユーザー体験を壊さない場所に出す。
- Slack 配送失敗は Notification には出さず、Operational に記録する。
- Summary はベストエフォート機能なので、生成失敗時も Notification には出さない。
- 一時調査ログは残さない。必要なら Operational Log に昇格する。

## ログ基盤 API

```python
from funhou_hook.logging import LogKind, get_logger

logger = get_logger(LogKind.Operational)
logger.warning("Summary generation failed", extra={"trigger": "Stop"})
```

`initialize_logging()` は Operational に `FileHandler` を設定し、それ以外の `LogKind`
には `NullHandler` を設定する。

`extra` には標準 `logging` の予約語(`message`, `asctime`, `levelname` など)を入れない。
