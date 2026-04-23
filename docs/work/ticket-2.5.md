# Ticket 2.5: ログ戦略の整理とログ基盤の導入

## 目的

現状のプロジェクトには運用視点のログが存在せず、debug ログ・調査用ログが整理されないまま蓄積している。Ticket 3(Dispatcher の複数チャネル配信)で Slack 配送失敗ログを扱う前に、ログ分類のルールと Operational Log の基盤を整備する。

## 前提ドキュメント

本チケットの作業は `docs/logging.md` に定めたログ戦略に基づく。実装・判断に迷った場合はそちらを参照すること。

## スコープ

### やること

**1. ドキュメント整備**

- `docs/logging.md` を本リポジトリに配置する(本チケットに添付)
- 内容は既に確定しているため、そのまま転写すること。独自解釈で改変しない

**2. 既存ログの調査・仕分け・削除**

- リポジトリ内の既存 debug ログ・調査用ログを grep で一覧化する
- 各ログを以下に仕分ける:
  - **消す**(大半はこれになる想定)
  - **Operational に昇格すべき**(運用中も価値があるもの)→ 後続タスク用にリストアップ
  - **触らない**(approval state 周辺の補助ログ = State/Audit 扱い)
- 「消す」判断したものは本チケット内で削除する
- 「昇格」判断したものは本チケット内では実装しない。リストを成果物として残す

**判断基準:**

- 「推測で直さないため」に一時的に入れた調査用ログは消す
- 運用中に障害調査で使える情報かどうかで判定する
- 迷ったら消す(残すなら明確な根拠が必要)

**3. ログ基盤実装**

- 種別 enum(`LogKind`)を定義:Notification / Operational / Debug / StateAudit の4つ
- `get_logger(kind: LogKind) -> Logger` API を実装
- Operational 用のハンドラとフォーマッタを実装
  - 出力先: `logs/operational.log`
  - フォーマット: timestamp + level + message(+ extra フィールド)
  - 標準 `logging` モジュールベースで実装する(独自実装はしない)
- Notification / Debug / StateAudit は enum で種別だけ用意し、ハンドラ実装は後続タスクとする
  - `get_logger` 自体は呼べる状態にしておく(ダミーハンドラまたは no-op で可)
- 各ロガーは `propagate = False` を設定
- アプリ起動時に一括初期化する仕組みを用意

**4. Operational Log 記録対象の最低限定義**

- Phase2 範囲で必要最低限の記録対象を `docs/logging.md` の「Operational Log 記録対象カタログ」節に定義する
- 初期版のエントリは `docs/logging.md` に既に記載済み。本チケットでは実装に合わせて必要な調整を行う(カラム追加、イベント追加など)
- 既存ログ仕分けで「昇格」判定したものはカタログに追記するのではなく、昇格候補リストとして別管理する(本チケットのスコープ外、後続チケット化)
- 本格的な棚卸しは Phase2 完了後の別チケットで行う

**5. テスト**

- `get_logger(LogKind.Operational)` が正常に動作することを確認
- pytest の `caplog` で捕捉できることを確認(必要に応じて `caplog.set_level(level, logger="operational")` のような種別指定を使う)
- 既存テストが壊れていないことを確認

### やらないこと

以下は本チケットのスコープ外。手を出さないこと。

- Operational 記録対象の本格的な棚卸し(Phase2 後に別チケット)
- Notification / Debug / StateAudit のハンドラ実装
- 構造化ログ化(JSON Lines)
- ログローテーション
- Debug 本番無効化機構
- ERROR の Slack 別チャネル通知
- State 破損検知・バックアップ
- ログ書き込み失敗のフォールバック(標準 logging の stderr 挙動に任せる)
- Web UI ログ閲覧

## 作業手順(推奨)

1. `docs/logging.md` をリポジトリに追加
2. 既存 debug ログ・調査用ログを grep で一覧化し、仕分け結果をチケット内にメモ
3. ログ基盤(enum、`get_logger`、Operational ハンドラ)を実装
4. `docs/logging.md` の「Operational Log 記録対象カタログ」節を必要に応じて調整(実装中に気づいた追加項目を反映)
5. 仕分けで「消す」判定したログを削除(機能単位で小さく分けてコミット推奨)
6. 「昇格」判定したログは既存コードを残したまま、昇格候補リストとしてチケットに記載
7. テストを通す
8. Ticket 3 着手前に本チケットをクローズ

## 成果物

- `docs/logging.md`(永続的な設計ドキュメント、Operational 記録対象カタログを含む)
- ログ基盤の実装(`LogKind`、`get_logger`、Operational ハンドラ)
- 既存 debug ログ・調査用ログの削除
- Operational 昇格候補リスト(後続チケットの入力として使用、本ドキュメント内に記載)

## Ticket 3 への引き継ぎ事項

- Dispatcher の配送失敗は `get_logger(LogKind.Operational)` 経由で吐くこと
- terminal には Notification しか流さないこと(Operational を混ぜない)
- 将来の Web UI チャネルを「口としては意識する」が、本チケットでは実装しない

## 工数見積もり

| 項目 | 工数 |
|---|---|
| ドキュメント配置 | 0.5人日 |
| 既存ログ調査・仕分け・削除 | 0.5〜1人日 |
| ログ基盤実装 | 1〜1.5人日 |
| Operational 記録対象の最低限定義 | 0.5人日 |
| テスト・初期化設計 | 0.5人日 |
| 合計 | 3〜4人日 |

## 後続チケットの候補

本チケットの作業から派生する後続タスク。本チケットでは起票まで、実作業はしない。

- Operational 昇格候補の実装(本チケットでリストアップしたもの)
- Operational 記録対象の本格棚卸し(Phase2 完了後)
- ロガー共通モジュール導入 / 既存コードの置き換え
- 構造化ログ化(JSON Lines)
- ログローテーション
- Debug ログの本番無効化機構
- ERROR の Slack 別チャネル通知
- State 破損検知・バックアップ
- Notification アーカイブの要否判断
- Web UI ログ API・閲覧 UI
