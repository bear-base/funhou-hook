# 設計ドキュメント

このプロジェクトの主要な設計は [ai-agent-funhou-system.md](./ai-agent-funhou-system.md) にまとめています。

`docs/design.md` は、日々の実装判断に必要な要点と、Claude Code の hook イベントから `log` / `summary` / `approval` の統一メッセージ型へどう写像するかをまとめる入口です。

## 現時点の要約

- コアは通知プラットフォームに依存しない
- 出力の中心は `log` / `summary` / `approval` の 3 種類
- 危険度判定は hard rules → project context → AI screening の順で行う
- 最初は最小構成で始め、段階的に通知先や双方向性を拡張する

## 統一メッセージ型

### `log`

通常の作業ログや状態変化、結果を表す。

例:
- ツール実行前のログ
- ツール実行後のログ
- 入力待ちになったことのログ
- 承認の結果ログ

### `summary`

一定区切りでの要約を表す。Phase 1 では未実装。

### `approval`

人間のアクションが必要で、セッションが停止している状態を表す。

例:
- Claude が権限承認待ちで止まっている
- 将来、明示的な確認ダイアログや承認要求を扱う場合

## Claude Code のイベントとの対応

Claude Code の hook イベントと、`funhou-hook` 側の統一メッセージ型の対応は次のように定義する。

### `PreToolUse` → `log`

ツール実行前のイベントは、基本的に `log` として扱う。

- `tool_name`
- `tool_input`
- ルールに基づく危険度

を使って 1 行ログに落とす。

### `PermissionRequest` → `approval`

`PermissionRequest` は、Claude Code における承認待ちの基本イベントとして扱う。

これは「人間の承認が必要で Claude が停止している状態」を表すため、基本設計として `approval` 型に写像する。

つまり、承認待ちの正式な起点は `Notification(permission_prompt)` ではなく `PermissionRequest` である。

### `PostToolUse` / `PostToolUseFailure` → `log`

ツール実行後のイベントは `log` として扱う。

ただし、直前に `PermissionRequest` があり、同じ対象のツール実行に対応付けられる場合は、通常の実行ログに加えて「承認されたため実行された」という経緯ログも記録する。

つまり、承認待ちのあとに対象ツールが実行されたら、それは承認結果として「許可された」とみなし、`log` に残す。

### `PermissionDenied` → `log`

`PermissionDenied` は auto mode classifier による拒否イベントであり、承認結果としては「拒否」にあたるため、経緯追跡のために `log` として記録する。

少なくとも次の情報を残す。

- 拒否された対象
- 拒否理由
- 承認待ちから拒否に至ったこと

### `Notification(idle_prompt)` → `log`

`idle_prompt` は、ユーザー入力待ちで停止している状態を示す。

これは人間のアクションは必要だが、権限承認という意味ではないため、`approval` ではなく状態ログとして `log` 型に写像する。

### `Notification(permission_prompt)` → 補助的な `approval`

`permission_prompt` は、来る環境では承認待ちを表す補助イベントとして扱ってよい。

ただし、Claude Code の実運用では承認待ちの主経路として常に来るとは限らないため、基本設計の中心には置かない。設計の正本は `PermissionRequest` を承認待ちの起点とする。

## 承認フローの基本設計

承認系の状態は、意味として次の 3 段階に分ける。

### 1. 承認待ち

- 起点イベント: `PermissionRequest`
- 統一メッセージ型: `approval`

この段階では、人間の判断が必要でセッションが止まっている。

### 2. 承認済み

- 結果イベント: `PostToolUse` / `PostToolUseFailure`
- 統一メッセージ型: `log`

承認されたあとに実行へ進んだことを、経緯として `log` に残す。

### 3. 拒否

- 結果イベント: `PermissionDenied`
- 統一メッセージ型: `log`

拒否されたことも、経緯として `log` に残す。

## 承認結果を記録する理由

`approval` だけを記録しても、「その後どうなったか」が分からないと分報として経緯を追えない。

そのため基本設計として、承認要求が発生した場合は可能な限りその結果も記録対象とする。

- 許可された場合: 実行に進んだことを `log` に残す
- 拒否された場合: 拒否されたことを `log` に残す

ここで重要なのは、`approval` は「いま止まっていて人間の判断が必要」という状態であり、許可/拒否という結果そのものではない、という点である。

## `Notification` の位置づけ

`Notification` は有用だが、承認まわりの主経路ではなく補助的なイベントとして扱う。

- `idle_prompt` は入力待ちの状態ログとして有効
- `permission_prompt` は来る環境では承認待ちの補助表示として有効
- ただし、承認待ちの基本設計は `PermissionRequest` を中心に組み立てる

これにより、実際のイベント出力の揺れに対しても設計が安定する。

## 現時点の制約

Claude Code Hooks の仕様上、手動で permission dialog を拒否したケースを常に直接 hook で観測できるとは限らない。少なくとも `PermissionDenied` は auto mode classifier の拒否のみを対象にし、手動拒否では発火しない可能性がある。

このため現時点では、承認結果の記録は次の範囲で実装する。

- 許可: `PostToolUse` / `PostToolUseFailure` により追跡する
- auto mode の拒否: `PermissionDenied` により追跡する
- 手動拒否: 現行 hook 仕様だけでは完全には追跡できない可能性がある

これは実装上の制約であり、設計上は「承認結果も記録すべき」という原則を維持する。
