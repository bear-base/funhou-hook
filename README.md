# funhou-hook

`funhou-hook` は、Claude Code の hook からツール実行や停止通知を受け取り、危険度付きの 1 行ログとして `/tmp/funhou.log` に流すための最小プロトタイプです。

Phase 1 では次の流れが動く状態を目指しています。

1. Claude Code の hook として `hook.py` が呼ばれる
2. stdin の JSON からツール実行・承認待ち・入力待ち・承認結果を取り出す
3. `config/funhou.toml` の hard rules と基本設計に基づいてメッセージ型を決める
4. 1 行ログに整形する
5. `/tmp/funhou.log` に追記する
6. ログを見ると、作業中だけでなく承認待ちや入力待ち、その結果も追える

設計の背景は [docs/design.md](docs/design.md) にあります。

## 前提

- Python 3.14 系
- `uv`
- Claude Code が使えること

このリポジトリでは Python の依存管理を `uv`、lint/format を `ruff`、テストを `pytest` に統一しています。

## インストール

最初にリポジトリ直下で依存を同期します。

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

以後、このリポジトリでは `uv run ...` でコマンドを実行します。

## Claude Code への組み込み

Claude Code の hook 設定は `.claude/settings.json` に書きます。まだファイルが無ければ作成してください。

最小構成の例:

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

この設定では次を拾います。

- `PreToolUse`: 通常の作業ログ
- `Notification(permission_prompt)`: 承認待ち
- `Notification(idle_prompt)`: 入力待ち
- `PermissionRequest`: 承認対象の内部追跡
- `PostToolUse` / `PostToolUseFailure`: 実行後の結果と、承認された経緯
- `PermissionDenied`: auto mode による拒否結果

Claude Code をリポジトリ直下で起動するなら、上の設定で十分です。別ディレクトリから起動する可能性があるなら、絶対パス寄りにすると安全です。

Windows の場合:

```json
{
  "type": "command",
  "command": "powershell -NoProfile -Command \"Set-Location 'C:\\path\\to\\funhou-hook'; uv run python hook.py\""
}
```

それ以外の場合:

```json
{
  "type": "command",
  "command": "cd /abs/path/to/funhou-hook && uv run python hook.py"
}
```

## ログの見方

別ターミナルでログを監視します。

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
10:03:18 [APPROVAL] Notification: {"command": "Permission needed", "reason": "Claude needs your permission to use Bash"}
10:03:19 [INFO] Bash: Approval granted: Bash rm -rf dist
10:03:20 [INFO] Bash: Completed Bash rm -rf dist
10:03:31 [WARN] Notification: Waiting for input: Claude is waiting for your input
10:03:45 [DANG] Bash: Approval denied: Bash git push origin main (Auto mode denied: command targets a path outside the project)
```

## 動作確認

### 1. `hook.py` 単体確認

通常の `PreToolUse`:

Windows の場合:

```powershell
'{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

承認待ち (`permission_prompt`):

Windows の場合:

```powershell
'{"hook_event_name":"Notification","notification_type":"permission_prompt","title":"Permission needed","message":"Claude needs your permission to use Bash"}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"Notification","notification_type":"permission_prompt","title":"Permission needed","message":"Claude needs your permission to use Bash"}' | uv run python hook.py
```

入力待ち (`idle_prompt`):

Windows の場合:

```powershell
'{"hook_event_name":"Notification","notification_type":"idle_prompt","title":"Waiting for input","message":"Claude is waiting for your input"}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"Notification","notification_type":"idle_prompt","title":"Waiting for input","message":"Claude is waiting for your input"}' | uv run python hook.py
```

### 2. Claude Code での確認

1. `.claude/settings.json` を保存する
2. 別ターミナルで `/tmp/funhou.log` を監視する
3. Claude Code で通常の読取操作を実行して作業ログが流れることを確認する
4. 承認が必要な操作を発生させて `permission_prompt` が出ることを確認する
5. 承認後に `Approval granted` と実行結果が出ることを確認する
6. 入力待ちになったときに `idle_prompt` が出ることを確認する

## 設定ファイル

```text
hook.py                         Claude Code から直接呼ぶ入口
config/funhou.toml              hard rules とログ出力先
src/funhou_hook/hook.py         stdin JSON の読込とイベント解釈
src/funhou_hook/classifier.py   危険度判定
src/funhou_hook/formatter.py    1 行ログ整形
src/funhou_hook/dispatcher.py   /tmp/funhou.log への追記
src/funhou_hook/messages.py     log / summary / approval の型
```

## いま入っていないもの

- AI スクリーニング
- サマリー生成
- Slack 連携
- 承認フロー本体
- Codex 対応実装

Codex 対応の検討メモは [docs/features/codex-support.md](docs/features/codex-support.md) にあります。
