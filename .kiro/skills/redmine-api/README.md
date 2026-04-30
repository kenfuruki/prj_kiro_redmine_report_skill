# redmine-api

Kiro用のAgent Skillで、Redmine REST APIを通じてチケット管理・プロジェクト管理・ダッシュボードレポート生成を自然言語で操作できます。ダッシュボードレポートはhooksのボタン１つで自動で動きます。

[Agent Skills標準](https://agentskills.io/specification) に準拠しています。

## 機能概要

### チケット管理
| 操作 | 説明 | コマンド例 |
|------|------|-----------|
| 一覧取得 | 条件を指定してチケットを一覧表示 | `issues --assigned-to me` |
| 詳細取得 | チケットの詳細・コメント履歴を表示 | `issue 123` |
| 作成 | 新しいチケットを作成 | `create --project my-proj --subject "題名"` |
| 更新 | ステータス・担当者・進捗率などを変更 | `update 123 --status 3 --notes "完了"` |
| 検索 | キーワードでチケットを検索 | `search "キーワード"` |

### プロジェクト管理
| 操作 | 説明 | コマンド例 |
|------|------|-----------|
| プロジェクト一覧 | 全プロジェクトを一覧表示 | `projects` |
| プロジェクト詳細 | トラッカー・カテゴリ含む詳細を表示 | `project my-proj` |
| メンバー一覧 | プロジェクトメンバーとロールを表示 | `members my-proj` |
| バージョン一覧 | マイルストーン（バージョン）を表示 | `versions my-proj` |

### ダッシュボードレポート
CSVでプロジェクトを指定し、4定点（3週間前・2週間前・1週間前・現在）のチケット状況をHTMLダッシュボードとして出力します。

**一覧ページ:**
- プロジェクトカード（プロジェクト名、identifier、チケット総数、トラッカー別件数・増減）
- AIフラグ付きプロジェクトには「🤖 AI」バッジ
- カードクリックで詳細ページに遷移

**詳細ページ（プロジェクト別）:**
- 📊 工程別 成果物・テスト進捗（バージョンごとの総数/予定/完了/達成率テーブル）
  - 上流〜設計（SA/UC/SS）: 成果物トラッカーの総数・期日到来済み予定数・終了完了数
  - テストフェーズ（IT/ST/UAT）: テストスイートトラッカーの予定ケース数・実績ケース数
  - SP/PG/PT/OT工程は除外、取消ステータスも除外
  - > テストスイートのカスタムフィールド名は初回セットアップで設定が必要です（SKILL.mdの手順を参照）
- 📋 プロマネ報告（最新の進捗報告トラッカーの説明文・コメント、アコーディオン方式で開閉可能）
- 課題トピック（直近1週間で更新された課題チケット上位3件）
- 🤖 AI考察（AIフラグ付き + 期限リスク検知、最大10件）
- 課題・Q/A・サポート・バグの折れ線グラフ（2行2列レイアウト）
  - 課題・Q/A・サポート: 合計数 vs 解決・終了数の推移
  - バグ: フェーズ別（IT/ST/UAT等）色分け推移
- 成果物の予実管理（サマリーバー + コンパクトテーブル + ガントチャート上位10件）

**対応トラッカー:** 課題、Q/A、サポート、成果物、進捗報告、バグ

**特徴:**
- デジタル庁デザインシステム v2 準拠（カラー・タイポグラフィ・コントラスト比）
- 完全オフライン動作（CSS/JS/SVGすべてインライン、外部リンクなし）
- サブプロジェクトのチケットを親プロジェクトに自動合算（多階層対応、循環参照防止付き）
- データがない定点は「-」表示（エラーにならない）

#### プロジェクト自動抽出

`--rpm` オプションでrpm.csvを指定した場合、CSVに記載されていないプロジェクトを自動的にダッシュボードに追加します。

- **動作条件:** `--rpm` オプションでrpm.csvが指定されている場合のみ動作
- **抽出ロジック:** rpm.csv内のレコードから、サービスイン予定日が操作日以降のプロジェクトを抽出し、課題+Q/Aチケット数が多い順に上位5件を選出
- **除外条件:** Projects_CSVに既に記載されているプロジェクト、サービスイン予定日が空欄のレコード、Redmine上に存在しないプロジェクトは除外
- **上限:** CSVプロジェクトと合わせてMAX_PROJECTS（30件）を超えない範囲で調整
- **「🔍 自動抽出」バッジ:** 自動抽出されたプロジェクトの行に表示され、CSVに手動記載されたプロジェクトと区別できます
- **AI考察:** 自動抽出プロジェクトのai_flagは無効（AI考察の対象外）ですが、期限リスクが検知された場合はAI考察対象に含まれます

#### 期限リスク検知

課題チケットとQ/Aチケットの期限超過・期限未設定の推移を4定点で分析し、上昇傾向にあるプロジェクトを警告します。

- **Risk_Score:** 各定点における「期限超過チケット数 + 期限未設定チケット数」（完了ステータスのチケットは除外）
- **判定ロジック:** 3区間（3週間前→2週間前、2週間前→1週間前、1週間前→現在）のうち2区間以上でRisk_Scoreが増加している場合、「上昇傾向」と判定
- **「⚠ 期限リスク」バッジ:** 上昇傾向と判定されたプロジェクトの行に表示。ツールチップに4定点のRisk_Score推移（例: 「3→5→4→7」）を表示
- **詳細ページ:** プロジェクト詳細ページにRisk_Score推移テーブルを表示
- **AI考察への影響:** 期限リスクが検知されたプロジェクトは、CSVのai_flagに関わらずAI考察の対象に含まれます（上限10件の中でカウント）

#### フィルタ・ソート機能

一覧テーブルの各列でフィルタリングやソートが可能です。

**フィルタボタン:** テーブル上部に4つのボタンがあり、クリックでプロジェクトを絞り込めます。
- 「全件」— フィルタ解除（デフォルト）
- 「⚠ 期限リスク」— 期限リスクありのプロジェクトのみ
- 「🤖 AI対象」— AI考察対象のプロジェクトのみ
- 「📋 CSV指定のみ」— 自動抽出を除外し、CSVで手動指定したプロジェクトのみ

**テキストフィルタ:** 各列ヘッダー直下のテキスト入力欄に文字を入力すると、部分一致で行を絞り込みます。複数列のフィルタはAND条件で適用されます
- **ソート:** 列ヘッダーをクリックすると、昇順→降順→解除の3段階でソートが切り替わります
- **ソートインジケーター:** ソート中の列ヘッダーに▲（昇順）/▼（降順）が表示されます
- **数値ソート:** チケット数・課題・Q/A・サポート・成果物の列は数値として比較ソートされます
- **キーボード操作:** Tab移動、Enter確定に対応しています

## Skill構造

他者にこのSkillを提供する際は、以下のファイル・ディレクトリ一式を渡してください。

```
redmine-api/
├── SKILL.md                            # メイン指示ファイル（Kiroが読み込む）
├── README.md                           # このファイル（使い方・セットアップ手順）
├── scripts/
│   ├── redmine_tool.py                 # チケット・プロジェクト操作ツール
│   ├── dashboard_report.py             # ダッシュボードHTML生成
│   ├── test_dashboard.py               # テスト（2プロジェクト）
│   ├── test_dashboard_20prj.py         # テスト（20プロジェクト）
│   └── test_dashboard_no_rpm.py        # テスト（rpm.csvなし）
├── references/
│   └── REFERENCE.md                    # ID一覧・フィルタ・エラー対処・期限リスク仕様
├── assets/
│   ├── projects_sample.csv             # プロジェクト一覧CSVサンプル
│   └── rpm_sample.csv                  # rpm.csv（補助データ）サンプル
└── cache/                              # APIキャッシュ（自動生成、.gitignore対象）
```

加えて、以下のファイルもワークスペースに配置が必要です：

```
（ワークスペースルート）
├── .env.example                        # 環境変数テンプレート
├── .kiroignore                         # Kiroからの秘密情報保護
├── .gitignore                          # Git除外設定
└── .kiro/
    ├── hooks/
    │   └── redmine-dashboard.kiro.hook # ワンクリック実行用hook
    └── steering/
        └── redmine-project-phases.md   # プロジェクトフェーズ定義（ステアリング）
```

## 動作要件

- Python 3.6以上（標準ライブラリのみ使用、外部パッケージ不要）
- Redmine 4.x / 5.x（REST APIが有効であること）
- Kiro IDE（`inclusion: manual` で手動読み込み）

## セットアップ

### 1. Skillの配置

ワークスペースに配置する場合：
```
.kiro/skills/redmine-api/
```

グローバル（全ワークスペース共通）に配置する場合：
```
~/.kiro/skills/redmine-api/
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、実際の値を記入します。

```bash
cp .env.example .env
```

`.env` の内容：
```
REDMINE_URL=https://redmine.example.com
REDMINE_API_KEY=your-api-key-here
```

> RedmineのAPIキーは、Redmineにログイン後「個人設定」→「APIアクセスキー」から取得できます。

### 3. 環境変数の読み込み

スクリプトは起動時にワークスペースルートの `.env` ファイルを自動読み込みします。手動で `source .env` を実行する必要はありません。

> 既に環境変数がセットされている場合は `.env` の値で上書きしません。環境変数を優先したい場合は事前に `export` してください。

### 4. セキュリティ設定（推奨）

`.kiroignore`:
```
.env
.env.*
!.env.example
```

`.gitignore`:
```
.env
.env.*
!.env.example
```

Kiroの設定（`Ctrl+,`）で `kiroAgent.agentIgnoreFiles` に `.kiroignore` を追加します。

これにより：
- Kiroが `.env` を物理的に読めなくなる（`.kiroignore`）
- `.env` がGitリポジトリに入らない（`.gitignore`）
- `.env.example`（テンプレート）は引き続きアクセス可能

### 5. 動作確認

```bash
python .kiro/skills/redmine-api/scripts/redmine_tool.py projects
```

プロジェクト一覧が表示されれば設定完了です。

## Kiroでの使い方

チャットで `#redmine-api` を入力してSkillを読み込み、自然言語で指示します。

```
#redmine-api 自分に割り当てられたチケットを見せて
```

```
#redmine-api プロジェクト一覧を表示して
```

```
#redmine-api チケット#123のステータスを解決にして、コメントに「対応完了」と追加して
```

```
#redmine-api ダッシュボードを生成して（CSVファイル: projects.csv）
```

## ダッシュボードの使い方

### CSVファイルの準備

```csv
project_identifier,redmine_identifier,ai_flag
GJ25500801,gj25500801_-2026,1
AH26501601,,1
ER25500501,,0
```

- `project_identifier`: rpm.csvの子案件No（必須）
- `redmine_identifier`: Redmineの識別子を直接指定したい場合に記入（任意）。空欄の場合はカスタムフィールド（子案件番号）から自動解決
- `ai_flag`: AI考察を有効にする場合は `1`（省略可、省略時はAI考察なし）

#### 識別子の解決ロジック

`project_identifier`（子案件番号）はRedmineのidentifier（識別子）とは異なります。スクリプトは起動時にRedmineの全プロジェクトを取得し、カスタムフィールド「子案件番号」（id=233）→ identifier のマップを自動構築します。

解決の優先順位：
1. CSVの `redmine_identifier` 列に値がある → そのまま使用
2. 自動構築されたマップに子案件番号がある → マップから解決（トップレベルプロジェクトを優先）
3. どちらもない → スキップ（警告を出力）

1つの子案件番号に複数のRedmineプロジェクトが紐づく場合、`parent` フィールドを持たないトップレベルのプロジェクトが自動的に選択されます。意図と異なる場合は `redmine_identifier` 列で直接指定してください。

> 識別子マップの構築には約20回のAPIコール（全プロジェクト取得）が発生します。

### コマンドラインから実行

```bash
# 基本（rpm.csvなし）
python scripts/dashboard_report.py projects.csv -o dashboard.html

# プロジェクト補助データ付き
python scripts/dashboard_report.py projects.csv --rpm rpm.csv -o dashboard.html
```

### プロジェクト補助データ（rpm.csv）

プロジェクトの管理情報を補助データとして付与できます。`--rpm` オプションで指定します。省略可能で、なくても動作します。

rpm.csvフォーマット（ヘッダー行あり）:
```csv
本部,部,案件No,子案件No,子案件名,影響度区分,重要案件区分,新領域案件,案件種類,工程,コスト(工数),状況,進捗状況,コスト(工数)割合,進捗率,開始日,完了予定日,完了実績日,着手年月,サービスイン予定日,進捗更新日
```

- `子案件No` がプロジェクトCSVの `project_identifier` と一致するレコードが紐づきます
- 1つの子案件Noに対して工程ごとに複数レコードが存在します
- rpm.csv読み込み時に以下の条件で子案件Noを事前フィルタし、不要なプロジェクトのAPI取得を省略します：
  - 作業日（今日） < サービスイン予定日（まだサービスインしていない）
  - 作業日（今日） ≧ 着手年月（既に着手している）
  - 両方を満たす子案件Noの全工程レコードのみ読み込み、それ以外は除外
- 現在日付が開始日〜完了予定日の間にある工程が「現在工程」として自動採用されます
- 該当する工程がない場合は最初のレコードが採用されます
- 全てのカラムが埋まっている必要はありません（空欄は「-」表示）
- rpm.csvに該当プロジェクトがなくても、ダッシュボードは正常に動作します

配置場所:
```
.kiro/skills/redmine-api/assets/
├── projects_sample.csv   # プロジェクト一覧サンプル（git管理）
├── rpm_sample.csv         # rpm.csvサンプル（git管理）
└── rpm.csv                # 実データ（.gitignoreで除外、ユーザーが配置）
```

セットアップ:
```bash
cp .kiro/skills/redmine-api/assets/rpm_sample.csv .kiro/skills/redmine-api/assets/rpm.csv
```
コピー後、rpm.csvに実際のプロジェクト情報を記入してください。rpm.csvは`.gitignore`で除外されるため、リポジトリには入りません。
一覧テーブルに表示される主要項目:
- 影響度区分、重要案件区分、新領域案件、工程、着手年月、サービスイン予定日

詳細ページには、値があるすべての項目がグリッド表示されます。
AI考察のインプットにも、工程・状況・進捗率・影響度・完了予定日・サービスイン予定日が含まれます。

### Kiroから一気通貫で実行

Kiroに「ダッシュボードを生成して」と指示すると、以下が自動で実行されます：

1. Pythonスクリプトを実行してHTMLを生成
2. AIフラグ付きプロジェクト（最大10件）のAI考察を生成
3. 考察テキストをHTMLに挿入
4. 完了報告

AI考察では、チケットの数値データに加えて「進捗報告」トラッカーのプロマネ報告内容もインプットとして使用し、定量・定性の両面から分析します。

### テストの実行

Redmine接続なしでモックデータを使ったテストが可能です。

```bash
# 2プロジェクトのテスト
python scripts/test_dashboard.py

# 20プロジェクトの負荷テスト
python scripts/test_dashboard_20prj.py
```

生成された `test_dashboard.html` / `test_dashboard_20prj.html` をブラウザで開いて確認できます。

## Pythonツール単体での使い方

```bash
# ヘルプ表示
python scripts/redmine_tool.py --help

# チケット一覧（自分の担当）
python scripts/redmine_tool.py issues --assigned-to me

# チケット詳細
python scripts/redmine_tool.py issue 123

# チケット作成
python scripts/redmine_tool.py create --project my-project --subject "題名"

# チケット更新
python scripts/redmine_tool.py update 123 --status 3 --notes "対応完了"

# チケット検索
python scripts/redmine_tool.py search "ログイン"

# プロジェクト一覧 / 詳細 / メンバー / バージョン
python scripts/redmine_tool.py projects
python scripts/redmine_tool.py project my-project
python scripts/redmine_tool.py members my-project
python scripts/redmine_tool.py versions my-project
```

## ワンクリック実行（Agent Hook）

Kiroの Agent Hook を使って、ダッシュボード生成をワンクリックで実行できます。

セットアップ済みの場合、Kiroサイドバーの「Agent Hooks」セクションに「Redmine ダッシュボード生成」が表示されます。クリックするだけで、CSVからのデータ取得 → HTML生成 → AI考察挿入まで一気通貫で実行されます。

hookが未作成の場合は、Kiroに「ダッシュボード生成用のhookを作って」と指示するか、`.kiro/hooks/redmine-dashboard.json` を以下の内容で作成してください：

```json
{
  "name": "Redmine ダッシュボード生成",
  "version": "1.0.0",
  "description": "Redmineのプロジェクトダッシュボード（HTML）を生成します。",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "#redmine-api のダッシュボードレポート生成を実行してください。"
  }
}
```

> hookのプロンプト内のCSVパスは、実際のプロジェクト一覧CSVのパスに変更してください。

## サーバー負荷対策

Redmineサーバーへの負荷を抑えるため、以下の制限とキャッシュ機構を設けています。

| 制限 | 値 | 説明 |
|------|-----|------|
| CSVプロジェクト上限 | 30件 | 31件以上でエラー停止 |
| APIリクエスト間隔 | 0.5秒 | 毎回のHTTPリクエスト後にスリープ |
| AI考察の上限 | 10件 | ai_flag + 期限リスクの合計で先頭10件 |

### APIキャッシュ

プロジェクト構造に関するAPIレスポンスを日付単位でキャッシュし、同日の2回目以降はAPIコールを省略します。

| キャッシュ対象 | 説明 | 削減効果 |
|--------------|------|---------|
| 識別子マップ | 子案件番号 → identifier のマッピング | 約20回のAPIコール |
| ステータスマップ | ステータスID → 名前のマッピング | 1回 |
| サブプロジェクト構造 | プロジェクトごとの全階層サブプロジェクト一覧 | プロジェクトあたり複数回 |

- キャッシュファイルは `.kiro/skills/redmine-api/cache/` に日付付きJSONで保存
- 日付が変わると古いキャッシュは自動削除され、再取得
- チケットデータはキャッシュしない（鮮度が重要なため毎回取得）
- キャッシュディレクトリは `.gitignore` で除外

20プロジェクトの場合、初回は約30秒、同日2回目以降は約15秒程度に短縮されます。

## Redmine側の運用ガイド

### 進捗報告トラッカーの起票のお願い

ダッシュボードの「📋 プロマネ報告」セクションは、Redmineの「進捗報告」トラッカーのチケットから情報を取得しています。この機能を活用するために、各プロジェクトのRedmineにて以下の運用をお願いします。

- 各プロジェクトに「進捗報告」トラッカーのチケットを起票してください
- 週次の進捗状況を、チケットの説明欄またはコメント（注記）に記載してください
- 1プロジェクトに1チケットで運用する場合は、毎週コメントとして追記する形でOKです
- 複数チケットで運用する場合は、最新の更新日のチケットがダッシュボードに表示されます

記載内容の例：
```
【今週の進捗】
・基本設計書の作成が70%まで進捗。来週中に完了見込み。
・テスト計画書は期日超過しており、リソース追加を検討中。

【リスク・課題】
・テスト計画書の遅延がテストフェーズ全体に影響する可能性あり。

【来週の予定】
・基本設計書のレビュー実施
・テスト計画書のリカバリープラン策定
```

> 進捗報告チケットがないプロジェクトでは、プロマネ報告セクションは表示されません。ダッシュボードの他の機能（グラフ・成果物予実など）は影響なく動作します。

## セキュリティについて

| 対策 | 説明 |
|------|------|
| `.kiroignore` | Kiroが `.env` を読めないようブロック |
| `.gitignore` | `.env` がリポジトリに入らない |
| 環境変数参照 | APIキーはシェルの環境変数経由で渡す |
| Skill内禁止事項 | Kiroに対し `.env` の読み取り・APIキーの表示を禁止 |
| `.env.example` | テンプレートのみ共有（実際の値なし） |

> APIキーをチャットに入力しないでください。会話履歴に残る可能性があります。

## デザイン準拠

ダッシュボードHTMLは[デジタル庁デザインシステム v2](https://design.digital.go.jp/dads/)に準拠しています。

- カラー: Blue系プライマリー、ニュートラルグレー階調、セマンティックカラー
- タイポグラフィ: Noto Sans JP、Standard/Denseスタイル
- コントラスト比: テキスト4.5:1以上、非テキスト3:1以上
- 最小フォントサイズ: 14px
- アクセシビリティ: セマンティックHTML、aria-label、キーボード操作対応

## 対応Redmine API

- [Issues](https://www.redmine.org/projects/redmine/wiki/Rest_Issues) — チケットのCRUD
- [Projects](https://www.redmine.org/projects/redmine/wiki/Rest_Projects) — プロジェクト情報（サブプロジェクト含む）
- [Memberships](https://www.redmine.org/projects/redmine/wiki/Rest_Memberships) — メンバー管理
- [Versions](https://www.redmine.org/projects/redmine/wiki/Rest_Versions) — バージョン管理
- [Search](https://www.redmine.org/projects/redmine/wiki/Rest_Search) — 全文検索

## ライセンス

MIT
