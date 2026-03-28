# MindClaude — Project CLAUDE.md

> Claude Codeが毎回自動で読み込む開発ルール。

## Project Overview

**MindClaude** — EdrawMindのマインドマップ(.emmx)をClaude CodeやブラウザUIから読み書きできるMCPサーバー＋Webアプリ。

**Stack:** Python 3.8+ (標準ライブラリのみ、外部依存なし), MCP Protocol (stdio), HTTP Server (http.server)

**Architecture:** MCPサーバー(`server.py`)がEdrawMindの.emmxバイナリを解析。Webサーバー(`app.py`)がREST APIとUI配信。`index.html`は単一ファイル（CSS/JS埋め込み、フレームワーク不要）。

**Repository:** `https://github.com/akira1999work-debug/MindClaude`
**Path:** `C:\ClaudeCode\projects\MindClaude`
**Local:** `C:\ClaudeCode\MindClaude` (ローカル専用: context/dev-characters/)

## Critical Rules

### Zero Dependencies

- 外部Pythonパッケージを追加しない — 標準ライブラリのみ
- フロントエンドもフレームワーク・ビルドツール不要 — バニラJS + DOM + SVG
- 理由: インストール不要で動くことがこのプロジェクトの価値

### .emmx Parser

- .emmxはZIPアーカイブ（document.xml, mmpage/page.bin, theme.xml, rels/, media/）
- page.binは独自バイナリ。フィールド番号はテーマで変動する（122-123: ルート、126-131: ノード、132-134: NOTE、135: フローティング）
- パーサーの変更は慎重に — バイナリ解析のエッジケースが多い

### MCP Protocol

- プロトコルバージョン: `2024-11-05`
- Content-Length + JSON-RPC 2.0 over stdio
- ツール定義変更時は`TOOL_DEFINITIONS`と`TOOL_HANDLERS`を同時更新

### Frontend (index.html)

- 単一HTMLファイル（CSS/JS埋め込み）
- DOM + SVGベース（Canvasは使わない）
- ノード = `<div>`、接続線 = `<svg><path>`

### Code Style

- No emojis in code or comments
- Python: PEP 8準拠、型ヒント推奨（Python 3.8互換）
- JavaScript: ES6+、バニラJS（フレームワーク不使用）
- ファイルサイズ: 200-400行が目安、800行を超えたら分割

## File Structure

```
MindClaude/
  server.py          # MCPサーバー（.emmx解析、ツール定義）
  app.py             # Webサーバー + REST API
  index.html         # ブラウザUI（TODO）
  context/
    dev-characters/  # キャラナビゲーター 5人
  logs/
    sessions/        # セッションログ
    INDEX.md         # ログ索引
  commands/
    start.md         # セッション開始コマンド
    done.md          # セッション終了コマンド
    slides.md        # マインドマップ→スライド生成スキル
```

## REST API

| Method | Path | 説明 |
|--------|------|------|
| GET | `/` | index.html配信 |
| GET | `/api/emmx/list` | .emmxファイル一覧 |
| GET | `/api/emmx/read?path=...` | .emmx読み込み→JSON変換 |
| GET | `/api/maps` | 保存済みマップ一覧 |
| GET/POST/DELETE | `/api/maps/<id>` | マップCRUD |

## Security Checklist

コミット前に確認:

- [ ] ファイルパス操作でディレクトリトラバーサルがないか
- [ ] ユーザー入力（クエリパラメータ、JSON body）をバリデーションしているか
- [ ] `os.startfile()` / `subprocess` に外部入力を直接渡していないか
- [ ] tempファイルが適切にクリーンアップされるか

## ECC Development Workflow

### Agent Orchestration

| Agent | いつ使うか |
|-------|-----------|
| **planner** | 新機能の実装計画 |
| **architect** | アーキテクチャ判断（パーサー設計、API設計） |
| **tdd-guide** | 新機能・バグ修正時にテスト駆動開発 |
| **code-reviewer** | コード変更後に即座にレビュー |
| **security-reviewer** | ファイル操作・外部プロセス起動の変更時 |
| **build-error-resolver** | ビルド失敗時 |

並列実行ルール: 独立したタスクは必ず並列で実行する。

### Feature Flow

```
1. Research → 2. Plan → 3. TDD → 4. Code Review → 5. Security → 6. Commit
```

### Git Workflow

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Feature branches from `main`
- PRにはテストプラン必須
