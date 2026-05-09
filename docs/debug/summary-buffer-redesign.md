# Summary Buffer Redesign

**このドキュメントは採用しない**
このドキュメントは LLM summary の出力エラーが起きた際、原因を「入力が大きすぎることによる構造的問題」と推測して書かれた検討メモである。
しかし実際の原因は thinking model における `MAX_TOKENS` 切れであり、このドキュメントが前提としていた「入力肥大化」は事実ではなかった。
そのため、本ドキュメントの修正方針は採用しない。

詳しい経緯と真因は [`summary-engine-llm-integration.md`](./summary-engine-llm-integration.md)を参照。

ただし、本ドキュメントが提起した構造的論点(terminal log を再パースする方式の脆さ、buffer の lifecycle、failure 時の扱い等)は、将来 summary engine の構造改善が必要になった際の参考として残す。

## 現状の課題

現在の summary engine は、terminal 向け通知ログである `/tmp/funhou.log` を offset で読み取り、その差分を LLM に渡して `SummaryMessage` を生成する設計になっている。

この設計は「ターン単位の要約」を実現する入力として不適切である。`funhou.log` は人間が tail して読むための表示済みログであり、サマリー生成用の構造化イベントログではない。そこには長い shell command、commit message、heredoc、過去ターン、承認要求、サマリー結果などが混在する。

結果として、summary engine が「今ターンの作業内容」ではなく「前回 offset 以降に残っている表示ログ」を処理する構造になっている。この構造では、summary の ON/OFF、LLM 障害、parse 失敗、state 消失、ログローテーションのたびに、サマリー入力が過去ログの未処理キューとして膨らむ。

特に問題なのは次の点である。

- 初回または state 消失時に、既存の `/tmp/funhou.log` を大量に読み込む
- summary OFF 中のログが、ON に戻した後の入力に混入する
- LLM 障害や parse 失敗時に offset を進めない設計だと、次回以降に同じ大きな入力を再処理する
- terminal 表示文字列を再パースするため、通知フォーマット変更が summary 入力にも影響する
- `[SUMMARY]` 行など、summary の出力が次回 summary の入力に混ざる循環が起きうる
- 長い command や heredoc を要約用に制御できず、LLM 入力が肥大化する

この問題は、単に `max_log_chars` を下げる、初回だけ tail 初期化する、parse 失敗時に offset を進める、といった局所修正では根本解決しない。summary engine の入力を terminal log から分離し、hook 処理時に作る構造化 buffer を要約対象にする必要がある。

## 検証済みの事実（ログ等）

- `SummaryMessage` の型、terminal formatter、Slack formatter、dispatcher の `summary` 配送判定は既に存在する。
- `Stop` hook を追加すると、Claude Code から `Stop` イベント自体は検知できる。
- `PermissionRequest` イベント内で summary 生成処理を呼び出すことはできる。
- 現行 summary engine は `funhou.log` を offset で読み、`max_log_chars` を超える場合は末尾だけを LLM に渡している。
- 実運用ログで、`PermissionRequest` 時に summary source が `log_count=850`, `char_count=8000` になった。
- 実運用ログで、Gemini 返答が JSON として parse できず、`SummaryMessage` が生成されなかった。
- 実運用ログで、Gemini から抽出した text が `{\n  "message": "` のように途中で終わって見えるケースがあった。
- 現行実装では、parse 失敗時に `SummaryMessage` が作られないため Slack へ summary は配送されない。
- `funhou.log` には長い commit command や heredoc を含む Bash ログが入っていた。
- `config/funhou.toml` では `message_types = ["log", "summary", "approval"]` のように Slack 側の summary 購読は有効にできる。

## 未検証の仮説

- Gemini の invalid JSON は、入力ログが大きすぎる、または長い command / heredoc が混ざることで出力が不安定になっている可能性がある。
- `funhou.log` の末尾切り出しでは、ターンの意味的な境界を保てず、LLM にとって要約しにくい入力になっている可能性がある。
- terminal 表示文字列ではなく `LogMessage` / `ApprovalMessage` の構造化データを渡せば、短く安定した summary prompt を作れる可能性が高い。
- summary OFF 中や LLM 障害中のログを後から回収しない方が、分報システムの用途に合っている可能性が高い。
- `PermissionRequest` 前 summary は、承認要求そのものを buffer に入れる前に発火した方が、「ここまでの経緯」として自然になる可能性が高い。
- `Stop` summary と `PermissionRequest` summary が短時間に連続する場合、buffer の cursor または flush 方針で重複要約を防げる可能性がある。

## 修正方針

summary engine の入力を `/tmp/funhou.log` から切り離し、hook 処理中に生成した `FunhouMessage` を summary 用の構造化 buffer に保存する方式へ再設計する。

### 基本方針

- terminal log は人間向け通知ログとして扱い、summary 入力には使わない。
- summary 入力は `LogMessage` / `ApprovalMessage` などの構造化イベントから作る。
- summary はベストエフォート機能とし、失敗したログを後で必ず回収する責務を持たせない。
- summary OFF 中のイベントは buffer に溜めない。
- LLM 失敗、parse 失敗、空文字応答の場合でも、そのトリガー時点の buffer は閉じる、または cursor を進める。
- 成功時のみ `SummaryMessage` を dispatcher に渡す。

### 提案する処理フロー

通常 hook event の処理:

1. `hook.py` が stdin payload を読む。
2. `_build_messages()` が `LogMessage` / `ApprovalMessage` を作る。
3. summary が有効なら、summary 対象の message を summary buffer に追記する。
4. dispatcher が terminal / Slack へ通常配送する。

`PermissionRequest` の処理:

1. 既存 buffer を読み、承認要求前の経緯として summary 生成を試みる。
2. summary 成功時は `SummaryMessage` を dispatcher に渡す。
3. 成功/失敗に関係なく、その時点の buffer を閉じる、または cursor を進める。
4. その後 `ApprovalMessage` を生成し、必要なら次区間の buffer に入れる。
5. `ApprovalMessage` を dispatcher に渡す。

`Stop` の処理:

1. 既存 buffer を読み、ターン終了 summary 生成を試みる。
2. summary 成功時は `SummaryMessage` を dispatcher に渡す。
3. 成功/失敗に関係なく、buffer を閉じる、または cursor を進める。

### Summary Buffer のデータ案

保存形式は JSON Lines を第一候補とする。

```json
{
  "timestamp": "2026-05-09T11:44:12Z",
  "session_id": "demo-session",
  "hook_event_name": "PreToolUse",
  "message_type": "log",
  "level": "warning",
  "tool": "Bash",
  "target": "npm run build",
  "message": "Bash npm run build"
}
```

`SummaryMessage` 自体は buffer に入れない。summary 出力を次回 summary の入力に混ぜないためである。

### 保存先案

候補:

- `/tmp/funhou-summary-buffer.jsonl`
- `/tmp/funhou-summary-buffer/<session_id>.jsonl`
- `/tmp/funhou-summary-buffer/<workspace_hash>/<session_id>.jsonl`

初期実装では単一 JSONL でもよいが、並行実行や複数セッション混在を考えると `session_id` 単位の分割を検討する必要がある。

### Prompt 入力案

LLM に渡す前に、buffer event を要約用の短いテキストへ整形する。

方針:

- `tool`, `target`, `level`, `message` を中心にする
- 長い `target` は保存時または prompt 化時に短縮する
- heredoc や commit message は全文ではなく先頭/末尾、または `multiline_command` として要約する
- `trigger`, `event_count`, `truncated` を prompt に含める

### 結果に関わらず buffer を進める

summary は監査ログではないため、LLM 失敗時に同じ buffer を次回再処理しない。

結果別の扱い:

- 成功: `SummaryMessage` を出し、buffer を閉じる
- 空文字: summary は出さず、buffer を閉じる
- LLM 失敗: summary は出さず、buffer を閉じる
- parse 失敗: summary は出さず、buffer を閉じる

失敗内容は Operational Log に残す。

### 検討すべき点

#### 1. buffer の粒度

- 単一 buffer にするか、`session_id` 単位に分けるか
- `cwd` や repository 単位も分離軸に含めるか
- Claude Code の `session_id` が常に存在する前提にできるか
- `session_id` が無い場合の fallback key をどうするか

#### 2. buffer の lifecycle

- `Stop` で truncate するか、cursor を進めるだけにするか
- `PermissionRequest` で buffer を閉じる場合、直後の `ApprovalMessage` をどの区間に入れるか
- hook process が並行実行される場合の追記競合をどう扱うか
- 古い buffer file の cleanup をどうするか

#### 3. 失敗時の扱い

- LLM 失敗時に buffer を必ず閉じるか
- parse 失敗時に raw response をどこまで Operational Log に出すか
- API key や機密情報が raw response / prompt に混ざらない保証をどう置くか
- 一時的な Gemini 障害時に summary を諦める判断でよいか

#### 4. 入力圧縮

- 長い command をどの時点で短縮するか
- Bash の heredoc や commit message をどう扱うか
- `target` と `message` の重複をどう削るか
- `max_events`, `max_chars`, `max_target_chars` の妥当な初期値

#### 5. prompt 仕様

- JSON 出力形式をどこまで厳密にするか
- `message` / `next` 以外のフィールドを持たせるか
- `trigger=PermissionRequest` のときに承認判断用の文体へ寄せるか
- `trigger=Stop` のときにターン完了 summary へ寄せるか

#### 6. 設定項目

候補:

```toml
[summary]
enabled = true
provider = "gemini"
model = "gemini-flash-latest"
buffer_path = "/tmp/funhou-summary-buffer"
max_events = 80
max_chars = 4000
max_target_chars = 300
```

検討点:

- 既存の `state_path` を廃止するか、cursor 管理用に残すか
- `buffer_path` は file か directory か
- summary 専用 Slack channel 設定と同じチケットで扱うか

#### 7. 既存実装からの移行

- 現在の `summary_engine.py` の offset 読み取り実装を削除するか
- `read_summary_source()` の責務を buffer reader に置き換えるか
- 既存テストのうち、offset 前提のテストをどう置き換えるか
- 既存 `SummaryMessage.trigger` は維持するか

#### 8. Operational Log

記録すべきイベント:

- `Summary buffer appended`
- `Summary buffer loaded`
- `Summary buffer closed`
- `Summary generation skipped`
- `Summary generated`
- `Summary generation failed`

検討点:

- Operational Log に prompt 本文を出すべきか
- raw LLM response を一時的な調査ログとして出すか、恒久ログにするか
- `docs/logging.md` の Operational Log カタログへ正式反映するか

#### 9. テスト方針

必要なテスト:

- summary OFF のとき buffer に保存しない
- 通常 log event が buffer に保存される
- `SummaryMessage` は buffer に保存されない
- `PermissionRequest` で summary が approval より先に生成される
- `Stop` で buffer が閉じる
- LLM 失敗時も同じ buffer を再処理しない
- 長い command が prompt 化時に短縮される
- session_id ごとに buffer が分離される

#### 10. 今回の暫定ログの扱い

現在の調査用ログは原因切り分けには有効だが、恒久運用ログとしては過剰な可能性がある。

検討点:

- `raw_output` や Gemini raw response を残すログを削除するか
- 残す場合、Debug Log 実装後に移すか
- Operational Log にはエラー種別と長さだけ残すか
