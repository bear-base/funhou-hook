# 現状の課題

- 現在の主問題は、Claude Code 上のユーザー承認結果が `funhou.log` に安定して記録されないことである。
- 現行コードでは、[hook.py](/C:/workspace/bear-base/funhou-hook/src/funhou_hook/hook.py) が `PermissionRequest` を承認待ちの起点として処理し、`PostToolUse` / `PostToolUseFailure` / `PermissionDenied` を承認結果側のイベントとして処理している。
- 承認相関は `_extract_correlation_keys()` で生成した `tool_use_id` と fallback key を用い、`_put_pending_approval()` で `/tmp/funhou-approval-state.json` に保存し、`_pop_pending_approval()` で結果イベント到達時に取り出す構造になっている。
- `PermissionRequest` では `ApprovalMessage` を生成するが、承認結果側では pending state の相関に失敗すると `Approval granted` / `Approval denied` の代わりに `ERROR` ログを出す設計になっている。
- 承認結果の取得可否は、Claude Code からのイベント送信、hook 内の相関キー生成、state file の保存・復旧、結果イベント到達時の取り出し、という複数段階に依存している。

## 検証済みの事実（ログ等）

- `PermissionRequest` は Claude Code から実際に送信されている。
- `PostToolUse` も Claude Code から実際に送信されている。
- `Notification(permission_prompt)` は送信される場合があるが、承認結果そのものを表すイベントではない。
- `PermissionRequest` の payload には `tool_use_id` が存在しないケースがある。
- `PostToolUse` の payload には `tool_use_id` が存在するケースがある。
- `funhou-correlation-debug.log` では、`PermissionRequest` を fallback key で保存し、対応する `PostToolUse` を fallback key で相関できたケースが確認されている。
- `funhou-correlation-debug.log` では、`Read` のような承認不要イベントに対して `PostToolUse` が到達し、pending が存在せず `match_failed` になるケースが確認されている。
- `funhou-debug.log` では、`PermissionRequest` に対して `message_count: 1`、`message_types: ["approval"]` が記録されており、承認待ちメッセージ自体は hook 内で生成されている。
- `PostToolUse` 処理中の `_load_pending_approvals()` で、0 バイトの `/tmp/funhou-approval-state.json` に対する `json.loads("")` が `JSONDecodeError` を発生させた。
- state file 破損対策として、現行コードには `.broken` 退避、空 state での継続、atomic write、`ERROR` ログ出力が実装されている。
- `funhou-input-debug.log` に記録された `PermissionRequest` の raw input は UTF-8 JSON として正常であり、日本語文字列も `\uXXXX` エスケープを含む妥当な形で到達している。
- `noise.astro` 関連の `PermissionRequest` では、コミットメッセージ中の日本語は受信時点では壊れていなかった。
- `sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")` は Windows の `cp932` 環境で `UnicodeEncodeError` を発生させたため、現行コードでは `ensure_ascii=True` に変更済みである。

## 未検証の仮説

- `PermissionDenied` がどの条件で発火し、どの程度 `PostToolUseFailure` と排他的に使われるかは十分に確認できていない。
- `PostToolUseFailure` 系の実運用ログが不足しており、失敗時の承認相関が `tool_use_id` と fallback key のどちらで安定するかはまだ確定していない。
- `Notification(permission_prompt)` の到達有無は Claude Code のバージョンや実行条件によって変動する可能性がある。
- `Approval granted` が出ないケースには、state file 破損以外に、結果イベント側の `target` 表現差分や補助キーの非一致が混在している可能性がある。

## 修正方針

- 承認待ちの正式な起点は `PermissionRequest` とし、`Notification(permission_prompt)` は補助イベントとして扱う。
- 承認相関は `tool_use_id` 優先、`session_id + tool_name + target` を補助キーとする方針を維持する。
- state file は atomic write と fail-soft を維持し、破損時は `.broken` に退避して空 state で継続する。
- 相関失敗時は `funhou.log` に `ERROR` を残し、通常の完了・失敗ログと区別して観測できるようにする。
- `PermissionDenied` / `PostToolUseFailure` の実ログを追加収集し、承認結果未取得の再現条件を event 種別ごとに切り分ける。
- 調査用ログは `funhou-debug.log` / `funhou-correlation-debug.log` / `funhou-input-debug.log` を継続利用し、問題の再現条件が確定した段階で削除対象を判断する。
