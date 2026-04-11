# 設計ドキュメント

このプロジェクトの主要な設計は [ai-agent-funhou-system.md](./ai-agent-funhou-system.md) にまとめています。

`docs/design.md` は参照先を固定するための入口です。今後設計書を分割しても、このパスを起点に辿れるようにします。

## 現時点の要約

- コアは通知プラットフォームに依存しない
- 出力の中心は `log` / `summary` / `approval` の3種類
- 危険度判定は hard rules → project context → AI screening の順で行う
- 最初は最小構成で始め、段階的に通知先や双方向性を拡張する
