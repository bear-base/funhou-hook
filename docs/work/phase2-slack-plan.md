# Phase2 Slack連携 実装プラン

## 前提

- 設計ドキュメントは [docs/ai-agent-funhou-system.md](../ai-agent-funhou-system.md) を参照した。
- Phase1 の現行実装は [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) を起点に、`load_config()` で設定を読み、`_build_messages()` で `FunhouMessage` を生成し、`dispatch_message()` で terminal へ配送する構成になっている。

## 現状の Slack 連携に関係する事実

- メッセージ型は [src/funhou_hook/messages.py](../../src/funhou_hook/messages.py) に `LogMessage` / `SummaryMessage` / `ApprovalMessage` として定義済み。
- Hook の出口は [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) の `main()` で、各メッセージを `dispatch_message(message, config.terminal)` へ順次渡している。
- 出力チャネル設定は [src/funhou_hook/config.py](../../src/funhou_hook/config.py) の `FunhouConfig` が `terminal: ChannelConfig` を 1 つだけ持つ形で、[config/funhou.toml](../../config/funhou.toml) も `channels.terminal` のみ定義している。
- stdout アダプター相当の実装は [src/funhou_hook/dispatcher.py](../../src/funhou_hook/dispatcher.py) にあり、`LogMessage.level` のフィルタ後に `format_message()` の結果をファイル追記している。
- 既存テストは `Notification` 系やメッセージ契約の確認が中心で、配送先追加をカバーするテストはまだ存在しない。

## チケット一覧

### Ticket 1: 設定モデルを multi-channel 前提へ拡張し、Slack 設定を読めるようにする

- ゴール
  Phase1 の `terminal` 固定設定を壊さずに、Slack の有効/無効・Webhook URL・通知レベルなどを設定ファイルから読める状態にする。
- 入力と出力
  入力:
  [src/funhou_hook/config.py](../../src/funhou_hook/config.py) の `ChannelConfig` / `FunhouConfig` / `load_config()`
  [config/funhou.toml](../../config/funhou.toml)
  出力:
  terminal と slack を保持できる設定モデル
  Slack 用設定のデータクラスとローダー
  サンプル設定の追加
- 完了条件
  `load_config()` が Slack 設定なしでも従来どおり読める。
  `channels.slack` を与えたとき、Webhook URL・levels・メンション関連設定が構造化されて取得できる。
  設定ローダーのユニットテストで、既定値と異常系が確認できる。
- スコープ外
  実際の HTTP 送信
  Dispatcher の複数チャネル配信
  Slack メッセージ本文の最終デザイン
- 後続セッションで渡せる指示文ドラフト
  `src/funhou_hook/config.py` を中心に、terminal 固定の設定モデルを multi-channel 対応へ拡張してください。既存の terminal 挙動は維持しつつ、Slack 用に enabled/webhook/levels/mention_on/mention_to を TOML から読めるようにし、設定ローダーのユニットテストも追加してください。`

### Ticket 2: Slack 送信アダプターを追加し、Webhook へ単発投稿できるようにする

- ゴール
  `FunhouMessage` を受け取り、Slack Incoming Webhook に対して HTTP POST できる最小アダプターを追加する。
- 入力と出力
  入力:
  [src/funhou_hook/messages.py](../../src/funhou_hook/messages.py) の `FunhouMessage`
  Ticket 1 で追加する Slack 設定
  出力:
  Slack 送信用モジュール
  Webhook 向け JSON payload 生成
  HTTP エラー時の例外ポリシーまたは失敗結果
- 完了条件
  Slack 送信関数が `FunhouMessage` 1 件から Webhook 用リクエストを組み立てて送信できる。
  ネットワークを使わないユニットテストで、成功時のリクエスト内容と失敗時の扱いを検証できる。
  送信処理は `hook.py` から直接呼ばず、アダプターとして独立している。
- スコープ外
  複数チャネルへのファンアウト
  Hook ランタイムエラーを Slack へ自己通知する設計
  Slack Bot や返信処理
- 後続セッションで渡せる指示文ドラフト
  `Slack Incoming Webhook 用の送信アダプターを追加してください。入力は FunhouMessage と Slack 設定で、Webhook に JSON を POST する単機能に絞ってください。HTTP クライアントは標準ライブラリ優先でよく、ネットワークを使わないユニットテストで payload とエラー処理を確認できる形にしてください。`
- Slack 送信失敗は詳細な復旧制御を行わず、共通の SlackDeliveryError として扱う。HTTP ステータスや元例外など調査に必要な情報だけ保持し、再試行・キューイング・サービス停止判定は Phase2 のスコープ外とする。dispatcher 統合時は SlackDeliveryError をログに残し、terminal 出力は継続する。

### Ticket 3: Dispatcher を複数チャネル配信に拡張する

- ゴール
  `hook.py` のメッセージ配送を terminal 専用から、設定された複数チャネルへ配信できる形にする。
- 入力と出力
  入力:
  [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) の `main()`
  [src/funhou_hook/dispatcher.py](../../src/funhou_hook/dispatcher.py) の `dispatch_message()`
  Ticket 1, 2 の設定モデルと Slack アダプター
  出力:
  terminal / slack のファンアウト処理
  チャネルごとの level フィルタ
  チャネルごとの message type フィルタ
  どのチャネル失敗を hook 全体の失敗にするかの整理
- 完了条件
  Hook が生成した 1 件の `FunhouMessage` を terminal と slack に独立して配送できる。
  Slack が無効なら terminal のみ動作する。
  `SummaryMessage` は level を持たず、channel ごとの message type 設定で配送有無を切り替えられる。
  `LogMessage` / `ApprovalMessage` は message type と level の両方を尊重して配送できる。
  Slack 配送失敗時も terminal 出力が失われないことをユニットテストで確認できる。
  terminal 配送失敗は hook 全体の失敗として扱い、slack 配送失敗は hook 全体の失敗にしないことがコードとテストで明確になっている。
- スコープ外
  Slack 表示文面の詳細改善
  サマリー生成そのもの
  配送リトライやキューイング
- 後続セッションで渡せる指示文ドラフト
  `既存の dispatch_message() と hook.py の配送処理を見直して、terminal と slack の複数チャネルへ配信できるようにしてください。channel ごとの levels に加えて message_types も尊重し、summary は channel ごとの message type 設定で配送有無を切り替えられるようにしてください。Slack が失敗しても terminal 出力は継続する方針で、挙動をユニットテストで固定してください。`

#### Ticket 3 の追加設計メモ

- `summary` は全チャネル一律配信ではなく、チャネルごとに出し分ける。これを `levels` に無理に載せず、`message_types` のような購読設定をチャネル設定に追加して制御する想定にする。
- `SummaryMessage` には level の概念を持たせない。summary は危険度通知ではなく要約メッセージとして扱い、配送判定は `message_types` のみで行う。
- `LogMessage` / `ApprovalMessage` は `message_types` と `levels` の両方で配送判定する。
- `SummaryMessage` は `message_types` のみで配送判定する。
- たとえば terminal は `log, approval, summary`、Slack は `approval, summary` のように channel ごとの差を設定できる形を目標にする。
- `message_types` は個別フラグ(`summary_enabled` など)ではなく、各チャネル設定に素直に持たせる。対象は `TerminalChannelConfig` / `SlackChannelConfig` の両方とし、将来のチャネル追加でも同じ概念で横展開できる形を優先する。
- Slack 配送失敗ログは Notification に混ぜず、[docs/logging.md](../logging.md) に従って Operational Log に記録する。
- リトライ未実装の Ticket 3 時点では、Slack 配送失敗は実装上すべて `ERROR` として Operational Log に記録する。
- 将来リトライを導入する場合は、`docs/logging.md` の方針に合わせて `WARN`(リトライ中) / `ERROR`(最終失敗) に分ける前提とする。
- terminal は最小保証チャネルとして扱い、terminal 配送失敗は hook 全体の失敗にする。
- slack は付加チャネルとして扱い、slack 配送失敗は hook 全体の失敗にせず、Operational Log に記録して処理を継続する。

### Ticket 4: Slack 上の表示ポリシーを message type ごとに定義して実装する

- ゴール
  `log` / `approval` / `summary` を Slack 上でどう見せるかを、プロジェクト固有の表示ルールとして固定する。
- 入力と出力
  入力:
  [src/funhou_hook/messages.py](../../src/funhou_hook/messages.py) の 3 message type
  [src/funhou_hook/formatter.py](../../src/funhou_hook/formatter.py) の terminal 向け表現
  設計ドキュメント中の Slack 表示イメージ
  出力:
  Slack 向け formatter もしくは payload builder
  `mention_on` / `mention_to` を反映した表示ルール
  `approval` と `summary` の見せ分け
- 完了条件
  `LogMessage(level=info/warning/danger/error)` の各ケースで Slack 投稿内容が決まる。
  `ApprovalMessage` は承認待ちと分かる表示になり、通常ログと区別できる。
  `SummaryMessage` は生成元が未実装でも、受け取った場合の表示仕様がテストで固定される。
- スコープ外
  サマリー生成タイミング
  Slack のインタラクティブボタン
  ユーザー返信の受信処理
- 後続セッションで渡せる指示文ドラフト
  `Slack での見え方だけに集中して、log/approval/summary の message type ごとの表示ポリシーを実装してください。warning/danger でのメンション、approval の強調、summary の簡潔表示をテストで固定し、terminal formatter とは責務を分けてください。`

### Ticket 5: Phase2 Slack連携の総合テストを実施する

- ゴール
  Ticket 4' / Ticket 1 / Ticket 2 / Ticket 2.5 / Ticket 3 の実装結果を前提に、Phase2 Slack連携が一通りつながっていることを総合テストで確認し、Phase2 の完了判定ができる状態にする。
  正式な README / docs 統合は Phase2 後作業に回し、Ticket 5 では総合テストを再実施するために必要な最小限の Slack 実機確認メモだけを副産物として残す。

- 入力と出力
  入力:
  Ticket 4' / Ticket 1 / Ticket 2 / Ticket 2.5 / Ticket 3 の実装結果
  既存テスト群
  `config/.env.example`
  `config/funhou.toml`
  必要なら `docs/work` 配下の補助文書

  出力:
  Phase2 Slack連携の総合テスト結果
  不足していた場合の最小限の追加テスト
  Slack 実機確認のための最小手順メモ
  Phase2 後に README / docs へ統合するための TODO

- 完了条件
  既存テスト全体が通過し、Phase2 実装によって既存の terminal 動作が壊れていないことを確認できる。
  Slack 連携の正常系 / Slack disabled / Slack enabled 時の webhook 未設定 / HTTP 失敗 / level filter / message_types filter が、既存または追加テストで確認できる。
  hook から dispatcher、terminal、Slack sender までの経路が総合的に確認できる。
  Slack 配送失敗時も terminal 出力が継続し、Operational Log に失敗情報が残ることを確認できる。
  Slack 実送信を人間が確認するための最小手順メモが `docs/work` などに残っている。
  README / docs への正式統合は行わず、Phase2 後作業として切り出されている。

- スコープ外
  README への正式統合
  docs 全体の再構成
  新規メンバー向け導入ガイドの完成
  詳細なトラブルシュート集の作成
  本番運用の監視基盤
  Slack Bot トークンや双方向連携の説明
  summary エンジンの利用説明
  リトライ / キューイング / Slack 返信処理の実装

## 依存関係と推奨順序

1. Ticket 1
   設定モデルがないと Slack アダプターの入出力を固定できない。
2. Ticket 4
   Slack 表示ポリシーは実装判断が入りやすいため、HTTP 送信や dispatcher 統合より先に仕様を固めると後戻りが減る。
3. Ticket 2
   Ticket 4 の payload 方針を使って、Webhook 投稿の単機能アダプターを作る。
4. Ticket 3
   既存 hook の出口へ組み込み、terminal と Slack の両配信を成立させる。
5. Ticket 5
   最後にテスト網と外部確認手順を整理する。

## 各チケット後に人間が動作確認すること

- Ticket 1 後
  `config/funhou.toml` に Slack 設定を追加したとき、設定ロードが失敗しないことをユニットテスト結果で確認する。
- Ticket 2 後
  テスト用 webhook URL を使って単発投稿を実行し、Slack に 1 件届くことを確認する。
- Ticket 3 後
  実際に Hook を 1 回流し、terminal ログと Slack 投稿が両方出ることを確認する。
- Ticket 4 後
  `info` / `warning` / `danger` / `approval` 相当の投稿サンプルを Slack 上で見て、メンション有無と視認性を確認する。
- Ticket 5 後
  新規メンバーがドキュメントだけで設定し、最小の疎通確認まで進められるかを確認する。

## 補足メモ

- 既存の [src/funhou_hook/formatter.py](../../src/funhou_hook/formatter.py) は terminal 向け 1 行整形なので、Slack 連携では formatter の責務分離を前提にした方が安全。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) には approval state や debug log の処理が多く入っているが、今回の Slack 連携ではそこへ仕様を寄せ過ぎず、配送レイヤーの追加で閉じる方針がよい。
- `SummaryMessage` は型として既に存在するため、生成エンジン未実装でも Slack 側の受け皿だけ先に定義しておくと後続作業を分離しやすい。
- 配送失敗や調査用ログは Ticket 3 の局所対応として増やすだけでなく、将来的には「何かあった時に能動的に読みに行く運用ログ」をプロジェクト全体でどう持つかを別途設計した方がよい。Slack 失敗ログはその全体設計の一部として扱う。

## 人間による判断結果

- Ticket4を先に作るために、純粋関数としてまずは実装して仕様確定をすることを提案する。仕様案は下記
  1. 一番不確実な部分(見せ方の設計判断)を最小コストで先に固められる
  2. 二度手間が発生しない
  3. テストカバレッジが自然に厚くなる
  4. Ticket 1(設定)との依存が切れる
  5. サンドボックス内で完結する
- 実装順を右記の通りとする: 4' → 1 → 2 → 3 → 5

### Ticket 4' : Slack 表示ポリシーの純粋関数実装

Slack への表示を、送信や設定から切り離した純粋関数として実装してください。

#### 作るもの

`src/funhou_hook/slack_formatter.py`(仮)に、以下の関数を実装:

```python
def build_slack_payload(
    message: FunhouMessage,
    mention_to: str | None = None,
    mention_levels: set[Level] = frozenset(),
) -> dict:
    """FunhouMessage を Slack Incoming Webhook 用の JSON dict に変換する。"""
```

#### 入力と出力

- 入力: FunhouMessage(LogMessage / SummaryMessage / ApprovalMessage)
- 出力: Slack Incoming Webhook に POST する JSON dict

#### 表示ポリシー(設計ドキュメントの「Slack表示」セクションを参照)

- log: 1行テキスト、ツール種別に応じた絵文字
- summary: Block Kit、複数行、時刻範囲 + 本文 + 次のアクション
- approval: Block Kit、🔴 アイコン、理由、メンション付き(ボタンは Phase3 なのでプレーンテキストの指示でよい)
- mention_levels に含まれるレベルのメッセージには mention_to を付与

#### 完了条件

- 3種類のメッセージ × 各レベル(info/warning/danger)の代表ケースで、
  期待される payload 構造をユニットテストで固定する
- HTTP 送信は呼び出さない、設定ファイルも読まない(純粋関数)
- mention_to=None / mention_levels=空 のときはメンションが付かないことをテスト

#### スコープ外

- HTTP 送信
- 設定ファイル読み込み
- 配送の多重化
- Slack Bot トークンや返信処理

#### 補足

- この関数は Ticket 2(webhook 送信)から呼ばれる
- mention_to / mention_levels は呼び出し側が設定から取り出して渡す(この関数は引数で受け取るだけ)

#### 制約

- 動作確認はユニットテストで完結させる(Slack への実送信は不要)
- 既存の terminal formatter(src/funhou_hook/formatter.py)には手を入れない

## 実装完了

### Ticket 4' : Slack 表示ポリシーの純粋関数実装

- [src/funhou_hook/slack_formatter.py](../../src/funhou_hook/slack_formatter.py) を追加し、`build_slack_payload()` を純粋関数として実装した。
- `log` / `summary` / `approval` の3種類について、Slack Incoming Webhook 向け payload 生成を実装した。
- `mention_to` / `mention_levels` によるメンション付与、未知ツール時のアイコン fallback、未知 message 型への `TypeError` を実装した。
- [tests/test_slack_formatter.py](../../tests/test_slack_formatter.py) を追加し、代表ケースと境界ケースをユニットテストで固定した。
- 人間確認では `uv run pytest` が通過し、Slack formatter 追加による既存テストの破壊がないことを確認した。

### Ticket 1 : 設定モデルと Slack 設定ローダーの実装

- [src/funhou_hook/config.py](../../src/funhou_hook/config.py) に `TerminalChannelConfig` / `SlackChannelConfig` を追加し、`FunhouConfig` が `terminal` と `slack` の両方を持てる形に拡張した。
- `load_config()` で `channels.slack` を読めるようにし、`enabled` / `webhook` / `levels` / `mention_on` / `mention_to` を構造化して返すようにした。
- バリデーションとして、`channels.slack.enabled = true` のときは `webhook` 必須、`levels` / `mention_on` の不正な level は `ValueError` にしている。
- [tests/test_config.py](../../tests/test_config.py) を追加し、既存互換、Slack 正常系、Slack 無効時、`webhook` 未指定、`levels` / `mention_on` 異常系を固定した。
- Windows の `tmp_path` 権限エラーを避けるため、config テストは OS の temp ではなく `tests/.tmp/` 配下に一時ファイルを作る fixture を使っている。
- [config/funhou.toml](../../config/funhou.toml) に disabled な `channels.slack` サンプルを追加済みなので、Ticket 2 以降はこの設定モデルを前提に Webhook 送信実装へ進めてよい。

### Ticket 2 : Slack 送信アダプターの実装

- [src/funhou_hook/slack_sender.py](../../src/funhou_hook/slack_sender.py) を追加し、`send_slack_message()` で `FunhouMessage` と `SlackChannelConfig` から Slack Incoming Webhook へ単発 POST できるようにした。
- payload 生成は Ticket 4' の `build_slack_payload()` を利用し、`mention_to` / `mention_on` を設定から渡す形にした。
- Slack 送信失敗は `SlackDeliveryError` に統一し、HTTP status、短く切り詰めた response body、元例外を保持できるようにした。再試行・キューイング・dispatcher 継続判断はスコープ外として残している。
- [tests/test_slack_sender.py](../../tests/test_slack_sender.py) を追加し、実ネットワークなしで POST リクエスト内容、メンション反映、HTTP 失敗、ネットワーク失敗、webhook 未設定を固定した。
- 人間確認では `tests/test_config.py` / `tests/test_slack_formatter.py` / `tests/test_slack_sender.py` の関連テストが通過し、ruff の対象ファイルチェックも通過した。当時は既存の `/tmp/funhou-debug.log` 権限エラーで `test_hook_notifications.py` が失敗していたが、Ticket 2.5 で旧 debug ログ実装を撤去し解消済み。
- Slack webhook URL と mention 先は `config/funhou.toml` ではなく git 管理外の `config/.env` から読む形に変更し、`config/.env.example` と `config/.env` の ignore 設定を追加した。ユーザー確認では `uv run pytest` と Slack 実機への `Slack webhook manual test` 投稿が通過した。

### Ticket 2.5 : ログ戦略の整理とログ基盤の導入

- 詳細は [ticket-2.5.md](./ticket-2.5.md) を参照する。

### Ticket 3 : Dispatcher の複数チャネル配信対応

- [src/funhou_hook/config.py](../../src/funhou_hook/config.py) に `message_types` を追加し、terminal / slack の両チャネルで `log` / `summary` / `approval` の購読対象を設定できるようにした。
- [src/funhou_hook/dispatcher.py](../../src/funhou_hook/dispatcher.py) の `dispatch_message()` を複数チャネル前提に拡張し、terminal と slack へ 1 回の呼び出しでファンアウトできるようにした。
- `LogMessage` / `ApprovalMessage` は `message_types` と `levels` の両方で配送判定し、`SummaryMessage` は level を持たない前提で `message_types` のみで配送判定するようにした。
- terminal は最小保証チャネルとして扱い、terminal 配送失敗は例外として hook 全体を失敗させる一方、slack 配送失敗は [docs/logging.md](../logging.md) に従って Operational Log に記録し、hook 処理は継続するようにした。
- [src/funhou_hook/hook.py](../../src/funhou_hook/hook.py) から新しい dispatcher API を呼ぶように変更し、通常の message 配送と runtime error 時の notification 配送の両方を同じ複数チャネル経路に揃えた。
- [tests/test_dispatcher.py](../../tests/test_dispatcher.py) を追加し、`message_types` / `levels` による配送判定、`SummaryMessage` の扱い、terminal fatal / slack non-fatal の failure policy、Operational Log 記録を固定した。
- [tests/test_hook_dispatch_integration.py](../../tests/test_hook_dispatch_integration.py) を追加し、`main()` から terminal / slack への fan-out、slack 配送失敗時の継続、response JSON の返却を integration テストで固定した。

### Ticket 5 : Phase2 Slack連携の総合テスト準備

- [tests/test_phase2_slack_integration.py](../../tests/test_phase2_slack_integration.py) を追加し、Slack 実送信なしで Phase2 Slack 連携の縦断回帰テストを固定した。
- 自動テストでは、Slack disabled、Slack enabled + env webhook、webhook 未設定、level filter、message_types filter、Slack 配送失敗時の terminal 継続と Operational Log 記録を確認する。
- `ApprovalMessage` は dispatcher から Slack sender まで到達し、`mention_to` / `mention_on` が sender に渡ることを確認する。
- `SummaryMessage` は Ticket 5 時点では hook から生成しない。手動生成した `SummaryMessage` を dispatcher に渡した場合に terminal / Slack へ配送できることのみ確認し、サマリー生成エンジン、生成トリガー、LLM 呼び出しは後続 TODO とする。
- [docs/work/phase2-slack-regression-test.md](./phase2-slack-regression-test.md) を追加し、人間が Slack 実機で確認するための回帰テスト仕様を整理した。
- Slack 実機テストは webhook URL と Slack user ID などの認証系情報を必要とするため、人間が実施する。自動テストでは monkeypatch による fake sender のみを使う。
- README への正式反映は、Phase2 全体の実績をフィードバックして書き直す後続作業とし、Ticket 5 では扱わない。
