# funhou-hook

AI エージェントの作業を「分報」として外に流し、人間がチラ見で監視・介入できるようにするための Python プロジェクトです。設計の中心は [docs/design.md](docs/design.md) にあり、現段階ではそのコアになるメッセージ型と開発環境を整えています。

## 方向性

このリポジトリは、設計書にある次の方針に寄せてセットアップしています。

- コアはプラットフォーム非依存に保つ
- `log` / `summary` / `approval` を統一フォーマットとして扱う
- 最小構成から始めて、hooks・判定・通知アダプターを段階的に育てる

そのため、初期コードは通知実装より先に、ドメインの核になるメッセージ型を `src/funhou_hook/` に置いています。Phase 1 ではさらに、PreToolUse フックの最小骨格として `hook.py` からログ出力までを通せるようにしています。

## 開発環境

- Python: 3.14 系
- パッケージ管理: `uv`
- lint / format: `ruff`
- テスト: `pytest`
- 設定集約: `pyproject.toml`

2026-04-11 時点で Python.org のダウンロードページに掲載されている最新安定版は Python 3.14.0 だったため、`requires-python` と `ruff` の target は 3.14 に合わせています。

## セットアップ

`uv` が未導入なら先にインストールしてください。

```powershell
uv python install 3.14
uv sync --dev
```

`.python-version` を置いているので、`uv` を使う前提で Python 3.14 系を選びやすくしています。

## よく使うコマンド

```powershell
uv run pytest
uv run ruff check .
uv run ruff format .
```

まとめて確認したいときは次の順がおすすめです。

```powershell
uv run ruff check .
uv run pytest
```

## Phase 1 フックの動かし方

Claude Code の PreToolUse フックから `hook.py` を呼び出す想定です。最小構成では、stdin の JSON からツール名と対象を取り出し、`config/funhou.toml` の hard rules で危険度を付けて `/tmp/funhou.log` に 1 行追記します。

手元での簡易確認例:

```powershell
'{"tool_name":"Read","tool_input":{"file_path":"src/config.ts"}}' | uv run python hook.py
Get-Content /tmp/funhou.log -Tail 5
```

返り値は標準出力の JSON です。

```json
{"level":"info","tool":"Read"}
```

## ディレクトリ構成

```text
src/funhou_hook/    コアのメッセージ型と Phase 1 の実装
config/funhou.toml  Phase 1 の hard rules
hook.py             PreToolUse フック入口
tests/              pytest による最小テスト
docs/design.md      設計書への入口
docs/ai-agent-funhou-system.md  詳細設計
pyproject.toml      Python 開発設定の集約点
```

## 現在の実装範囲

現時点では、設計書の「コア出力」に対応する基本型を定義しています。

- `LogMessage`
- `SummaryMessage`
- `ApprovalMessage`

これらを起点に、今後は以下の順で拡張しやすい構成にしています。

1. hooks からのイベント取り込み
2. 危険度判定ロジック
3. サマリー生成
4. stdout / Slack などの通知アダプター

## 補足

Phase 1 は hard rules のみを対象にしており、AI スクリーニング、サマリー生成、Slack 連携、承認フローはまだ実装していません。
