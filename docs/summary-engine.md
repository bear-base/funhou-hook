# summary-engine

このドキュメントは、`summary` を生成する summary engine の基本設計を定める。

`summary` は `log` / `approval` と並ぶ統一メッセージ型であり、生ログを置き換える
ものではなく、人間が作業経緯を後追いしやすくするための補助情報である。

## 他ドキュメントとの分担

- [design.md](./design.md): `summary` を含む統一メッセージ型と hook event の写像
- [summary-provider.md](./summary-provider.md): provider 境界と生成結果分類の設計思想
- [logging.md](./logging.md): summary 生成失敗時の Operational Log 方針

## 目的

summary engine の目的は、作業区切りごとに「ここまで何が起きたか」と「次に見るべき
こと」を短くまとめ、ユーザーが作業状況を後追いしやすい状態を作ることである。

承認待ちの前に summary を出す場合も、それは承認要求そのものではなく、承認判断の
材料として扱う。

## 責務範囲

summary engine が担うこと:

- summary 生成タイミングの制御
- summary 入力の収集
- provider への生成依頼
- provider の結果を `SummaryMessage` に変換すること
- 生成不要・生成失敗時の扱いを決めること

summary engine が担わないこと:

- terminal / Slack など配送先の選択
- Slack 表示の調整
- LLM API 固有の詳細
- 承認可否の判断や実行制御
- 監査ログ、履歴検索、長期保存

## 生成タイミング

標準の生成タイミングは作業区切りであり、現状では `Stop` をデフォルトトリガーとする。

`PermissionRequest` は承認判断材料として有用だが、頻度が高くなりやすいため、
デフォルトでは summary を生成しない。承認待ちのたびに summary が必要な場合は、
設定で `summary.triggers` に `PermissionRequest` を追加する。

件数ベース・時間ベースのトリガーは現状の基本設計には含めない。必要になった時点で、
通知頻度と認知負荷を踏まえて再検討する。

## 入力の考え方

summary は、直近の未処理ログを材料に生成する。

現行実装では terminal log を入力元とし、前回処理位置以降の差分を provider に渡す。
ただし、summary 自身を次回 summary の入力に混ぜないため、`[SUMMARY]` 行は入力から除外する。

入力が大きくなりすぎる場合は、設定された上限に基づいて provider に渡す範囲を制限する。

将来的に入力元を terminal log から構造化イベントへ変更する可能性はあるが、その場合でも
summary engine は「直近の未処理分を扱う」という原則を維持する。

## Provider 境界

summary engine は LLM API を直接知らない。

LLM 呼び出し、prompt、model、structured output、retry などの詳細は provider 側の
責務とする。summary engine は provider に summary 生成を依頼し、結果分類だけを見る。

provider は「LLM クライアント」ではなく、「summary を生成する用途」の境界である。
これにより、Gemini 以外の provider や LLM を使わない実装へ差し替える場合も、
summary engine の責務を増やさずに済む。

## 結果分類

summary 生成結果は次の 3 種類に分ける。

| 状態 | 意味 | 扱い |
|---|---|---|
| `generated` | summary を生成できた | `SummaryMessage` を作る |
| `skipped` | 要約不要と判断した | 正常系として summary を出さない |
| `failed` | 生成に失敗した | 異常系として summary を出さない |

`skipped` と `failed` は、どちらもユーザー向けには「summary を出さない」結果になる。
ただし設計上の意味は異なるため、state 更新やログ記録では区別する。

## State と再処理

summary engine は、どの入力範囲を処理済みにしたかを state として持つ。

基本方針:

- 正常に処理できた範囲は処理済みにする
- 要約不要も正常処理として扱う
- 生成に失敗した範囲は処理済みにしない
- trigger policy で対象外のイベントは summary 処理に入らない

つまり、`generated` と `skipped` は処理済みとして扱い、`failed` は次回再試行の余地を
残す。

## 失敗時の扱い

summary はベストエフォート機能である。生成に失敗しても、hook 全体や `approval`
通知を失敗させない。

失敗詳細はユーザー向け Notification には出さず、Operational Log に記録する。
ユーザーにとって summary は「あれば便利」な補助情報であり、失敗の詳細をリアルタイム
通知に混ぜると分報の読みやすさを損なうためである。

retryable かどうか、どの error kind として扱うかは provider 側が判断する。

## 配送との関係

summary engine は `SummaryMessage` を生成するだけで、配送先は選ばない。

terminal / Slack に出すかどうかは dispatcher と channel ごとの `message_types` 設定で
決まる。

`SummaryMessage` は危険度通知ではないため `level` を持たない。配送判定は message type
で行う。

## 設定で制御するもの

summary の挙動は主に `[summary]` 設定で制御する。

- summary の有効/無効
- provider / model
- 生成トリガー
- 入力サイズ上限
- timeout
- 最大出力 tokens
- thinking budget
- state path

LLM provider に必要な secret は `.env` で管理する。Gemini provider を使う場合は
`GEMINI_API_KEY` が必要になる。
