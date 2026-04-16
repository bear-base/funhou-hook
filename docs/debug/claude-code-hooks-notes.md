# Claude Code Hooks Debug Notes

## 目的

Claude Code Hooks を使って funhou-hook を組み込むときに、仕様上つまずきやすい点を簡潔に残す。

## 今回わかったこと

### 1. 承認待ちの主イベントは `Notification(permission_prompt)` とは限らない

実際の挙動では、承認待ちの開始を表す主経路は `PermissionRequest` だった。
`Notification(permission_prompt)` は来る環境もあるが、常に来る前提では設計しないほうがよい。

### 2. 承認後は `PostToolUse` で追うのが基本

承認ボタン押下後は、結果として `PostToolUse` または `PostToolUseFailure` が来る。
承認そのものの専用イベントが別に来るとは限らないため、承認後の経緯は実行結果イベントから追う設計が必要になる。

### 3. 通常ログが出ていても、承認系だけ壊れていることがある

`PreToolUse` が正常でも、`PermissionRequest` / `PostToolUse` 側だけ別経路の内部状態に依存して落ちることがある。
今回も通常ログは出ていたが、承認系は state file の JSON 破損で異常終了していた。

### 4. Claude Code 側でイベントが出ているかと、hook 側で処理できているかは別問題

debug ログでは `PermissionRequest` と `PostToolUse` が来ていたが、hook 側の内部例外により `/tmp/funhou.log` には出ていなかった。
そのため、イベント受信確認だけでは不十分で、hook 内処理の段階ログも必要になる。

## 今回困ったこと

- `Notification(permission_prompt)` を承認待ちの正規イベントだと見なしていた
- 実際には `PermissionRequest` が主経路だった
- 通常ログが出ていたため、最初は設定ミスよりも浅い問題に見えた
- 実際は内部 state file の JSON 破損で、承認系イベントだけ落ちていた
- 例外が見えるまで「イベントが来ていない」のか「処理で落ちている」のか切り分けに時間がかかった

## 先に確認するとよい順番

1. `settings.json` に対象イベントが登録されているか確認する
2. debug ログで `PermissionRequest` / `PostToolUse` が実際に来ているか確認する
3. `/tmp/funhou.log` に出ていないなら、hook の stderr / traceback を確認する
4. 内部 state file や一時ファイルの破損有無を確認する

## 実運用での注意

- `PermissionRequest` を承認待ちの正式な起点として扱う
- `Notification(permission_prompt)` は補助扱いに留める
- 承認後の追跡は `PostToolUse` / `PostToolUseFailure` 前提で考える
- hook はイベントを受けるだけでなく、内部状態の破損でも止まらない設計にする
- デバッグ用の structured log を常備しておくと切り分けが速い
