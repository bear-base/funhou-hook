# Ticket 2.5 既存ログの確認メモ

## 1. 現状の課題

- Ticket 2.5 着手前に、既存の debug ログ・調査用ログがどこにあり、何を記録しているかを整理する必要がある。
- 現状は場当たり的に追加されたログが混在しており、削除対象・Operational 昇格候補・State/Audit 扱いで当面触らないものの境界が明確ではない。
- Ticket 3 では Slack 配送失敗や hook runtime error の扱いを設計するため、既存ログのうち「残すべき事象」と「一時的な調査用トレース」を切り分けておく必要がある。

## 2. 検証済みの事実（ログ等）

### grep で確認できたログ実装の所在

- 既存の debug/調査用ログ実装は主に [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) に集中している。
- debug ログ出力先は以下の 3 つである。
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `DEBUG_LOG_PATH = Path("/tmp/funhou-debug.log")`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `CORRELATION_DEBUG_LOG_PATH = Path("/tmp/funhou-correlation-debug.log")`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `INPUT_DEBUG_LOG_PATH = Path("/tmp/funhou-input-debug.log")`
- 呼び出し箇所は `main()` 冒頭、message build 前後、approval 相関処理、approval state 読み書き処理、例外処理に広く分布している。
- `TEMP DEBUG` と明示された相関調査用ログが存在する。
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `# TEMP DEBUG: dedicated correlation log for approval matching investigation.`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `"""TEMP DEBUG: make approval correlation decisions obvious in one place."""`
- debug ログの実装本体は以下である。
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_raw_stdin`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_event_payload`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_stage`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_exception`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_correlation`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_append_debug_record`
- state 破損時には、既に通常の debug ログとは別に内部エラーを追記する経路がある。
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_recover_broken_state`
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_append_operational_log`
- hook 全体の例外時にも内部エラーを別経路へ出そうとする実装がある。
  - [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_emit_runtime_error`
- テストコードや他モジュールから、これらの debug ログ関数や `/tmp/funhou-debug.log` 系ファイルを直接利用している形跡は確認できなかった。
- ドキュメント上では、これらの debug ログが現行調査に使われていることが記載されている。
  - [docs/work/current-issue.md](./current-issue.md)
  - [docs/features/approval-state-reliability.md](../features/approval-state-reliability.md)
  - [docs/debug/claude-code-hooks-notes.md](../debug/claude-code-hooks-notes.md)

### 仕分け案

#### 消す

- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_raw_stdin`
  - stdin 生バイト全文、hex dump、UTF-8 復元文字列を丸ごと記録しており、典型的な調査用ログである。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_event_payload`
  - payload 全文ダンプであり、常設の運用ログとしては重すぎる。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_stage` のうち以下に属する実行経路トレース
  - `main.received`
  - `main.config_loaded`
  - `main.messages_built`
  - `main.dispatching_message`
  - `main.response_ready`
  - `build_messages.start`
  - `build_messages.done`
  - `pre_tool_use.classified`
  - `notification.classified`
  - `notification.ignored`
  - `permission_request.start`
  - `permission_request.message_ready`
  - `permission_denied.start`
  - `permission_denied.done`
  - `post_tool_use.start`
  - `post_tool_use.done`
  - `post_tool_failure.start`
  - `post_tool_failure.done`
  - 理由: 実装中の経路確認には有効だが、恒常的な運用価値は低く、場当たり的なトレースの性格が強い。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_correlation`
  - 承認相関調査専用であり、コード上でも `TEMP DEBUG` と明記されている。

#### 昇格

- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_debug_exception`
  - hook runtime error の `error_type`、`error_message`、`traceback` を記録している。
  - [docs/logging.md](../logging.md) の `hook runtime error` は Operational Log 対象として定義済みであり、debug ではなく Operational へ再配置するのが妥当。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_recover_broken_state`
  - approval state 破損を検知し、`.broken` 退避と空 state での継続を行っている。
  - [docs/logging.md](../logging.md) の `approval state 破損` は `State/Audit + Operational` 対象であり、残すべき重要事象に該当する。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_append_operational_log`
  - まだ正式な logging 基盤ではないが、内部障害を通知ログとは別経路へ出そうとしている点は Operational の意図に沿う。
  - 実装は置き換え候補だが、概念上は昇格側に分類する。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `_emit_runtime_error`
  - hook runtime error を記録対象として扱っている点は妥当であり、Operational の責務に寄せるべき処理である。
  - ただし現状は `dispatch_message(..., config.terminal)` に流す分岐があり、Notification と混線している。

#### 触らない

- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `state.load.*`
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `state.save.*`
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `state.put.*`
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) `state.pop.*`
  - approval state の読み書き・相関状態管理に付随する補助ログであり、Ticket 2.5 の整理方針では当面 `State/Audit` 寄りとして扱うのが安全である。
  - 直ちに削除するより、State/Audit の扱いを確定させるタイミングで再評価する方がよい。

## 3. 未検証の仮説

- `state.load.*` / `state.save.*` / `state.put.*` / `state.pop.*` の一部は、将来的には `State/Audit` ではなく Operational へ寄せた方が運用上有用な可能性がある。
- [docs/work/current-issue.md](./current-issue.md) で継続利用とされている debug ログのうち、一部は不具合の再現条件が確定した後にまとめて削除できる可能性が高い。
- `_emit_runtime_error` が terminal へ出している内容は、将来的に Notification の「要約」なのか、それとも完全に Operational 側へ閉じるべきなのか、まだ設計が固まっていない可能性がある。

## 4. 修正方針

- Ticket 2.5 では、まず既存ログを「消す / 昇格 / 触らない」の 3 区分で扱う。
- `TEMP DEBUG` と明記された調査用ログ、および payload 全文・stdin 全文・逐次 stage トレースは削除候補として扱う。
- hook runtime error と approval state 破損のような、運用中に障害調査価値がある事象は Operational または State/Audit に昇格させる前提で扱う。
- approval state 周辺の補助ログは、このメモ時点では削除対象にせず、State/Audit の正式設計時に再評価する。
- Ticket 3 着手前に、Notification と Operational の混線をなくし、terminal に内部障害事情を混ぜない方針を維持する。
