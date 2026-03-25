# MindClaude 開発セッション開始

> セッション開始時の自動復元 → 1問分岐

## Phase 1: 自動復元（並列実行、ユーザー入力なし）

以下を**並列で**実行する:

1. `C:\ClaudeCode\projects\MindClaude\CLAUDE.md` を読む（設計哲学・コンテキスト一覧）
2. `C:\ClaudeCode\MindClaude\context\dev-characters\` を読む（README + meeting-mode + 凛 + 心春）※ローカル専用
3. `C:\ClaudeCode\projects\MindClaude\logs\sessions\` の最新1件を読む（前回申し送り）
4. git操作を実行:
   ```bash
   cd C:/ClaudeCode/projects/MindClaude
   git fetch origin 2>/dev/null
   git status
   git log --oneline -5
   ```

## Phase 2: 報告 → 1問だけ聞く

以下を報告:
- 現在のブランチと状態
- 最新コミット
- 前回セッションの「次回やること」

**質問**: 「前回の続きから進める？ 別の作業をする？」

回答に応じて分岐:
- **続き** → 前回ログの「次回やること」から着手。関連context/を遅延読み込み
- **別の作業** → 作業内容を聞いて、関連context/を遅延読み込み
- **ブランチ変更** → git checkout → 該当作業に切り替え

## Phase 3: 凛+心春ペア起動

以降のセッションでは凛と心春が常駐:

```
**心春**: [ユーザー視点のコメント — 必要な時だけ]
**凛**: [リスク・技術視点のコメント — 必要な時だけ]
```

「5人に聞いて」「会議して」で5人会議モードに切り替え。

## ルール

- Phase 1は**必ず並列実行**（順次実行しない）
- Phase 2の質問は**1問だけ**（複数の質問で開始を遅らせない）
- context/ファイルは**必要になった時に遅延読み込み**（一括読みしない）
- 5人のキャラファイル全員分は5人会議が必要になった時に読む
