# Redmine API リファレンス

## デフォルトID一覧

### ステータスID

| ID | ステータス名 |
|----|-------------|
| 1  | 新規        |
| 2  | 進行中      |
| 3  | 解決        |
| 4  | フィードバック |
| 5  | 終了        |
| 6  | 却下        |

確認コマンド:
```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" "$REDMINE_URL/issue_statuses.json"
```

### トラッカーID

| ID | トラッカー名 |
|----|-------------|
| 1  | バグ        |
| 2  | 機能        |
| 3  | サポート    |

> 本Skillのダッシュボードで使用するトラッカーは以下の通りです。IDはRedmineの設定により異なります。

| ダッシュボード対象 | 用途 |
|-------------------|------|
| 課題 | 折れ線グラフ（合計数 vs 解決・終了数）、課題トピック |
| Q/A | 折れ線グラフ（合計数 vs 解決・終了数） |
| サポート | 折れ線グラフ（合計数 vs 解決・終了数） |
| 成果物 | ガントチャート風タイムライン + サマリーバー（予実管理） |
| 進捗報告 | プロマネ報告セクション（最新の説明文/コメントを表示）、AI考察のインプット |

確認コマンド:
```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" "$REDMINE_URL/trackers.json"
```

### 優先度ID

| ID | 優先度名 |
|----|---------|
| 1  | 低め    |
| 2  | 通常    |
| 3  | 高め    |
| 4  | 急いで  |
| 5  | 今すぐ  |

確認コマンド:
```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" "$REDMINE_URL/enumerations/issue_priorities.json"
```

> すべてのIDはRedmineの設定により異なる場合があります。初回利用時に上記コマンドで実際の値を確認してください。

---

## ページネーション

大量データ取得時のパラメータ：
- `limit`: 1回の取得件数（デフォルト25、最大100）
- `offset`: 開始位置
- `total_count`: レスポンスに含まれる総件数

例: 26件目から50件取得
```bash
curl -s -H "X-Redmine-API-Key: $REDMINE_API_KEY" \
  "$REDMINE_URL/issues.json?limit=25&offset=25"
```

---

## フィルタパラメータ

チケット一覧で使用可能なフィルタ：

| パラメータ | 説明 | 例 |
|-----------|------|-----|
| status_id | ステータス（open/closed/*） | `status_id=open` |
| assigned_to_id | 担当者ID（meで自分） | `assigned_to_id=me` |
| tracker_id | トラッカーID | `tracker_id=1` |
| priority_id | 優先度ID | `priority_id=4` |
| created_on | 作成日（>=, <=, ><で範囲指定） | `created_on=>=2025-01-01` |
| updated_on | 更新日 | `updated_on=>=2025-04-01` |
| due_date | 期日 | `due_date=<=2025-05-01` |
| sort | ソート（フィールド:asc/desc） | `sort=updated_on:desc` |

---

## エラーレスポンス対処

| HTTPステータス | 意味 | 対処 |
|---------------|------|------|
| 401 Unauthorized | APIキーが無効 | APIキーを再確認する |
| 403 Forbidden | 権限不足 | 対象リソースへのアクセス権を確認する |
| 404 Not Found | リソースが存在しない | ID・URLを確認する |
| 422 Unprocessable Entity | バリデーションエラー | 必須フィールドや値の形式を確認する |
| 500 Internal Server Error | サーバーエラー | 時間を置いて再試行する |

---

## レスポンス例

### チケット一覧レスポンス（抜粋）
```json
{
  "issues": [
    {
      "id": 123,
      "subject": "ログイン画面のバグ修正",
      "status": {"id": 2, "name": "進行中"},
      "priority": {"id": 3, "name": "高め"},
      "assigned_to": {"id": 5, "name": "田中太郎"},
      "updated_on": "2025-04-28T10:30:00Z"
    }
  ],
  "total_count": 42,
  "offset": 0,
  "limit": 25
}
```

### プロジェクト一覧レスポンス（抜粋）
```json
{
  "projects": [
    {
      "id": 1,
      "identifier": "my-project",
      "name": "マイプロジェクト",
      "description": "プロジェクトの説明",
      "status": 1,
      "created_on": "2025-01-15T09:00:00Z"
    }
  ]
}
```

---

## ダッシュボードレポート

### CSVフォーマット

```csv
project_identifier,ai_flag
my-project-001,1
my-project-002,0
```

| カラム | 必須 | 説明 |
|--------|------|------|
| project_identifier | はい | RedmineのプロジェクトID（identifier形式） |
| ai_flag | いいえ | AI考察を有効にする場合: `1` / `true` / `yes` / `○` |

### 制限事項

| 項目 | 値 |
|------|-----|
| CSVプロジェクト上限 | 30件 |
| APIリクエスト間隔 | 0.5秒（毎リクエスト後） |
| AI考察の上限 | 5件（CSVの記載順で先頭5件） |
| 定点数 | 4（3週間前・2週間前・1週間前・現在） |

### 状態復元の仕組み

ダッシュボードの4定点データは、チケットの `journals`（変更履歴）から過去の状態を復元して算出しています。

- ステータス: `journals[].details` の `status_id` 変更を逆順に巻き戻し
- 進捗率: `journals[].details` の `done_ratio` 変更を逆順に巻き戻し
- 対象定点より後の変更を巻き戻すことで、その時点の状態を再現

### サブプロジェクトの扱い

- `/projects/{id}.json?include=children` でサブプロジェクトを自動検出
- サブプロジェクトのチケットは親プロジェクトに合算
- ダッシュボード上は親プロジェクト単位で表示

### 進捗報告トラッカーの取得ロジック

1. プロジェクト内の「進捗報告」トラッカーのチケットを全件取得
2. `updated_on` が最新のチケットを選択
3. そのチケットの最新コメント（`journals` の `notes`）があればそれを表示
4. コメントがなければチケットの `description`（説明文）を表示
5. 表示は先頭300文字で切り詰め、「続きを読む」で全文展開

### AI考察のdata属性

HTMLのAI考察プレースホルダーには以下のdata属性が埋め込まれます：

| 属性 | 内容 |
|------|------|
| `data-project` | プロジェクトidentifier |
| `data-project-name` | プロジェクト名 |
| `data-recent-topics` | 直近1週間の課題チケットタイトル（セミコロン区切り） |
| `data-summary` | トラッカー別の現在件数と解決・終了数 |
| `data-progress-report` | 進捗報告の最新テキスト（先頭500文字） |

### コマンドラインオプション

```
usage: dashboard_report.py [-h] [-o OUTPUT] [--rpm RPM] csv

positional arguments:
  csv                   プロジェクトID一覧のCSVファイルパス

optional arguments:
  -h, --help            ヘルプを表示
  -o OUTPUT, --output OUTPUT
                        出力HTMLファイルパス（デフォルト: dashboard.html）
  --rpm RPM             プロジェクト補助データCSV（rpm.csv）のパス（省略可）
```
