# Approval State Reliability

## 背景

Claude Code 向け hook の承認まわりでは、`PermissionRequest` を承認待ちの起点とし、`PostToolUse` / `PostToolUseFailure` / `PermissionDenied` を結果イベントとして扱っている。

今回の調査では、通常の `PreToolUse` ログは出力される一方で、承認待ち・承認後のログが欠落する事象が発生した。エラーログからは、共有状態ファイル `/tmp/funhou-approval-state.json` の JSON 破損により、承認系イベント処理が途中で異常終了していたことが確認された。

```text
json.decoder.JSONDecodeError: Expecting value
```

この事象は、単一の共有 JSON ファイルに承認状態を集約する設計が、並行実行される hook プロセスに対して脆弱であることを示している。

## 今回の調査で確定したこと

今回の debug ログと traceback から、次の事実が確認できた。

- `PreToolUse` は通常どおり発火し、通常ログも出力されている
- `PermissionRequest` と `PostToolUse` も Claude Code から実際に送られている
- 問題は「イベントが来ていない」ことではなく、hook 内部で承認系処理が落ちていること
- 例外は `PostToolUse` 処理中の `_load_pending_approvals()` で発生していた
- `funhou-approval-state.json` は壊れた JSON ではなく、0 バイトの空ファイルとして読まれていた
- `json.loads("")` により `JSONDecodeError` が発生し、承認系ログが出る前に hook が異常終了していた
- 承認対象は `Bash` だけではなく、`Edit` でも発生している
- したがって、相関設計や状態保存は Bash 専用前提では不十分である

代表的な観測ログは次のとおり。

```text
state.load.read bytes=0 chars=0
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

## 問題の整理

現行設計の弱点は次のとおり。

- 承認系イベントだけが共有 state file の読み書きに依存している
- `PreToolUse` は state file を使わないため、通常ログだけ生き残り、承認ログだけ落ちる
- state file が壊れると hook 全体が異常終了し、ユーザー向け分報まで失われる
- 単一 JSON ファイルは並行更新、途中書き、空ファイル読込に弱い
- 障害時に「どこまで処理が進んだか」を追う診断情報が不足している
- 承認対象ツールが `Bash` に限られないため、ツール非依存の相関設計が必要になる

## 設計方針

修正の方向は、最小の対症療法ではなく、以下を満たす構成へ寄せることを目標とする。

- 壊れても hook 全体は止まらない
- 承認系イベントの経緯を後から追跡できる
- 並行実行に耐える
- デバッグしやすい
- 将来の summary や外部連携に拡張しやすい
- `Bash` 以外の承認対象にもそのまま適用できる

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
- `session_id + normalized target` は補助キーにする
- fallback を持たせる
- `target` は Bash の command だけでなく、Edit の file path なども含む一般化された対象として扱う

### 利点

- 同一セッションでの衝突を減らせる
- 承認待ちと実行結果の対応付け精度が上がる
- `Bash` 以外のツールにも流用できる

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

## 今回、実装前に決めること

本修正に入る前に、少なくとも次の 3 点を決める必要がある。

### 1. 壊れた state file をどう扱うか

候補:

- 壊れたファイルを退避して、空状態として継続する
- 壊れたファイルをその場で削除して継続する
- 壊れたファイルを残したまま、読み込み失敗時だけ空状態として扱う

推奨:

- 退避して、空状態として継続する

### 2. 当面の state 保存方式をどうするか

候補:

- 単一ファイルのまま、atomic write とフェイルソフトを入れる
- `session_id` 単位の分割ファイルにする
- `tool_use_id` 単位の分割ファイルにする
- append-only イベントログへ寄せ、pending は補助的に持つ

推奨:

- Phase 1 では単一ファイルのまま atomic write とフェイルソフトを入れる
- 次段階でイベントログ正本化を検討する

### 3. 承認相関キーを何にするか

候補:

- 現行どおり `session_id + tool + target`
- `tool_use_id` 優先、無い場合は `session_id + tool + target`
- `session_id + normalized target` のみに寄せる

推奨:

- `tool_use_id` 優先、無い場合は `session_id + tool + target`

## 読む場所の案内

今回の意思決定に必要なのは、文書全体ではなく次の 3 箇所で十分である。

- 「今回の調査で確定したこと」: 何が事実として分かったか
- 「推奨する全体方針」: 大きな方向性
- 「今回、実装前に決めること」: いま選ぶ必要がある論点

この 3 箇所を読めば、実装に入るための判断ができる。

## 今やらないこと

この文書は設計検討の記録であり、以下の詳細実装まではここでは扱わない。

- イベントストア実装の具体クラス設計
- file lock の実装方式の確定
- Windows / Linux / macOS ごとの差分吸収方法の詳細
- Phase 2 以降の summary / Slack 連携仕様の具体化
