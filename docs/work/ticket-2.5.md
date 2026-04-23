# Ticket 2.5: ログ戦略の整理とログ基盤の導入

## 目的

現状のプロジェクトには運用視点のログが存在せず、debug ログ・調査用ログが整理されないまま蓄積している。Ticket 3(Dispatcher の複数チャネル配信)で Slack 配送失敗ログを扱う前に、ログ分類のルールと Operational Log の基盤を整備する。

## 前提ドキュメント

本チケットの作業は `docs/logging.md` に定めたログ戦略に基づく。実装・判断に迷った場合はそちらを参照すること。

既存ログの調査・仕分け結果は別途メモとしてまとめ済み(`docs/work/` 配下の既存ログ確認メモ参照)。本チケットの作業はそのメモを前提とする。

## スコープ

### やること

**1. ドキュメント整備**

- `docs/logging.md` を本リポジトリに配置する(本チケットに添付)
- 内容は既に確定しているため、そのまま転写すること。独自解釈で改変しない

**2. 既存ログの削除と書き直し(基本方針: 全入れ替え)**

既存の debug 実装は「その場しのぎ」の位置づけであり、部分的に残すと新旧混在で読みづらくなる。そのため **既存 debug ログ実装は全削除し、必要なものは新基盤で書き直す** 方針を取る。

対象関数(すべて `src/funhou_hook/hook.py`):

- `_debug_raw_stdin`
- `_debug_event_payload`
- `_debug_stage`
- `_debug_exception`
- `_debug_correlation`
- `_append_debug_record`
- `_append_operational_log`
- `_emit_runtime_error`

対象定数:

- `DEBUG_LOG_PATH`(`/tmp/funhou-debug.log`)
- `CORRELATION_DEBUG_LOG_PATH`(`/tmp/funhou-correlation-debug.log`)
- `INPUT_DEBUG_LOG_PATH`(`/tmp/funhou-input-debug.log`)

削除後、以下を新基盤(`get_logger(LogKind.Operational)` 経由)で書き直す:

- **hook 受信成功**(旧 `_debug_stage('main.received')` に対応)
- **設定ロード成功**(旧 `_debug_stage('main.config_loaded')` に対応)
- **hook runtime error**(旧 `_debug_exception` および `_emit_runtime_error` の本体)
- **approval state 破損検知**(旧 `_recover_broken_state` の内部ログ)
- `docs/logging.md` の「Operational Log 記録対象カタログ」にあるその他のエントリ

書き直さないもの(= 削除のみ):

- 場当たり的な分岐トレース系 `_debug_stage`(`build_messages.*`, `pre_tool_use.*`, `notification.*`, `permission_request.*`, `permission_denied.*`, `post_tool_use.*`, `post_tool_failure.*` など)
- payload / stdin の全文ダンプ系(`_debug_raw_stdin`, `_debug_event_payload`)
- 相関調査用(`_debug_correlation`、`TEMP DEBUG` 明記)

触らないもの:

- `state.load.*` / `state.save.*` / `state.put.*` / `state.pop.*`(approval state 周辺の補助ログ、State/Audit 正式設計時に再評価)

**3. `_emit_runtime_error` の Notification 分岐の改修**

現状の `_emit_runtime_error` は `dispatch_message(..., config.terminal)` に流す分岐を持ち、Notification と Operational が混線している。これを以下のように分離する:

- Operational 側(ERROR): stack trace、error_type、error_message、event_type などの詳細
- Notification 側: 要約のみ(`docs/logging.md` の「Notification への要約出力の規約」に従う)
  - 「エージェント処理でエラーが発生した」程度の事実
  - ユーザーが次に取るべき行動の示唆(例: 「詳細はログを確認してください」)
  - 内部情報(stack trace、error_type、設定キー等)は出さない

**4. ログ基盤実装**

- 種別 enum(`LogKind`)を定義: Notification / Operational / Debug / StateAudit の4つ
- `get_logger(kind: LogKind) -> Logger` API を実装
- Operational 用のハンドラとフォーマッタを実装
  - 出力先: `logs/operational.log`
  - フォーマット: timestamp + level + message(+ extra フィールド)
  - 標準 `logging` モジュールベースで実装する(独自実装はしない)
- Notification / Debug / StateAudit は enum で種別だけ用意し、ハンドラ本実装は後続タスクとする
  - `get_logger` 自体は呼べる状態にしておく(ダミーハンドラまたは no-op で可)
- 各ロガーは `propagate = False` を設定
- アプリ起動時に一括初期化する仕組みを用意

**5. Operational Log 記録対象カタログの調整**

- 初期版のエントリは `docs/logging.md` に既に記載済み
- 実装時に実装との噛み合わせを確認し、必要ならカタログを微調整
- 本格的な棚卸しは Phase2 完了後の別チケットで行う

**6. 関連ドキュメントの整理**

既存 debug ログを全削除することで記述が古くなるドキュメントを整理する。

- **`docs/debug/claude-code-hooks-notes.md`**
  - debug ログ参照手順(PermissionRequest / PostToolUse の確認、stderr / traceback の確認)は古くなる
  - 試行錯誤のメモなので、中身は **不要として扱う**
  - ファイル自体を削除するか、「Ticket 2.5 以前の調査メモ。現在は該当する debug ログ実装なし」と冒頭に注記を残す(判断は実装者に委ねる)

- **`docs/features/approval-state-reliability.md`**
  - 「今回の debug ログと traceback から...」という事実認定部分は、**結論は残す**(後続の State/Audit 設計の入力になる)
  - 「診断モードを正式機能にする」提案は `docs/logging.md` の「Debug ログの本番無効化メカニズム」後続課題に吸収されるため、features 側は**削除または簡素化**してよい
  - features ドキュメント全体は **State/Audit 正式設計チケット(後続)に合流**する位置づけとする。本チケットで完全に処理しきる必要はなく、State/Audit 設計時に再参照される入力として残す

- **`docs/work/phase2-slack-plan.md`**
  - `/tmp/funhou-debug.log` の権限エラーに関する現状説明は古くなる(Ticket 2.5 で該当ファイル自体が消滅)
  - 該当箇所を更新し、「Ticket 2.5 で解消済み」と反映する

**7. テスト**

- `get_logger(LogKind.Operational)` が正常に動作することを確認
- pytest の `caplog` で捕捉できることを確認(必要に応じて `caplog.set_level(level, logger="operational")` のような種別指定を使う)
- 既存テストが壊れていないことを確認
- 削除した debug ログ関数を直接参照しているテストがないことを事前確認(grep 済み、利用なし)

### やらないこと

以下は本チケットのスコープ外。手を出さないこと。

- Operational 記録対象の本格的な棚卸し(Phase2 後に別チケット)
- Notification / Debug / StateAudit のハンドラ本実装(enum と `get_logger` の口だけ用意、中身は後続)
- 構造化ログ化(JSON Lines)
- ログローテーション
- Debug 本番無効化機構
- ERROR の Slack 別チャネル通知
- State/Audit Log の正式設計(`state.*` ログの再配置を含む、Phase2 完了後の別チケット)
- State 破損検知・バックアップ
- ログ書き込み失敗のフォールバック(標準 logging の stderr 挙動に任せる)
- Web UI ログ閲覧
- Ticket 3(Dispatcher 複数チャネル配信)への着手

## 作業手順(推奨)

1. `docs/logging.md` をリポジトリに追加
2. ログ基盤(enum、`get_logger`、Operational ハンドラ)を実装
3. 新基盤で書き直す対象(hook 受信、設定ロード、hook runtime error、approval state 破損)を実装
4. `_emit_runtime_error` の Notification 分岐を要約出力に改修
5. 既存 debug ログ実装を全削除(対象関数・定数すべて)
6. 関連ドキュメント(`docs/debug/claude-code-hooks-notes.md`, `docs/features/approval-state-reliability.md`, `docs/work/phase2-slack-plan.md`)を整理
7. `docs/logging.md` の Operational 記録対象カタログを実装と突き合わせて微調整
8. テストを通す
9. Ticket 3 着手前に本チケットをクローズ

## 成果物

- `docs/logging.md`(永続的な設計ドキュメント、Operational 記録対象カタログを含む)
- ログ基盤の実装(`LogKind`、`get_logger`、Operational ハンドラ)
- 既存 debug ログ実装の全削除
- 新基盤による Operational Log 出力(カタログ記載のイベント)
- `_emit_runtime_error` の Notification 要約出力への改修
- 関連ドキュメントの整理

## Ticket 3 への引き継ぎ事項

- Dispatcher の配送失敗は `get_logger(LogKind.Operational)` 経由で吐くこと
- terminal には Notification しか流さないこと(Operational を混ぜない)
- hook runtime error のような異常事象を Notification に出す場合は、`docs/logging.md` の「Notification への要約出力の規約」に従うこと
- 将来の Web UI チャネルを「口としては意識する」が、本チケットでは実装しない

## 工数見積もり

| 項目 | 工数 |
|---|---|
| ドキュメント配置 | 0.5人日 |
| ログ基盤実装 | 1〜1.5人日 |
| 新基盤による再実装(4イベント + runtime error 改修) | 0.5〜1人日 |
| 既存 debug ログ全削除 | 0.5人日 |
| 関連ドキュメント整理 | 0.5人日 |
| Operational カタログ調整 | 0.5人日 |
| テスト | 0.5人日 |
| 合計 | 3.5〜4.5人日 |

## 後続チケットの候補

本チケットの作業から派生する後続タスク。本チケットでは起票まで、実作業はしない。

- Operational 記録対象の本格棚卸し(Phase2 完了後)
- ロガー共通モジュール導入 / 既存コードの置き換え
- 構造化ログ化(JSON Lines)
- ログローテーション
- Debug ログの本番無効化機構(Debug Log ハンドラ本実装とセット)
- ERROR の Slack 別チャネル通知
- **State/Audit Log の正式設計**(Phase2 完了後、`state.*` ログの再配置、破損検知、バックアップを含む。`docs/features/approval-state-reliability.md` の提案を入力として合流)
- Notification アーカイブの要否判断
- Web UI ログ API・閲覧 UI
