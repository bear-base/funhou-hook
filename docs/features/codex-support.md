# Codex Support Considerations

## 目的

このドキュメントは、`funhou-hook` を Codex CLI に対応させる可能性を整理するための検討メモです。

現時点の Phase 1 の実装対象は Claude Code 向けですが、Codex にも Hooks フレームワークが存在するため、将来対応の余地と制約を明文化しておきます。

参考資料:
- OpenAI Developers: [Hooks – Codex](https://developers.openai.com/codex/hooks)

## Codex Hooks の現状

Codex には hooks フレームワークがあり、`hooks.json` でフックを設定できます。主な配置先は以下です。

- `~/.codex/hooks.json`
- `<repo>/.codex/hooks.json`

複数の `hooks.json` が存在する場合、Codex はそれらをまとめて読み込みます。上位レイヤーが下位レイヤーを置き換えるのではなく、マッチした hook がそれぞれ動作します。

また、hooks は feature flag で有効化する必要があります。

```toml
[features]
codex_hooks = true
```

2026-04-12 時点の公式ドキュメントでは、Codex Hooks は experimental とされており、Windows は一時的に無効化されていると記載されています。

## 対応状況と制限事項

Codex Hooks は `PreToolUse` / `PostToolUse` に対応していますが、現時点のランタイムではどちらも `Bash` ツールのみを emit します。つまり、matcher として `Edit|Write` のような正規表現は設定できても、現在の Codex では実際にはマッチしません。

Phase 1 の分報システムに関係する制約は次のとおりです。

- `PreToolUse` は現在 `Bash` のみ対応
- `PostToolUse` も現在 `Bash` のみ対応
- `tool_input.command` から、これから実行する Bash コマンドを取得できる
- `PostToolUse` では `tool_response` を受け取れるが、実行済みコマンドの副作用は取り消せない
- plain text の `stdout` は `PreToolUse` / `PostToolUse` では無視される
- `PreToolUse` は `systemMessage` と block 系の JSON 出力をサポートする
- `PostToolUse` は `systemMessage`、`continue: false`、`stopReason` をサポートする
- matching hook は複数並列で起動されるため、1つの hook が他の hook の起動を止めることはできない
- hooks は turn scope で実行される
- Windows は現時点で無効

公式 docs ではさらに、`PreToolUse` / `PostToolUse` による interception は完全ではなく、単純な shell 呼び出しだけが対象で、`unified_exec` など新しい経路の interception は未完成とされています。また、`MCP`、`Write`、`WebSearch` などの非 shell ツール呼び出しは intercept できません。

## Claude Code Hooks との差分

Claude Code 向けに想定している Phase 1 は、設計書の粒度に近い「ツール呼び出し全般の分報」です。これに対して、Codex Hooks は現時点では Bash 観測に強く寄った仕組みです。

差分を整理すると、次のようになります。

- Claude Code 向けの想定: `Read` / `Edit` / `Bash` など複数ツールを対象にできる
- Codex Hooks の現状: `PreToolUse` / `PostToolUse` ともに `Bash` のみ
- Claude Code 向けの設計意図: 設計書にある `log` / `summary` / `approval` を将来的に全ツールへ広げる
- Codex Hooks の現状: まずは shell コマンドの可視化に用途が限定される
- Claude Code 向けの Phase 1: `tail -f /tmp/funhou.log` で全体の作業分報を見せる方向
- Codex Hooks の現状: `tail -f` 自体は可能でも、観測できるのは主に Bash 実行前後のみ

この差分により、Codex 対応を行う場合でも「Claude Code 用の hook をそのまま流用する」より、「共通コアを保ちつつ、Codex 入力専用の adapter を別で持つ」設計のほうが自然です。

## 対応する場合の方針

Codex に対応する場合の方針は、Claude Code 向け実装を無理に共通化しすぎず、別アダプターとして割り切ることです。

具体的には次の構成がよいと考えます。

- `classifier` / `formatter` / `dispatcher` / `messages` は共通コアとして使う
- Claude Code と Codex で異なるのは hook payload の形なので、入力正規化だけ別アダプターにする
- Codex 向け adapter は `tool_input.command` を `ToolEvent` 相当へ正規化する
- Codex 向けの hard rule は実質 `Bash(...)` 中心で運用する
- `PreToolUse` は「これから実行する Bash コマンドの分報」に使う
- 必要なら `PostToolUse` は「実行結果の後追いログ」に使う

この方針を取ると、分報システムのコアフォーマットである `log` / `summary` / `approval` は維持しつつ、Codex の制約に合わせて観測範囲だけを限定できます。

要するに、Codex 対応は「Claude Code 互換の完全移植」ではなく、「Bash 中心の別アダプターを同じコアの前段に差し込む」形が妥当です。

## 今やらない理由

Phase 1 の今回のゴールは、Claude Code 向けの最小プロトタイプを完成させることです。

今 Codex 対応を同時に進めない理由は次のとおりです。

- Codex Hooks は experimental であり、仕様変更の可能性がある
- Windows では現時点で無効とされているため、手元環境での検証コストが高い
- `PreToolUse` / `PostToolUse` が現在 `Bash` のみで、設計書の理想である全ツール分報とは観測範囲が異なる
- Claude Code 向け Phase 1 を先に成立させたほうが、共通コアの妥当性を落ち着いて検証できる
- Codex 対応は「別アダプターとしての設計判断」を含むため、Phase 1 に同時投入すると焦点がぼやける

そのため、現時点では Claude Code 向けを優先し、Codex 対応は Phase 1 完了後の拡張テーマとして扱うのが適切です。

## 将来対応時の最小スコープ

将来 Codex 対応を始める場合、最初のスコープは次の程度に絞るのが現実的です。

1. `.codex/hooks.json` を repo-local に追加する
2. `PreToolUse` の `Bash` matcher に限定する
3. `tool_input.command` を読んで hard rule で危険度判定する
4. `/tmp/funhou.log` に 1 行追記する
5. 必要に応じて `PostToolUse` を追加し、Bash 結果ログを残す

この段階では、`Read` / `Edit` / `WebSearch` などの分報は対象外と割り切るのがよいです。
