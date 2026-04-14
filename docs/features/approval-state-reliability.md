# Approval State Reliability

## 背景

Claude Code 向け hook の承認まわりでは、`PermissionRequest` を承認待ちの起点とし、`PostToolUse` / `PostToolUseFailure` / `PermissionDenied` を結果イベントとして扱っている。

今回の調査では、通常の `PreToolUse` ログは出力される一方で、承認待ち・承認後のログが欠落する事象が発生した。エラーログからは、共有状態ファイル `/tmp/funhou-approval-state.json` の JSON 破損により、承認系イベント処理が途中で異常終了していたことが確認された。

```text
json.decoder.JSONDecodeError: Expecting value
```

この事象は、単一の共有 JSON ファイルに承認状態を集約する設計が、並行実行される hook プロセスに対して脆弱であることを示している。

## 問題の整理

現行設計の弱点は次のとおり。

- 承認系イベントだけが共有 state file の読み書きに依存している
- `PreToolUse` は state file を使わないため、通常ログだけ生き残り、承認ログだけ落ちる
- state file が壊れると hook 全体が異常終了し、ユーザー向け分報まで失われる
- 単一 JSON ファイルは並行更新、途中書き、空ファイル読込に弱い
- 障害時に「どこまで処理が進んだか」を追う診断情報が不足している

## 設計方針

修正の方向は、最小の対症療法ではなく、以下を満たす構成へ寄せることを目標とする。

- 壊れても hook 全体は止まらない
- 承認系イベントの経緯を後から追跡できる
- 並行実行に耐える
- デバッグしやすい
- 将来の summary や外部連携に拡張しやすい

## 提案 1: 共有 JSON 1枚を正本にしない

### 方針

`/tmp/funhou-approval-state.json` のような単一の共有ファイルを承認状態の正本にしない。

代わりに、承認イベントそのものを追記型で記録し、必要に応じて状態を再構成する設計へ寄せる。

### 具体案

- `PermissionRequest` を approval event として 1 行追記する
- `PostToolUse` / `PostToolUseFailure` / `PermissionDenied` も結果 event として 1 行追記する
- 正本は append-only の JSON Lines とする
- pending 状態は必要なら別途生成するが、正本はイベントログとする

### 利点

- 追記型のため競合に強い
- ファイル全体破損の影響を受けにくい
- 「何が起きたか」の監査と再現がしやすい
- 将来 summary や Slack 連携へ流用しやすい

## 提案 2: pending 状態は細かく分割する

### 方針

pending approval が必要な場合でも、1ファイル共有ではなく、粒度を小さくする。

### 具体案

- `session_id` 単位で state file を分ける
- 可能なら `tool_use_id` 単位で state file を分ける
- 1 pending approval = 1ファイル に近づける

### 例

- `/tmp/funhou-state/<session_id>/<tool_use_id>.json`
- `/tmp/funhou-state/<session_id>__<command-hash>.json`

### 利点

- 並行更新競合が大幅に減る
- 破損時の影響範囲が局所化される
- 調査時に対象を見つけやすい

## 提案 3: 書き込みを原子的にする

共有状態を持つ場合は、書き込みを必ず atomic write にする。

### 具体案

- 直接上書きせず、一時ファイルに完全な内容を書き込む
- 書き込み完了後に `replace` / rename で差し替える
- 読み込み時に JSONDecodeError が起きても hook 全体を落とさない

### 復旧方針

- 壊れた state file は退避する
- pending 状態は空として継続する
- 診断ログに復旧内容を残す

## 提案 4: hook をフェイルソフトにする

内部状態の破損や相関失敗で、ユーザー向けログまで失わないことを優先する。

### 方針

- 内部状態の保存に失敗しても、可能な範囲で approval 行を出す
- pending 読み込みに失敗しても、最低限 `Completed ...` / `Failed ...` は出す
- 相関付け失敗と、ツール実行結果ログを分離して扱う

### 期待される挙動

- state 破損時でも hook 全体は継続する
- 「承認との対応関係」は失われても、実行完了・失敗ログは残る
- 分報の継続性を優先できる

## 提案 5: 診断モードを正式機能にする

今回の切り分けでは debug ログが有効だったため、一時的な仕掛けではなく正式な診断モードとして設計に含める。

### 方針

- `debug.enabled` で ON/OFF できるようにする
- debug 出力先を設定可能にする
- 処理段階ごとの structured log を JSON Lines で残す

### 標準項目

- `timestamp`
- `stage`
- `hook_event_name`
- `session_id`
- `tool_use_id`
- `tool_name`
- `target`
- `message_count`
- `result`
- `error_type`
- `error_message`

### 段階例

- `received`
- `parsed`
- `message_built`
- `pending_saved`
- `pending_loaded`
- `message_dispatched`
- `log_appended`
- `error`

### 利点

- 障害箇所の特定が速くなる
- 今回のような「イベントは来ているがログが出ない」問題を追いやすい
- 今後の hook 全般の保守性が上がる

## 提案 6: 相関キーを強化する

現行の `session_id + signature` だけでは、同一セッション内の類似コマンドや文字列表現差に弱い可能性がある。

### 方針

- `tool_use_id` があるイベントでは、それを第一キーに使う
- `session_id + normalized command` は補助キーにする
- fallback を持たせる

### 利点

- 同一セッションでの衝突を減らせる
- 承認待ちと実行結果の対応付け精度が上がる

## 提案 7: ログの責務を分離する

1つの処理フローにすべてを詰め込まず、役割ごとに分離する。

### 分離対象

- ユーザー向け分報ログ
- 内部イベントログ
- pending 状態ストア

### 期待効果

- どれか1つが壊れても全体停止しにくい
- 見やすさと診断性を両立できる
- 将来の外部連携先を増やしやすい

## 推奨する全体方針

現時点では、次の構成を推奨する。

1. 承認イベントの正本は append-only なイベントログにする
2. pending 状態は `tool_use_id` か `session_id` 単位の小さな単位で管理する
3. state 操作は atomic write とフェイルソフトを前提にする
4. debug/diagnostic を正式サポートする
5. 相関キーは `tool_use_id` 優先にする
6. `Completed` / `Failed` の通常ログは、相関失敗でも可能な限り残す

## Phase 1 への適用の考え方

Phase 1 のゴールは Claude Code 向けの基本的な分報を安定して出すことであり、承認状態の共有 JSON 破損で hook 全体が止まる構成は避けたい。

そのため、Phase 1 の範囲でも少なくとも次は満たすべきである。

- 承認系イベントで hook が落ちない
- state 破損時も通常ログは継続する
- 診断に必要な情報を残せる
- 承認待ちから承認結果までの経緯を後から追える

## 今やらないこと

この文書は設計検討の記録であり、以下の詳細実装まではここでは扱わない。

- イベントストア実装の具体クラス設計
- file lock の実装方式の確定
- Windows / Linux / macOS ごとの差分吸収方法の詳細
- Phase 2 以降の summary / Slack 連携仕様の具体化
