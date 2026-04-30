---
name: redmine-api
description: >
  Redmine REST APIを使用してチケット管理とプロジェクト管理を行うSkill。
  チケットの作成・更新・検索・一覧取得、プロジェクトの一覧・詳細・メンバー・バージョン取得が可能。
  「チケットを作成して」「自分のチケット一覧」「プロジェクト一覧を見せて」などの指示で起動する。
compatibility: Kiro IDE。bash/PowerShellでcurlコマンドが利用可能な環境。
metadata:
  version: "1.0.0"
  spec-url: "https://agentskills.io/specification"
  api-version: "Redmine 4.x / 5.x"
inclusion: manual
---

# Redmine API連携

Redmine REST APIを使用して、チケット管理とプロジェクト管理を行います。

## セキュリティ方針

APIキーなどの秘密情報はKiroに直接伝えない。以下の仕組みで保護する。

### 初回セットアップ（ユーザーが手動で実施）

1. `.env.example` をコピーして `.env` を作成する
2. `.env` にRedmineのURLとAPIキーを記入する
3. ターミナルで環境変数を読み込む: `source .env`（bash）または `. .\.env`（PowerShell）

```bash
# .env の内容（ユーザーが手動で記入）
REDMINE_URL=https://redmine.example.com
REDMINE_API_KEY=your-api-key-here
```

### 保護の仕組み

- `.kiroignore` に `.env` を記載 → Kiroが `.env` を読めない
- `.gitignore` に `.env` を記載 → リポジトリに入らない
- curlコマンドでは `$REDMINE_URL` / `$REDMINE_API_KEY` 環境変数を参照
- チャットでAPIキーの値を入力しない・表示しない

### 禁止事項（Kiroへの指示）

- `.env` ファイルを読み取ってはならない
- APIキーの値をチャットやログに出力してはならない
- ユーザーにAPIキーをチャットで入力するよう求めてはならない

## 認証

すべてのAPIリクエストに環境変数を使用：
```
X-Redmine-API-Key: $REDMINE_API_KEY
Content-Type: application/json
```

---

## チケット管理

### チケット一覧取得

```bash
# 自分に割り当てられたチケット
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/issues.json?assigned_to_id=me&status_id=open&limit=25"

# プロジェクト指定
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/projects/{{project_id}}/issues.json?limit=25"
```

表示項目: チケットID、題名、ステータス、優先度、担当者、更新日

### チケット詳細取得

```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/issues/{{issue_id}}.json?include=journals,attachments"
```

### チケット作成

```bash
curl -s -X POST \
  -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  -H "Content-Type: application/json" \
  "$REDMINE_URL/issues.json" \
  -d '{"issue":{"project_id":"{{project_id}}","subject":"題名","description":"説明","tracker_id":1,"priority_id":2}}'
```

必須: project_id、subject。未指定項目はユーザーに確認する。

### チケット更新

```bash
curl -s -X PUT \
  -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  -H "Content-Type: application/json" \
  "$REDMINE_URL/issues/{{issue_id}}.json" \
  -d '{"issue":{"status_id":{{status_id}},"notes":"コメント"}}'
```

更新可能: status_id、assigned_to_id、priority_id、done_ratio（0〜100）、due_date、notes

### チケット検索

```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/search.json?q={{keyword}}&issues=1"
```

---

## プロジェクト管理

### プロジェクト一覧

```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/projects.json"
```

### プロジェクト詳細

```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/projects/{{project_id}}.json?include=trackers,issue_categories"
```

### メンバー一覧

```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/projects/{{project_id}}/memberships.json"
```

### バージョン（マイルストーン）一覧

```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/projects/{{project_id}}/versions.json"
```

---

## 注意事項

- APIキーは絶対にログやチャットに表示しない
- チケット作成・更新前に内容をユーザーに確認する
- 大量取得時はページネーション（limit/offset）を使用する
- エラーレスポンス（401/403/404/422）は日本語で説明する

## Pythonツール（推奨）

curlの代わりに `scripts/redmine_tool.py` を使用できる。標準ライブラリのみで動作する。

```bash
# チケット一覧（自分の担当）
python scripts/redmine_tool.py issues --assigned-to me

# チケット詳細
python scripts/redmine_tool.py issue 123

# チケット作成
python scripts/redmine_tool.py create --project my-project --subject "題名" --description "説明"

# チケット更新（ステータス変更 + コメント）
python scripts/redmine_tool.py update 123 --status 3 --notes "対応完了"

# チケット検索
python scripts/redmine_tool.py search "キーワード"

# プロジェクト一覧
python scripts/redmine_tool.py projects

# プロジェクト詳細
python scripts/redmine_tool.py project my-project

# メンバー一覧
python scripts/redmine_tool.py members my-project

# バージョン一覧
python scripts/redmine_tool.py versions my-project
```

スクリプトの詳細は [scripts/redmine_tool.py](scripts/redmine_tool.py) を参照。

## ダッシュボードレポート生成

CSVファイルでプロジェクトを指定し、4定点（3週間前・2週間前・1週間前・現在）のチケット状況をHTMLダッシュボードとして出力する。

### 一気通貫の実行手順

ユーザーが「ダッシュボードを生成して」と指示した場合、以下を順番に実行する。

#### ステップ1: Python実行（HTML生成）

```bash
# 基本
python scripts/dashboard_report.py projects.csv -o dashboard.html

# プロジェクト補助データ（rpm.csv）付き
python scripts/dashboard_report.py projects.csv --rpm rpm.csv -o dashboard.html
```

#### ステップ2: AI考察の生成と挿入

HTML生成後、出力されたHTMLファイルを読み込み、`id="ai-insight-{project_id}"` のセクションを探す。
該当セクションが存在するプロジェクト（CSVでAIフラグが付いたもの）について、以下を実行する。

**上限: 最大10件まで。** CSVの記載順で先頭10件を対象とし、11件目以降はプレースホルダーのまま残す。

1. セクションの `data-project-name`、`data-recent-topics`、`data-summary` 属性からデータを読み取る
2. そのデータを元に、プロジェクトマネージャーの視点で以下の考察を生成する：
   - 直近1週間の課題チケットの動向分析
   - トラッカー別の進捗状況の評価
   - リスクや懸念事項の指摘
   - 推奨アクション
3. 生成した考察テキストで、セクション内の `<div class="ai-content">` の中身を置換する
4. 考察は日本語で、簡潔に3〜5文程度にまとめる

#### ステップ3: 完了報告

「ダッシュボードを生成しました。dashboard.html をブラウザで開いてください。」と報告する。
AIフラグ付きプロジェクトがあった場合は「AI考察を N件のプロジェクトに挿入しました。」と追記する。
6件以上のAIフラグがある場合は「AI考察は上限10件のため、残りN件はプレースホルダーのままです。」と追記する。

### CSVフォーマット

ヘッダー行あり、identifier形式。`ai_flag` 列は任意（省略可）。

```csv
project_identifier,ai_flag
my-project-001,1
my-project-002,0
my-project-003,1
```

`ai_flag` の値: `1` / `true` / `yes` / `○` でAI考察を有効化。

### 出力内容

一覧ページ:
- プロジェクトカード（プロジェクト名、identifier、チケット総数、トラッカー別件数・増減）
- AIフラグ付きプロジェクトには「🤖 AI」バッジ
- 全体概要テーブル

詳細ページ（プロジェクトカードをクリック）:
- 課題トピック（直近1週間で更新された課題チケット上位3件）
- AI考察（AIフラグ付きのみ）
- 課題・Q/A・サポート・バグの折れ線グラフ（2行2列レイアウト）
  - 課題・Q/A・サポート: 合計数 vs 解決・終了数
  - バグ: フェーズ別（IT/ST/UAT等）色分け推移
- 成果物の予実管理（サマリーバー + コンパクトテーブル + ガントチャート上位10件）

HTMLは完全オフライン動作（CSS/JSすべてインライン、外部リンクなし）。
デジタル庁デザインシステム v2 準拠。

サンプルCSVは [assets/projects_sample.csv](assets/projects_sample.csv) を参照。

詳細なID一覧やエラー対処は [references/REFERENCE.md](references/REFERENCE.md) を参照。
