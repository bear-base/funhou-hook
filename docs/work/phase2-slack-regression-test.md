# Phase2 Slack 回帰テスト仕様書

## 現状の課題

Phase2 の Slack 連携は、設定読み込み、Slack payload 生成、Incoming Webhook 送信、dispatcher からの複数チャネル配信まで実装済みである。一方で、Slack 実機への送信確認は webhook URL やメンション先などの認証系情報を必要とするため、自動テストでは実施しない。

Ticket 5 では、実送信を伴わない自動回帰テストと、人間が Slack 実機で確認するための手順を分離して整備する。README への正式反映とサマリー生成エンジンは本チケットの対象外とする。

## 検証済みの事実（ログ等）

- `SummaryMessage` は型、terminal 表示、Slack payload、dispatcher 配送判定の受け皿が存在する。
- `SummaryMessage` を生成するエンジン、生成トリガー、LLM 呼び出しは未実装である。
- Slack webhook URL とメンション先は `config/.env` から読む。
- `config/.env` は git 管理外であり、`config/.env.example` にはダミー値のみを置く。
- Slack disabled 時は terminal のみ動作する設計である。
- Slack 配送失敗は hook 全体を失敗させず、Operational Log に記録する設計である。
- terminal は最小保証チャネルであり、terminal 配送失敗は hook 全体の失敗として扱う設計である。
- 自動回帰テストは `tests/test_phase2_slack_integration.py` に配置する。

## 未検証の仮説

- 実際の Slack Incoming Webhook に対して、現在の payload が Slack 上で期待どおり表示される。
- `SLACK_MENTION_TO` に `<@USERID>` 形式を設定した場合、warning / danger / approval で実メンションとして通知される。
- Slack 側の webhook 無効化、権限変更、チャンネル削除などの運用上の失敗は、HTTP 失敗として `logs/operational.log` から追跡できる。
- Windows PowerShell から hook を実行した場合でも、`config/.env` と `config/funhou.toml` の組み合わせで Slack 実送信まで到達できる。

## 修正方針

### 自動回帰テスト

`tests/test_phase2_slack_integration.py` で以下を確認する。

- Slack disabled 時は terminal のみ出力され、Slack sender は呼ばれない。
- Slack enabled かつ `SLACK_WEBHOOK_URL` がある場合、hook から Slack sender まで到達する。
- Slack enabled かつ `SLACK_WEBHOOK_URL` がない場合、設定ロードが失敗する。
- Slack の `levels` filter により、対象外 level の message は Slack sender に渡らない。
- Slack の `message_types` filter により、対象外 message type の message は Slack sender に渡らない。
- Slack 配送失敗時も terminal 出力は残り、Operational Log に失敗が記録される。
- `ApprovalMessage` は Slack sender まで到達し、`mention_to` / `mention_on` が渡される。
- `SummaryMessage` は生成エンジン抜きで手動生成した場合に配送できる。生成エンジン本体は後続 TODO とする。

### Slack 実機回帰テスト

#### 事前準備

1. Slack Incoming Webhook URL を用意する。
2. メンション先の Slack user ID を確認する。
3. `config/.env` を作成し、以下を設定する。

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_MENTION_TO=<@U01234567>
```

`@you` のような表示名は実メンションにならない可能性があるため、メンション確認では `<@USERID>` 形式を使う。

#### 設定

`config/funhou.toml` の Slack 設定を一時的に有効化する。

```toml
[channels.slack]
enabled = true
levels = ["info", "warning", "danger", "error"]
message_types = ["log", "summary", "approval"]
mention_on = ["warning", "danger"]
```

実機確認後は `enabled = false` に戻す。

#### 通常ログ確認

PowerShell で以下を実行する。

```powershell
'{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.py"},"session_id":"phase2-slack-manual"}' | uv run python hook.py
```

確認事項:

- terminal ログに `Read src/config.py` が出る。
- Slack に `Read src/config.py` 相当の投稿が届く。
- `Read` は `info` 扱いなので、メンションは付かない。

#### warning メンション確認

PowerShell で以下を実行する。

```powershell
'{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"npm run build"},"session_id":"phase2-slack-manual"}' | uv run python hook.py
```

確認事項:

- Slack に `Bash npm run build` 相当の投稿が届く。
- default level が `warning` のため、`SLACK_MENTION_TO` のメンションが付く。
- Slack クライアント上で通知として扱われる。

#### danger / approval 確認

PowerShell で以下を実行する。

```powershell
'{"hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"command":"npx prisma migrate deploy","description":"production migration"},"session_id":"phase2-slack-manual","tool_use_id":"phase2-tool-1"}' | uv run python hook.py
```

確認事項:

- terminal ログに `[APPROVAL]` が出る。
- Slack に承認待ちの Block Kit 表示が届く。
- `SLACK_MENTION_TO` のメンションが付く。
- Slack 上では承認できない旨が表示される。

#### level filter 確認

`config/funhou.toml` の Slack levels を一時的に以下へ変更する。

```toml
levels = ["danger"]
```

通常ログ確認と同じ `Read` payload を実行する。

確認事項:

- terminal ログには出る。
- Slack には投稿されない。

#### message type filter 確認

`config/funhou.toml` の Slack message_types を一時的に以下へ変更する。

```toml
message_types = ["approval"]
```

通常ログ確認と同じ `Read` payload を実行する。

確認事項:

- terminal ログには出る。
- Slack には投稿されない。

#### Slack 失敗時の Operational Log 確認

`config/.env` の `SLACK_WEBHOOK_URL` を一時的に無効な URL に変更する。

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/invalid
```

通常ログ確認と同じ `Read` payload を実行する。

確認事項:

- terminal ログには出る。
- hook の標準出力 JSON は返る。
- `logs/operational.log` に `Slack delivery failed` が記録される。

#### SummaryMessage の扱い

Ticket 5 時点では hook から `SummaryMessage` は生成されない。自動テストでは `SummaryMessage` を手動生成して dispatcher に渡し、terminal / Slack の配送経路のみを確認する。

サマリー生成エンジン、生成トリガー、LLM 呼び出しは後続 TODO とする。
