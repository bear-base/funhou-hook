# ログ戦略

本ドキュメントは AI エージェント分報システムにおけるログの分類・役割・出力先・運用ルールを定める、永続的な設計ドキュメントである。新しいログを追加するとき、既存ログの扱いに迷ったときに参照する。

## 全体方針

ログを4種別に分類し、それぞれの読み手・タイミング・出力先を明確に分離する。

- 「流れてくるもの(push)」と「調べに行くもの(pull)」を混ぜない
- 出力先はログ種別ごとに固定ルート化し、1つの出力先に複数種別を混在させない
- 障害ログはユーザー体験を壊さない場所に吐く(= terminal 分報に混ぜない)
- Debug ログは開発中の一時物として扱い、本番では抑制する

## 4種別の定義

### Notification Log(分報)

ユーザー向けの出来事通知。エージェントが今何をしているかを人間が把握するためのイベントストリーム。

| 項目 | 内容 |
|---|---|
| 読み手 | ユーザー(人間) |
| 読むタイミング | リアルタイム / 流し読み |
| 出力先 | terminal、Slack、将来は Web UI |
| 出してよいもの | hook イベントのユーザー可読な要約、approval 要求、完了通知 |
| 出してはいけないもの | 内部 ID、stack trace、リトライ詳細、配送失敗の内部事情 |
| 保持方針 | terminal は揮発でよい。Slack はチャネル履歴が保持装置 |

**ノイズ抑制:** 1イベント1行を基本、冗長な内部情報を入れない。失敗してもここには出さない(ユーザーにとっては「来なかった」だけで十分、原因は Operational Log を見る)。

### Operational Log(運用ログ)

システム挙動の真実の記録。障害発生時に「何が起きたか」を追うための能動的に読むログ。

| 項目 | 内容 |
|---|---|
| 読み手 | 運用者・開発者 |
| 読むタイミング | 障害時、挙動が怪しいと感じた時に能動的に |
| 出力先 | ローカルファイル(`logs/operational.log`) |
| 出してよいもの | Slack 配送の成否、hook 受信の成否、approval state の読み書き結果、起動/終了、設定ロード |
| 出してはいけないもの | 開発者がその場限りで欲しい変数ダンプ(→ Debug Log へ) |
| 保持方針 | 将来的に日次ローテート・一定期間保持。当面は追記のみ |

**ノイズ抑制:** レベル(INFO/WARN/ERROR)で峻別。正常系は INFO 止まり。同一エラーの連発への対処は将来課題。

### Debug Log(デバッグログ)

開発中の詳細トレース。特定の機能を触っている開発者が、その場で使うためのログ。

| 項目 | 内容 |
|---|---|
| 読み手 | その機能を触っている開発者だけ |
| 読むタイミング | 実装中・再現確認中 |
| 出力先 | ローカルファイル(`logs/debug/`)。**デフォルト OFF または環境変数で ON**(実装は後続) |
| 出してよいもの | 変数の中身、分岐のトレース、ペイロード dump |
| 保持方針 | 使い捨て前提。gitignore、長期保存しない |

**ノイズ抑制:** 本番では無効化。運用判断に必要な情報をここに置かない(置くべきなら Operational に昇格)。

### State / Audit Log(状態・監査)

approval state のようにシステム自身が読み戻す「状態」と、後から監査可能な決定の履歴。

| 項目 | 内容 |
|---|---|
| 読み手 | システム自身(state)、開発者・監査者(audit) |
| 読むタイミング | 状態復元時、事後監査時 |
| 出力先 | 専用ファイル(`logs/state/`) |
| 出してよいもの | approval の要求→承認/却下の遷移、決定者、タイムスタンプ |
| 出してはいけないもの | 通常の挙動トレース(→ Operational) |
| 保持方針 | 壊れたら困る層なので別管理。破損検知・バックアップは将来課題 |

**役割の切り分け:** State は「真実の状態」、Operational は「処理の記録」。二重記録を許容するかは実装時に判断。

**現状の補足:** Ticket 2.5 時点では State/Audit Log のハンドラは実装されない。`LogKind.StateAudit` は enum としてのみ用意され、具体の記録対象・出力先・フォーマットは State/Audit 正式設計チケット(Phase2 完了後)で決定する。既存の `state.*` 補助ログは Ticket 2.5 で一旦削除され、コード上には `TODO(state-audit-redesign)` マーカーが残る(詳細は Ticket 2.5 作業指示書参照)。

## 出力先マトリクス

| | terminal | Slack | ローカルファイル | 将来 Web UI |
|---|---|---|---|---|
| Notification | ○ | ○ | △(アーカイブ用途のみ) | ○ |
| Operational | ✕ | △(ERROR のみ別チャネル案、将来) | ○ | ○(フィルタ付き) |
| Debug | ✕ | ✕ | ○(開発時のみ) | ✕ |
| State / Audit | ✕ | ✕ | ○ | ○(閲覧) |

**重要な不変条件:**

- terminal に出るのは Notification **だけ**
- Operational は terminal に絶対に混ぜない
- Debug は Slack/terminal に出さない

## ログレベル方針(Operational)

| レベル | 使う場面 |
|---|---|
| INFO | 正常系の主要イベント(起動、設定ロード、配送成功など) |
| WARN | リトライ可能な失敗、一時的な異常(Slack 配送失敗でリトライ余地がある、など) |
| ERROR | 最終的な失敗、ユーザー介入が必要な異常(配送最終失敗、state 破損、hook runtime error など) |

判断に迷ったら **WARN/ERROR の判定基準は「ユーザーまたは運用者の対応が必要か」**。対応不要なら INFO または記録しない。

## 障害時の出力ルール

| 障害 | 出力先 | レベル | 補足 |
|---|---|---|---|
| Slack 配送失敗(リトライ中) | Operational | WARN | terminal 分報には出さない |
| Slack 配送失敗(最終) | Operational | ERROR | terminal 分報には出さない |
| hook runtime error | Operational | ERROR | stack trace 付き、Notification には要約のみ |
| approval state 破損 | State/Audit(破損検知) + Operational | ERROR | 復旧は手動介入が必要な領域 |

### approval state 破損の Ticket 2.5 時点での暫定対応

`approval state 破損` は本来 **State/Audit + Operational** の両方に記録されるべきだが、Ticket 2.5 時点では State/Audit ハンドラ本体は未実装である。そのため以下の暫定対応で運用する:

- **Operational 側**: Ticket 2.5 で実装(旧 `_recover_broken_state` の昇格先。ERROR レベルで記録)
- **State/Audit 側**: ハンドラ未実装のため、**`.broken` 退避と TODO マーカーでつなぐ**
  - `.broken` 退避: 既存の挙動を踏襲し、破損した state ファイルをリネーム保全する
  - TODO マーカー: 退避処理箇所に `TODO(state-audit-redesign): State/Audit Log として記録` を残す

State/Audit の本格記録は正式設計チケット(Phase2 完了後)で実装する。Ticket 2.5 では**この暫定対応で一貫性を確保**し、無理に State/Audit 側を完成させようとしない。

### Notification への要約出力の規約

hook runtime error のようにユーザーに何らかの異常が起きたことを伝える必要がある場合、Notification には**要約のみ**を出す。

**出してよいもの:**

- 異常が起きた事実
- ユーザーが次に取るべき行動の示唆(ログを確認するなど)

**出してはいけないもの:**

- stack trace
- error_type, error_message などの内部情報
- 設定キー、内部 ID、ファイルパスなど
- リトライ詳細

詳細はすべて Operational Log 側に記録し、Notification はユーザー体験を損なわない最小限の告知に留める。

#### hook runtime error のデフォルトテンプレート

実装者による文言ブレを防ぐため、デフォルト文言を固定する:

> エラーが発生しました。詳細はログを確認してください。

このシステムは開発者向けなので、Notification で詳細説明を行う必要はない。何のエラーかはログを見れば分かる前提でよい。文脈に応じた微調整は可能だが、**長くしない**(2文以内、内部情報を含めない)ことを守る。

## 調査用ログの扱い

「推測で直さず事実を見るために一時的に入れるログ」は、Debug Log とは別物として扱う。

### 運用方針

調査用ログは積極的に使ってよい。推測で直すより事実を見る方が常に優位である。ただし、**調査用ログの投入と削除は一セットの作業**として扱う。

### 投入時

- 調査目的で一時的に入れるログは、Debug Log でも Operational Log でもない第3の扱いとする
- メディアは自由(`print`、一時ファイル、`sys.stderr` への直接出力など)
- **ただし `get_logger(LogKind.Debug)` は使わない**。Debug Log は恒常的な位置づけであり、「一時的に入れてすぐ消す」調査用ログとは性質が異なる。混ぜると削除判断が揺れる
- TODO マーカーは付けない(恒久的に残る場所ではないため)

### 削除時

- 調査が完了したら、**その PR の中で削除まで完了させる**
- 「あとで消す」は認めない。調査用ログの寿命は当該 PR 内に限る
- 残すべきと判断した場合は、**Operational Log に昇格させる**(Debug に昇格させない)

### 昇格判断の目安

- 運用中に障害調査で使う価値があるか?
  - Yes → Operational に昇格(カタログにエントリ追加)
  - No → 削除
- 迷ったら削除(Operational の判断基準は厳しめに保つ)

このルールがないと、調査用ログが消し忘れで蓄積し、Debug Log と混ざって運用視点が見えなくなる。

## ログ基盤 API

### 種別の指定

```python
from <package>.logging import LogKind, get_logger

logger = get_logger(LogKind.Operational)
```

`LogKind` は以下の4種別の enum:

- `LogKind.Notification`
- `LogKind.Operational`
- `LogKind.Debug`
- `LogKind.StateAudit`

### コンテキスト情報の渡し方

コンテキストは `extra=dict(...)` で渡す。これは将来の構造化ログ化(JSON Lines 化)で `extra` の中身がそのまま JSON フィールドになることを想定した規約。

```python
logger.warning("Slack delivery failed", extra={
    "channel": "#general",
    "retry_count": 2,
    "reason": "rate_limit",
})
```

**注意:** `extra` に標準 `logging` の予約語(`message`, `asctime`, `levelname` 等)を入れない。

### 初期化

アプリ起動時に一括初期化する。遅延初期化は当面採用しない。

### propagate の扱い

種別ごとのロガーは `propagate = False` を設定する。ルートロガーへの伝播による重複出力を防ぐため。

## ログ書き込み失敗の扱い

標準 `logging` モジュールのデフォルト挙動(stderr へのフォールバック)に任せる。明示的なフォールバック設計は要件が出てから検討する。

## Operational Log 記録対象カタログ

Operational Log に何を記録するかの一覧。Phase2 範囲の最低限から始め、必要に応じて追記していく。本格的な棚卸しは Phase2 完了後に行う。

### 記載形式

各エントリは以下の要素を持つ:

- **イベント**:何が起きたか
- **レベル**:INFO / WARN / ERROR
- **記録する context**:`extra` に入れるキー
- **備考**:判断基準や補足

### Phase2 範囲の最低限

注: `approval state` 関連のエントリのうち「破損検知」を除く読み書きログは、State/Audit Log 正式設計(Phase2 完了後の後続チケット)まで**実装を保留**する。Ticket 2.5 時点では該当箇所を削除し `TODO(state-audit-redesign)` マーカーを残すに留める。カタログには将来の実装対象として記載しておく。

| イベント | レベル | context | 備考 |
|---|---|---|---|
| アプリ起動 | INFO | version, config_path | 起動確認用 |
| アプリ終了 | INFO | reason | 正常終了・異常終了の区別 |
| 設定ロード成功 | INFO | config_path | |
| 設定ロード失敗 | ERROR | config_path, reason | 起動不能の原因追跡 |
| hook 受信成功 | INFO | event_type, source | |
| hook 受信失敗(パース失敗等) | WARN | source, reason | |
| Slack 配送成功 | INFO | channel, event_type | |
| Slack 配送失敗(リトライ中) | WARN | channel, retry_count, reason | |
| Slack 配送失敗(最終) | ERROR | channel, event_type, reason | ユーザーに届いていない |
| approval state 読み込み成功 | INFO | state_id | **State/Audit 正式設計まで保留**。頻度次第で DEBUG 相当に落とすか再検討 |
| approval state 読み込み失敗 | ERROR | state_id, reason | **State/Audit 正式設計まで保留** |
| approval state 書き込み失敗 | ERROR | state_id, reason | **State/Audit 正式設計まで保留** |
| approval state 破損検知 | ERROR | state_id, detail | 手動介入が必要。**Ticket 2.5 で実装**(旧 `_recover_broken_state` の昇格先) |
| hook runtime error | ERROR | event_type, stack_trace | |

### 更新ルール

- Phase2 範囲で追加が必要になったら随時このカタログに追記する
- Phase2 完了後、本格的な棚卸しを別チケットで実施しカタログを再編する
- 昇格候補(既存 debug ログから Operational に昇格させるもの)は個別チケットで扱い、実装時に本カタログに追記する

## 本ドキュメントで定めないこと(後続課題)

以下は意図的に本ドキュメントのスコープ外。必要になった時点で追記・別ドキュメント化する。

- 構造化ログ化(JSON Lines)のスキーマ
- ログローテーション・保持期間の具体値
- Debug ログの本番無効化メカニズム
- ERROR レベル Operational の Slack 別チャネル通知
- **State/Audit Log の正式設計**(現 `state.*` ログの再配置、破損検知、バックアップを含む。**Phase2 完了後に着手**。`docs/features/approval-state-reliability.md` の提案はこのチケットに合流させる)
- Notification アーカイブの要否
- Web UI 向けログ API・閲覧 UI
- マルチプロセス/マルチスレッド時の書き込み競合対策
