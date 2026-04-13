# funhou-hook

`funhou-hook` は、Claude Code の hook からツール実行や停止通知を受け取り、危険度付きの 1 行ログとして `/tmp/funhou.log` に流すための最小プロトタイプです。

Phase 1 では次の流れが動く状態を目指しています。

1. Claude Code の `PreToolUse` フックとして `hook.py` が呼ばれる
2. Claude Code の `Notification` フックとしても `hook.py` が呼ばれる
3. stdin の JSON からツール名や通知種別を取り出す
4. `config/funhou.toml` の hard rules で危険度を判定する
5. 1 行ログに整形する
6. `/tmp/funhou.log` に追記する
7. ログを見れば、実行中だけでなく承認待ちや入力待ちも分かる

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

よく使う確認コマンド:

Windows の場合:

```powershell
uv run ruff check .
uv run pytest
```

それ以外の場合:

```bash
uv run ruff check .
uv run pytest
```

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

この設定では、通常の `PreToolUse` に加えて、次の Notification も拾います。

- `permission_prompt`: 承認待ちで止まっている状態
- `idle_prompt`: 入力待ちで止まっている状態

`hook.py` は stdin から hook payload を受け取り、`config/funhou.toml` を読んで危険度を判定し、`/tmp/funhou.log` に 1 行追記します。

Claude Code をリポジトリ直下で起動するなら、上の設定で十分です。別のディレクトリから起動する可能性があるなら、絶対パス寄りの書き方にしておくと安全です。

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

ログは 1 行ずつ追記されます。たとえば次のような形式です。

```text
10:03:12 [INFO] Read: Read src/config.ts
10:03:18 [WARN] Notification: Claude is waiting for your input
10:03:24 [APPROVAL] Notification: {"command": "Permission needed", "reason": "Claude needs your permission to use Bash"}
```

## 動作確認

初めて使うときは、次の順番で確認するのがおすすめです。

### 1. `hook.py` 単体で動くか確認する

まずは Claude Code を介さず、標準入力にサンプル JSON を流して確認します。

通常の `PreToolUse` 確認:

Windows の場合:

```powershell
'{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

`permission_prompt` の確認:

Windows の場合:

```powershell
'{"hook_event_name":"Notification","notification_type":"permission_prompt","title":"Permission needed","message":"Claude needs your permission to use Bash"}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"Notification","notification_type":"permission_prompt","title":"Permission needed","message":"Claude needs your permission to use Bash"}' | uv run python hook.py
```

`idle_prompt` の確認:

Windows の場合:

```powershell
'{"hook_event_name":"Notification","notification_type":"idle_prompt","title":"Waiting for input","message":"Claude is waiting for your input"}' | uv run python hook.py
```

それ以外の場合:

```bash
printf '%s' '{"hook_event_name":"Notification","notification_type":"idle_prompt","title":"Waiting for input","message":"Claude is waiting for your input"}' | uv run python hook.py
```

続けてログを確認します。

Windows の場合:

```powershell
Get-Content /tmp/funhou.log -Tail 10
```

それ以外の場合:

```bash
tail -n 10 /tmp/funhou.log
```

### 2. Claude Code に hook を設定する

上の `.claude/settings.json` を保存し、Claude Code がその設定を読む状態にします。

### 3. 別ターミナルでログを監視する

Windows の場合:

```powershell
Get-Content /tmp/funhou.log -Wait
```

それ以外の場合:

```bash
tail -f /tmp/funhou.log
```

### 4. Claude Code で通常操作を確認する

たとえば「README を読んで」や「このファイルを確認して」のような軽い指示を出します。`PreToolUse` が発火すれば、`/tmp/funhou.log` に通常の作業ログが流れます。

### 5. 承認待ち・入力待ちを確認する

次の状態で `Notification` が流れます。

- Claude が権限承認を求めて止まったとき: `permission_prompt`
- Claude がユーザー入力待ちで止まったとき: `idle_prompt`

これらも同じ `/tmp/funhou.log` に出るので、別ウィンドウで監視していれば「いま止まっている理由」が分かります。

### 6. 危険度判定を確認する

`config/funhou.toml` には初期ルールが入っています。

- `Read|Glob|Grep` は `info`
- `Notification(idle_prompt)` は `warning`
- `Notification(permission_prompt)` は `danger`
- `Bash(*test*|*lint*)` は `info`
- `Bash(*deploy*|*migrate*)` は `danger`
- `Edit(*.env*)` は `danger`
- それ以外は `warning`

ルールを変えたら、同じように Claude Code を動かしてログレベルが変わることを確認してください。

## 設定ファイル

Phase 1 で関係する主なファイルは次のとおりです。

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

Phase 1 ではまだ次はやっていません。

- AI スクリーニング
- サマリー生成
- Slack 連携
- 承認フロー本体
- Codex 対応実装

Codex 対応の検討メモは [docs/features/codex-support.md](docs/features/codex-support.md) にあります。
