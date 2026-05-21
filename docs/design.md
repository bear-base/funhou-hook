# 設計ドキュメント

`docs/design.md` は、Claude Code の hook イベントを `log` / `summary` / `approval`
の統一メッセージ型へどう写像するかをまとめる設計入口です。

詳細な summary 生成方針は [summary-engine.md](./summary-engine.md)、provider 境界の
設計思想は [summary-provider.md](./summary-provider.md)、ログ種別の方針は
[logging.md](./logging.md) に分けます。

## 現時点の要約

- コアのメッセージ型は通知プラットフォームに依存しない
- 出力の中心は `log` / `summary` / `approval` の 3 種類
- 危険度判定は現時点では hard rules を中心に行う
- 配送先は terminal log と Slack を設定で切り替える
- サマリー生成はベストエフォート機能として扱う

## 統一メッセージ型

### `log`

通常の作業ログや状態変化、結果を表す。

例:
- ツール実行前のログ
- ツール実行後のログ
- 入力待ちになったことのログ
- 承認の結果ログ

### `summary`

一定区切りでの作業要約を表す。現状は `Stop` を標準トリガーとし、必要に
応じて `PermissionRequest` でも生成できる。

`summary` は危険度通知ではないため、`level` を持たない。配送可否は channel
ごとの message type 設定で判断する。

### `approval`

人間のアクションが必要で、セッションが停止している状態を表す。

例:
- Claude が権限承認待ちで止まっている
- 将来、明示的な確認ダイアログや承認要求を扱う場合

`approval` は承認待ちを通知するメッセージであり、承認可否の判断や実行制御
そのものは Claude Code 側に委ねる。

## Claude Code のイベントとの対応

Claude Code の hook イベントと、`funhou-hook` 側の統一メッセージ型の対応は
次のように定義する。

### `PreToolUse` → `log`

ツール実行前のイベントは、基本的に `log` として扱う。

- `tool_name`
- `tool_input`
- ルールに基づく危険度

を使って作業ログに落とす。

### `PermissionRequest` → `approval`、必要に応じて `summary`

`PermissionRequest` は、Claude Code における承認待ちの基本イベントとして扱う。

これは「人間の承認が必要で Claude が停止している状態」を表すため、基本設計
として `approval` 型に写像する。承認待ちの正式な起点は
`Notification(permission_prompt)` ではなく `PermissionRequest` である。

`summary.triggers` に `PermissionRequest` が含まれる場合は、承認要求の前に
`summary` を生成し、ここまでの経緯を示す。デフォルトでは `PermissionRequest`
では summary を生成しない。

### `Stop` → `summary`

`Stop` はターン終了時のサマリートリガーとして扱う。

`summary.enabled = true` かつ `summary.triggers` に `Stop` が含まれる場合、
直近ログから `summary` を生成する。生成に失敗した場合や要約不要と判断した
場合は、メッセージを出さない。

### `PostToolUse` / `PostToolUseFailure` → `log`

ツール実行後のイベントは `log` として扱う。

ただし、直前に `PermissionRequest` があり、同じ対象のツール実行に対応付けられる
場合は、通常の実行ログに加えて「承認されたため実行された」という経緯ログも
記録する。

つまり、承認待ちのあとに対象ツールが実行されたら、それは承認結果として
「許可された」とみなし、`log` に残す。

### `PermissionDenied` → `log`

`PermissionDenied` は auto mode classifier による拒否イベントであり、承認結果
としては「拒否」にあたるため、経緯追跡のために `log` として記録する。

少なくとも次の情報を残す。

- 拒否された対象
- 拒否理由
- 承認待ちから拒否に至ったこと

### `Notification(idle_prompt)` → `log`

`idle_prompt` は、ユーザー入力待ちで停止している状態を示す。

これは人間のアクションは必要だが、権限承認という意味ではないため、`approval`
ではなく状態ログとして `log` 型に写像する。

### `Notification(permission_prompt)` → 生成しない

`permission_prompt` は `PermissionRequest` と重複しやすいため、現行実装では
メッセージを生成しない。

承認待ちの正本は `PermissionRequest` とする。

## 承認フローの基本設計

承認系の状態は、意味として次の 3 段階に分ける。

### 1. 承認待ち

- 起点イベント: `PermissionRequest`
- 統一メッセージ型: `approval`

この段階では、人間の判断が必要でセッションが止まっている。

承認待ち時の `summary` は `approval` そのものではなく、承認判断の材料として
前置される補助情報である。

### 2. 承認済み

- 結果イベント: `PostToolUse` / `PostToolUseFailure`
- 統一メッセージ型: `log`

承認されたあとに実行へ進んだことを、経緯として `log` に残す。

### 3. 拒否

- 結果イベント: `PermissionDenied`
- 統一メッセージ型: `log`

拒否されたことも、経緯として `log` に残す。

## 承認結果を記録する理由

`approval` だけを記録しても、「その後どうなったか」が分からないと分報として
経緯を追えない。

そのため基本設計として、承認要求が発生した場合は可能な限りその結果も記録対象
とする。

- 許可された場合: 実行に進んだことを `log` に残す
- 拒否された場合: 拒否されたことを `log` に残す

ここで重要なのは、`approval` は「いま止まっていて人間の判断が必要」という
状態であり、許可/拒否という結果そのものではない、という点である。

## `Notification` の位置づけ

`Notification` は有用だが、承認まわりの主経路ではなく補助的なイベントとして
扱う。

- `idle_prompt` は入力待ちの状態ログとして有効
- `permission_prompt` は `PermissionRequest` と重複するため、現行実装では通知しない
- 承認待ちの基本設計は `PermissionRequest` を中心に組み立てる

これにより、実際のイベント出力の揺れに対しても設計が安定する。

## 配送の考え方

`FunhouMessage` は通知先に依存しない。terminal / Slack などの配送先は dispatcher
と channel 設定で決める。

`log` と `approval` は message type と level で配送判定する。`summary` は level
を持たないため、message type のみで配送判定する。

Slack の表示調整は Slack formatter の責務であり、コアのメッセージ型には持ち込まない。

## サマリーの基本設計

サマリーはベストエフォート機能であり、生成に失敗しても hook 全体を失敗させない。

分報不要と判断された場合は正常スキップとして扱い、生成失敗とは区別する。失敗時
のログ記録、リトライ、offset 更新の詳細は summary / provider 側の設計に委ねる。

## 現時点の制約

Claude Code Hooks の仕様上、手動で permission dialog を拒否したケースを常に
直接 hook で観測できるとは限らない。少なくとも `PermissionDenied` は auto mode
classifier の拒否のみを対象にし、手動拒否では発火しない可能性がある。

このため現時点では、承認結果の記録は次の範囲で実装する。

- 許可: `PostToolUse` / `PostToolUseFailure` により追跡する
- auto mode の拒否: `PermissionDenied` により追跡する
- 手動拒否: 現行 hook 仕様だけでは完全には追跡できない可能性がある

これは実装上の制約であり、設計上は「承認結果も記録すべき」という原則を維持する。
