# funhou-hook

`funhou-hook` は、Claude Code の hook イベントを作業分報向けの `log` / `approval` / `summary` メッセージに整形し、terminal log や Slack に流すための hook adapter です。

Claude Code の作業中に起きるツール実行、承認待ち、入力待ち、作業区切りを見える形で残すことを目的にしています。

設計の背景は [docs/design.md](docs/design.md) にあります。

## 主な機能

- ツール実行を作業ログとして記録する
- 承認待ち・承認結果を通知する
- 入力待ち通知を記録する
- 作業区切りでサマリーを生成する
- terminal log と Slack に配送する

## 全体の流れ

1. Claude Code が hook イベントを発火する
2. `hook.py` が stdin の JSON payload を受け取る
3. payload を `log` / `approval` / `summary` に変換する
4. `config/funhou.toml` の設定に従って terminal log や Slack に配送する

## 前提

- Python 3.14 系
- `uv`
- Claude Code が使えること
- Slack に通知する場合は Slack Incoming Webhook URL
- サマリーを生成する場合は Gemini API key

このリポジトリでは Python の依存管理を `uv`、lint/format を `ruff`、テストを `pytest` に統一しています。

## セットアップ

リポジトリ直下で依存を同期します。

Windows の場合:

```powershell
uv python install 3.14
uv sync --dev
```

それ以外の場合:

```bash
uv python install 3.14
uv sync --dev
```

## Claude Code への組み込み

Claude Code の hook 設定は `.claude/settings.json` に書きます。まだファイルが無ければ作成してください。

設定例:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ],
    "PermissionDenied": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ],
    "PostToolUseFailure": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      },
      {
        "matcher": "idle_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hook.py"
          }
        ]
      }
    ]
  }
}
```

## 設定

基本設定は `config/funhou.toml` に書きます。

- `[[rules]]`: ツールや対象パスに応じた通知レベルのルール
- `[channels.terminal]`: terminal log の出力先と配送対象
- `[channels.slack]`: Slack 通知の有効化、配送対象、メンション設定
- `[summary]`: サマリー生成の有効化、モデル、生成タイミングなど

シークレットは `config/.env` に書きます。

```dotenv
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_MENTION_TO=<@U01234567>
GEMINI_API_KEY=...
```

Slack を使う場合は `SLACK_WEBHOOK_URL` を設定します。サマリーを使う場合は `GEMINI_API_KEY` を設定し、`config/funhou.toml` の `[summary].enabled` を `true` にします。

サマリーはデフォルトでは `Stop` hook で生成されます。承認待ちのたびにもサマリーを出したい場合は、`summary.triggers` に `PermissionRequest` を追加します。

```toml
[summary]
enabled = true
triggers = ["Stop", "PermissionRequest"]
```

## ログの見方

Windows の場合:

```powershell
Get-Content /tmp/funhou.log -Wait
```

それ以外の場合:

```bash
tail -f /tmp/funhou.log
```

ログ例:

```text
10:03:12 [INFO] Read: Read src/config.ts
10:03:18 [APPROVAL] Bash: Permission requested: Bash git status (Check git status and changed files)
10:03:19 [INFO] Bash: Approval granted: Bash git status
10:03:20 [INFO] Bash: Completed Bash git status
10:03:31 [WARN] Notification: Waiting for input: Claude is waiting for your input
10:03:45 [DANG] Bash: Approval denied: Bash git push origin main (Auto mode denied: command targets a path outside the project)
10:04:10 [SUMMARY] Git の状態確認と設定ファイルの確認を行いました。 | next=README の更新内容を確認する
```

## 動作確認

通常の `PreToolUse`:

Windows の場合:

```powershell
'{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

承認待ち (`PermissionRequest`):

Windows の場合:

```powershell
'{"hook_event_name":"PermissionRequest","tool_name":"Bash","session_id":"demo-session","tool_input":{"command":"git status","description":"Check repository status"}}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"PermissionRequest","tool_name":"Bash","session_id":"demo-session","tool_input":{"command":"git status","description":"Check repository status"}}' | uv run python hook.py
```

ターン終了サマリー (`Stop`):

Windows の場合:

```powershell
'{"hook_event_name":"Stop","session_id":"demo-session"}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"Stop","session_id":"demo-session"}' | uv run python hook.py
```
