# MindClaude 開発TODO

## 完了済み
- [x] `server.py` — MCPサーバー（.emmx読み込み、構造化パーサー、NOTE対応、generate_plan）
- [x] `app.py` — Webサーバー + REST API（.emmxインポート、JSON保存/読み込み、ポート設定可能）

## 次のタスク: `index.html` — ブラウザベースのマインドマップUI

### セットアップ
```bash
git clone https://github.com/akira1999work-debug/MindClaude
cd MindClaude
python3 app.py
# http://localhost:8080 で開く
```

### 技術方針
- 単一HTMLファイル（CSS/JS埋め込み、ビルドツール不要、フレームワーク不要）
- DOM + SVGベース（Canvasは使わない）
- ノード = `<div>`、接続線 = `<svg><path>`
- パン = コンテナdivのtranslate、ズーム = CSS transform scale

### 実装する機能

#### マインドマップ表示
- ノードをdivで表示、ツリーレイアウトで自動配置
- 親子間をSVG bezier曲線で接続
- ルートノードは中央、子は右に展開（水平レイアウト）
- 展開/折りたたみ（三角アイコンクリック）
- 深さごとにノード色を変える

#### 操作
- パン: 背景ドラッグ
- ズーム: マウスホイール（0.3〜3.0倍、カーソル位置起点）
- ノード選択: クリック（ハイライト表示）
- ノード編集: ダブルクリック → input表示 → blur/Enterで確定

#### キーボードショートカット
- `Tab` — 選択ノードの子を追加
- `Enter` — 選択ノードの兄弟を追加
- `Delete` — 選択ノード削除
- `F2` — 選択ノードのラベル編集
- `Escape` — 選択解除 / NOTEパネル閉じる

#### NOTEパネル（SuperNote代替）
- 右サイドにスライドアウトする300pxパネル
- ノードクリックで開く
- `<textarea>`でプレーンテキスト編集（v1）
- 編集内容はノードのnoteフィールドに保存
- 閉じるボタンあり

#### ファイル操作
- **新規**: ルートノード1つの状態にリセット
- **保存**: POST /api/maps → ~/.mindclaude/maps/ にJSON保存
- **開く**: GET /api/maps → リスト表示 → 選択 → ロード
- **インポート(.emmx)**: GET /api/emmx/list → リスト表示 → GET /api/emmx/read?path=... → ツリーに変換

#### ツールバー
- New, Open JSON, Import .emmx, Save, + Child, + Sibling, Delete

### JSON保存フォーマット
```json
{
  "version": 1,
  "title": "マインドマップタイトル",
  "nodes": {
    "root": {
      "id": "root",
      "label": "中心トピック",
      "note": "NOTEの長文テキストがここに入る",
      "children": ["node_1", "node_2"],
      "collapsed": false
    },
    "node_1": {
      "id": "node_1",
      "label": "ブランチ1",
      "note": "",
      "children": [],
      "collapsed": false
    }
  },
  "rootId": "root"
}
```

### REST API（app.pyで実装済み）
| Method | Path | 説明 |
|--------|------|------|
| GET | `/` | index.html配信 |
| GET | `/api/emmx/list` | .emmxファイル一覧 |
| GET | `/api/emmx/read?path=...` | .emmx読み込み→JSON変換 |
| GET | `/api/maps` | 保存済みマップ一覧 |
| GET | `/api/maps/<id>` | マップ読み込み |
| POST | `/api/maps` | マップ新規保存 |
| POST | `/api/maps/<id>` | マップ更新 |
| DELETE | `/api/maps/<id>` | マップ削除 |

## 将来のタスク
- EdrawMind/.emmxとオリジナルの両対応（ユーザーが選べるように）
- ガントチャートビュー
- カンバンビュー
- アウトラインモード（テキスト一括編集）
- タスク管理（優先度、期限、進捗）
- ドラッグでノード移動・並べ替え

## .emmx解析メモ
- .emmxはZIPアーカイブ（document.xml, mmpage/page.bin, theme.xml, rels/, media/）
- page.binは独自バイナリ。テキストはUTF-8でインライン格納
- フィールド番号はテーマによって変動する（122-123: ルート、126-131: ノード、132-134: NOTE、135: フローティング/参照）
- インラインNOTE(field 132-134)は読める
- SuperNote(クラウド)はハッシュIDのみ保存、ローカル取得不可 → オリジナルではローカル保存にした
