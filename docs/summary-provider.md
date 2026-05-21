# summary-provider

このドキュメントは、summary 生成を担う provider 境界の設計思想をまとめる。

ここでは特定の LLM API 仕様やモデル選定の手順を正本として固定しない。LLM provider
を大きく変更する場合は、その時点の公式情報を改めて調査する。

## 目的

summary provider の目的は、summary engine から生成方法の詳細を分離することである。

summary engine は「summary がほしい」とだけ依頼し、provider が LLM 利用、prompt、
model、structured output、retry などの詳細を引き受ける。

## 基本方針

provider は「LLM クライアント」ではなく、「summary を生成する用途」の境界とする。

- summary engine は LLM API の詳細を知らない
- prompt や model の選択は provider 側に閉じ込める
- Gemini は現行の具象 provider のひとつとして扱う
- 別 provider が必要になった場合も、summary engine に provider 固有処理を持ち込まない

この境界により、上位層は provider の生成結果だけを見ればよく、LLM API の変更や
モデル変更の影響範囲を provider 内に閉じやすくなる。

## 結果分類

provider は summary 生成結果を値として返す。

| 状態 | 意味 |
|---|---|
| `generated` | summary を生成できた |
| `skipped` | 要約不要と判断した |
| `failed` | 生成に失敗した |

`skipped` と `failed` は、どちらも summary を出さない結果になる。ただし意味は異なる。

- `skipped` は正常系であり、処理済みとして扱える
- `failed` は異常系であり、調査情報を Operational Log に残す

この区別を provider 境界で値として表すことで、summary engine は例外や LLM API の詳細を
知らずに state 更新やログ記録を判断できる。

## 外部 API 依存の扱い

LLM API は外部サービスであり、モデル更新、API 仕様変更、レート制限、出力切れ、
レスポンス構造の変化が起こりうる。

summary はベストエフォート機能なので、provider の失敗で hook 全体を止めない。
失敗はユーザー向け Notification には出さず、Operational Log に記録する。

ログは目的ではなく、失敗を分類し、後から調査できるようにするための手段である。
必要な情報は provider が `error_kind`、`retryable`、`metadata` などの形で返す。

## 変更時の判断

provider を変更するときは、次の原則を守る。

- LLM API や model に依存する判断は、その時点で改めて調査する
- summary engine に provider 固有の処理を追加しない
- prompt / schema / retry / API error の扱いは provider 内に閉じる
- `generated` / `skipped` / `failed` の意味を変えない
- summary 生成失敗をユーザー向け通知に混ぜない

詳細なモデル選定や API 設定値は、長期的な正本として固定しない。必要な場合は実装、
テスト、当時の調査メモを確認する。
