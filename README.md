# funhou-hook

`funhou-hook` は、Claude Code の hook からツール実行を受け取り、危険度付きの 1 行ログとして `/tmp/funhou.log` に流すための最小プロトタイプです。

Phase 1 では次の流れが動く状態を目指しています。

1. Claude Code の `PreToolUse` フックとして `hook.py` が呼ばれる
2. stdin の JSON からツール名と対象を取り出す
3. `config/funhou.toml` の hard rules で危険度を判定する
4. 1 行ログに整形する
5. `/tmp/funhou.log` に追記する
6. `tail -f /tmp/funhou.log` で分報を見る

設計の背景は [docs/design.md](docs/design.md) にあります。

## 前提

- Python 3.14 系
- `uv`
- Claude Code が使えること

このリポジトリでは Python の依存管理を `uv`、lint/format を `ruff`、テストを `pytest` に統一しています。

## インストール

最初にリポジトリ直下で依存を同期します。

```powershell
uv python install 3.14
uv sync --dev
```

以後、このリポジトリでは `uv run ...` でコマンドを実行します。

よく使う確認コマンド:

```powershell
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
    ]
  }
}
```

この設定では、`PreToolUse` が発生するたびに Claude Code が `uv run python hook.py` を実行します。`hook.py` は stdin から hook payload を受け取り、`config/funhou.toml` を読んで危険度を判定し、`/tmp/funhou.log` に 1 行追記します。

もし Claude Code をリポジトリ外から起動する運用なら、`command` は絶対パスにしておくと安全です。

例:

```json
{
  "type": "command",
  "command": "cd /abs/path/to/funhou-hook && uv run python hook.py"
}
```

## ログの見方

別ターミナルで次を実行すると、分報ログを追いかけられます。

```bash
tail -f /tmp/funhou.log
```

PowerShell で見るなら、ほぼ同等の確認方法としてこちらでも大丈夫です。

```powershell
Get-Content /tmp/funhou.log -Wait
```

ログは 1 行ずつ追記されます。たとえば次のような形式です。

```text
10:03:12 [INFO] Read: Read src/config.ts
10:03:18 [WARN] Bash: Bash rm -rf dist
10:03:24 [DANG] Bash: Bash npm run deploy
```

## 動作確認

初めて使うときは、次の順番で確認するのがおすすめです。

### 1. `hook.py` 単体で動くか確認する

まずは Claude Code を介さず、標準入力にサンプル JSON を流して確認します。

```powershell
'{"tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
```

期待する標準出力:

```json
{"level": "info", "tool": "Read"}
```

続けてログを確認します。

```powershell
Get-Content /tmp/funhou.log -Tail 5
```

### 2. Claude Code に hook を設定する

上の `.claude/settings.json` を保存し、Claude Code がその設定を読む状態にします。

### 3. 別ターミナルでログを監視する

```bash
tail -f /tmp/funhou.log
```

### 4. Claude Code で簡単な操作をさせる

たとえば「README を読んで」や「このファイルを確認して」のような軽い指示を出します。

そのとき `PreToolUse` が発火すれば、`/tmp/funhou.log` に 1 行ずつログが流れます。

### 5. 危険度判定を確認する

`config/funhou.toml` には初期ルールが入っています。

- `Read|Glob|Grep` は `info`
- `Bash(*test*|*lint*)` は `info`
- `Bash(*deploy*|*migrate*)` は `danger`
- `Edit(*.env*)` は `danger`
- それ以外は `warning`

ルールを変えたら、同じように Claude Code を動かしてログレベルが変わることを確認してください。

## 設定ファイル

Phase 1 で関係する主なファイルは次のとおりです。

```text
hook.py                    Claude Code から直接呼ぶ入口
config/funhou.toml         hard rules とログ出力先
src/funhou_hook/hook.py    stdin JSON の読込と正規化
src/funhou_hook/classifier.py  危険度判定
src/funhou_hook/formatter.py   1 行ログ整形
src/funhou_hook/dispatcher.py  /tmp/funhou.log への追記
src/funhou_hook/messages.py    log / summary / approval の型
```

## いま入っていないもの

Phase 1 ではまだ次はやっていません。

- AI スクリーニング
- サマリー生成
- Slack 連携
- 承認フロー
- Codex 対応実装

Codex 対応の検討メモは [docs/features/codex-support.md](docs/features/codex-support.md) にあります。
