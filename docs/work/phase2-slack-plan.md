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
  どのチャネル失敗を hook 全体の失敗にするかの整理
- 完了条件
  Hook が生成した 1 件の `FunhouMessage` を terminal と slack に独立して配送できる。
  Slack が無効なら terminal のみ動作する。
  Slack 配送失敗時も terminal 出力が失われないことをユニットテストで確認できる。
- スコープ外
  Slack 表示文面の詳細改善
  サマリー生成そのもの
  配送リトライやキューイング
- 後続セッションで渡せる指示文ドラフト
  `既存の dispatch_message() と hook.py の配送処理を見直して、terminal と slack の複数チャネルへ配信できるようにしてください。channel ごとの levels を尊重し、Slack が失敗しても terminal 出力は継続する方針で、挙動をユニットテストで固定してください。`

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

### Ticket 5: テスト基盤と運用ドキュメントを整え、人間が外部確認しやすい状態にする

- ゴール
  サンドボックス内ではユニットテストで担保し、サンドボックス外では人間が Slack 実機確認しやすい形にする。
- 入力と出力
  入力:
  Ticket 1-4 の実装結果
  既存テスト群
  必要なら README または `docs/work` 配下の補助文書
  出力:
  設定例
  手動確認手順
  Slack 連携のユニットテスト追加
- 完了条件
  Slack 連携の正常系/設定未指定/HTTP失敗/レベルフィルタがユニットテストで確認できる。
  人間が `config/funhou.toml` をどう書き、何を見ればよいかが文書化されている。
  手動確認は webhook 実送信に限定され、実装チケット側は外部環境なしで完了判定できる。
- スコープ外
  本番運用の監視基盤
  Slack Bot トークンや双方向連携の説明
  summary エンジンの利用説明
- 後続セッションで渡せる指示文ドラフト
  `Phase2 Slack 連携のユニットテストと最小ドキュメントを整備してください。サンドボックス内では HTTP モック中心で完結させ、外部の Slack 実機確認は人間が行えるように、設定例と確認観点を README か docs に追加してください。`

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
