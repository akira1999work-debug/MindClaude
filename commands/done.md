# MindClaude 開発セッション終了

> 設計判断をcontext/に振り分け、20-30行の申し送りセッションログを生成し、INDEX.mdを更新する。

## Step 1: 情報の振り分け（5分類）

今回のセッションで発生した情報を以下の5カテゴリに分類:

| 分類 | 行き先 | 判断基準 |
|------|--------|---------|
| 設計判断 | `context/` の該当ファイル | 「〜に決めた」「〜は廃止」→ 確定事項 |
| 実装進捗 | `context/` のスコープ/ロードマップファイル | コミット済みコード、フェーズ完了/未完了 |
| キャラ改善 | `context/dev-characters/` の改善ログ | 5人会議実施時のみ。発言品質の△×を記録 |
| 未決・TODO | セッションログのみ | 結論が出ていない議題 |
| 議論経緯 | `logs/meetings/YYYY-MM-DD_トピック名.md` | **重要な議論のみ**保存 |

## Step 2: 5人挙動レビュー（5人会議実施時のみ）

5人会議を実施した場合、各キャラの発言品質を自己採点。
△×のキャラ → `context/dev-characters/` の改善ログに即座に記録。

## Step 3: セッションログ生成

**場所:** `C:\ClaudeCode\projects\MindClaude\logs\sessions\YYYY-MM-DD.md`
（同日2回目以降は `_2`, `_3`）

**20-30行厳守。以下のテンプレート:**

```markdown
# MindClaude 開発セッション YYYY-MM-DD

## 今日やったこと（1-3行）
- 〜〜 → context/xx.md に反映済み
- 〜〜 → commit: xxxxxxx

## 更新したcontext
- context/xxx.md — 変更内容1行
- dev-characters/xxx.md — 変更内容1行

## 未決
- [ ] 〜〜

## 次回やること
1. 〜〜
2. 〜〜
```

## Step 4: INDEX.md 更新

`C:\ClaudeCode\projects\MindClaude\logs\INDEX.md` にエントリを追加。

## Step 5: 実行順序

1. 振り分けに基づいて context/ ファイルを更新（並列可）
2. 5人挙動レビュー → dev-characters/ 改善ログ記録（該当する場合）
3. セッションログ生成
4. INDEX.md 更新
5. 全変更をcommit
