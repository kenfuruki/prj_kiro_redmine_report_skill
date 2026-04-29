# 要件定義書: ダッシュボード機能拡張

## はじめに

Redmineダッシュボードレポート（`dashboard_report.py`）に対する3つの機能拡張要件を定義する。rpm.csvからのプロジェクト自動抽出、期限リスク検知、および一覧テーブルのフィルタ・ソート機能を追加し、ダッシュボードの実用性と視認性を向上させる。

## 用語集

- **Dashboard_Report**: `dashboard_report.py` が生成するHTMLダッシュボードレポート。一覧ページとプロジェクト別詳細ページで構成される
- **Projects_CSV**: ダッシュボード対象プロジェクトを指定するCSVファイル（`project_identifier,ai_flag` 形式）
- **RPM_CSV**: プロジェクト補助データCSV。`子案件No`（= project_identifier）をキーとし、サービスイン予定日・影響度区分等の管理情報を含む
- **Auto_Extract_Engine**: RPM_CSVからサービスイン予定日と課題・QAチケット総数に基づきプロジェクトを自動抽出するロジック
- **Checkpoint**: ダッシュボードの4定点（3週間前・2週間前・1週間前・現在）の各時点
- **Overdue_Count**: 期限日（`due_date`）が操作日より過去であり、かつステータスが未完了（解決・終了・却下以外）のチケット数
- **Blank_Due_Count**: 期限日（`due_date`）が未設定（空欄）であり、かつステータスが未完了のチケット数
- **Risk_Score**: 各Checkpointにおける Overdue_Count + Blank_Due_Count の合計値
- **Deadline_Risk_Flag**: 4定点のRisk_Scoreが上昇傾向にあるプロジェクトに付与されるフラグ
- **Trend_Analysis**: 4定点のRisk_Scoreの推移を分析し、上昇傾向を判定するロジック
- **Project_List_Table**: 一覧ページに表示されるプロジェクト一覧テーブル（HTML `<table>` 要素）
- **Filter_Engine**: Project_List_Tableの各列に対してテキスト入力またはドロップダウンで行を絞り込むJavaScript機能
- **Sort_Engine**: Project_List_Tableの列ヘッダークリックで行を昇順・降順に並べ替えるJavaScript機能
- **Target_Tracker**: ダッシュボードの集計対象トラッカー（課題、Q/A、サポート、成果物、進捗報告）
- **Issue_Tracker**: 「課題」トラッカーのチケット
- **QA_Tracker**: 「Q/A」トラッカーのチケット

## 要件

### 要件1: RPM_CSVからのプロジェクト自動抽出

**ユーザーストーリー:** プロジェクト管理者として、RPM_CSVが指定された場合にサービスイン予定日が近いプロジェクトを自動的にダッシュボードに追加したい。これにより、CSVに手動で記載していないプロジェクトも漏れなく監視できるようにする。

#### 受入条件

1. WHEN RPM_CSVが `--rpm` オプションで指定されている場合、THE Auto_Extract_Engine SHALL RPM_CSV内の全レコードからサービスイン予定日が操作日以降のレコードを抽出する
2. WHEN サービスイン予定日が操作日以降のレコードが抽出された場合、THE Auto_Extract_Engine SHALL 各レコードの `子案件No` に対応するプロジェクトのIssue_TrackerチケットとQA_Trackerチケットの総数をRedmine APIから取得する
3. WHEN チケット総数が取得された場合、THE Auto_Extract_Engine SHALL Issue_TrackerチケットとQA_Trackerチケットの合計数が多い順に上位5件を選出する
4. WHEN 上位5件が選出された場合、THE Auto_Extract_Engine SHALL Projects_CSVに既に記載されているプロジェクトを除外した上で、残りのプロジェクトをダッシュボード対象に追加する
5. WHEN 自動抽出されたプロジェクトがダッシュボードに追加される場合、THE Dashboard_Report SHALL 自動抽出されたプロジェクトを Projects_CSV記載のプロジェクトの後に表示する
6. WHEN 自動抽出されたプロジェクトがダッシュボードに追加される場合、THE Dashboard_Report SHALL 自動抽出されたプロジェクトの行に「自動抽出」であることを示すバッジを表示する
7. WHEN 自動抽出によりプロジェクト総数がMAX_PROJECTS（30件）を超える場合、THE Auto_Extract_Engine SHALL MAX_PROJECTSを超えない範囲で自動抽出件数を削減する
8. WHEN RPM_CSVが指定されていない場合、THE Auto_Extract_Engine SHALL 自動抽出処理を実行せず、従来通りProjects_CSVのみでダッシュボードを生成する
9. WHEN RPM_CSVのレコードにサービスイン予定日が空欄のレコードが存在する場合、THE Auto_Extract_Engine SHALL そのレコードを自動抽出の対象外とする
10. WHEN 自動抽出の対象となるプロジェクトがRedmine上に存在しない場合、THE Auto_Extract_Engine SHALL そのプロジェクトをスキップし、標準エラー出力に警告メッセージを出力する
11. WHEN 自動抽出処理が完了した場合、THE Auto_Extract_Engine SHALL 自動抽出されたプロジェクト数と各プロジェクトのidentifierを標準エラー出力にログ出力する
12. THE Auto_Extract_Engine SHALL 自動抽出されたプロジェクトの `ai_flag` を無効（0）として扱う

### 要件2: 期限リスク検知

**ユーザーストーリー:** プロジェクト管理者として、課題チケットとQAチケットの期限超過・期限未設定の推移を4定点で把握し、上昇傾向にあるプロジェクトを一目で識別したい。これにより、期限管理に問題があるプロジェクトへの早期介入が可能になる。

#### 受入条件

1. WHEN Dashboard_Reportがデータを集計する際、THE Dashboard_Report SHALL 各Checkpointにおける各プロジェクトのIssue_TrackerおよびQA_TrackerのOverdue_CountとBlank_Due_Countを算出する
2. WHEN Overdue_CountとBlank_Due_Countが算出された場合、THE Dashboard_Report SHALL 各CheckpointのRisk_Score（Overdue_Count + Blank_Due_Count）を計算する
3. WHEN 4定点のRisk_Scoreが算出された場合、THE Trend_Analysis SHALL 直近3区間（3週間前→2週間前、2週間前→1週間前、1週間前→現在）のうち2区間以上でRisk_Scoreが増加している場合を「上昇傾向」と判定する
4. WHEN プロジェクトが「上昇傾向」と判定された場合、THE Dashboard_Report SHALL そのプロジェクトにDeadline_Risk_Flagを付与する
5. WHEN Deadline_Risk_Flagが付与されたプロジェクトがProject_List_Tableに表示される場合、THE Dashboard_Report SHALL プロジェクト行に「⚠ 期限リスク」バッジを視覚的に目立つ形で表示する
6. WHEN Deadline_Risk_Flagのバッジが表示される場合、THE Dashboard_Report SHALL バッジのツールチップに4定点のRisk_Score推移（例: 「3→5→4→7」）を表示する
7. WHEN プロジェクトの4定点すべてでRisk_Scoreが0の場合、THE Trend_Analysis SHALL そのプロジェクトを「上昇傾向」と判定しない
8. WHEN Checkpointにおいてプロジェクトのチケットデータが存在しない場合、THE Dashboard_Report SHALL そのCheckpointのRisk_Scoreを0として扱う
9. WHEN プロジェクト詳細ページが表示される場合、THE Dashboard_Report SHALL 4定点のRisk_Score推移を数値テーブルとして詳細ページに表示する
10. THE Dashboard_Report SHALL Overdue_Countの算出において、ステータスが「解決」「終了」「却下」のチケットを除外する
11. THE Dashboard_Report SHALL Blank_Due_Countの算出において、ステータスが「解決」「終了」「却下」のチケットを除外する
12. WHEN Deadline_Risk_Flagが付与されたプロジェクトがある場合、THE Dashboard_Report SHALL そのプロジェクトをAI考察の対象に含める（CSVの `ai_flag` の値に関わらず、Deadline_Risk_Flagが付与されたプロジェクトはAI考察プレースホルダーを生成する）
13. WHEN Deadline_Risk_FlagによりAI考察対象となるプロジェクトがある場合、THE Dashboard_Report SHALL AI考察の上限10件の中にCSVの `ai_flag` 指定分とDeadline_Risk_Flag分を合算してカウントする
14. WHEN AI考察が生成される際にDeadline_Risk_Flagが付与されたプロジェクトの場合、THE Dashboard_Report SHALL AI考察のdata属性に4定点のRisk_Score推移を `data-risk-scores` として埋め込む

### 要件3: 一覧テーブルのフィルタ・ソート機能

**ユーザーストーリー:** プロジェクト管理者として、一覧テーブルの各列でフィルタリングやソートを行いたい。これにより、多数のプロジェクトから特定の条件に合致するプロジェクトを素早く見つけられるようにする。

#### 受入条件

1. WHEN Project_List_Tableが表示される場合、THE Filter_Engine SHALL 各列のヘッダー直下にフィルタ入力欄を表示する
2. WHEN ユーザーがフィルタ入力欄にテキストを入力した場合、THE Filter_Engine SHALL 入力文字列を含む行のみを表示し、該当しない行を非表示にする
3. WHEN 複数列のフィルタが同時に入力されている場合、THE Filter_Engine SHALL すべてのフィルタ条件をAND条件で適用する
4. WHEN フィルタ入力欄が空にされた場合、THE Filter_Engine SHALL その列のフィルタ条件を解除し、他の列のフィルタ条件のみで行を絞り込む
5. WHEN ユーザーが列ヘッダーをクリックした場合、THE Sort_Engine SHALL その列の値で行を昇順にソートする
6. WHEN 既に昇順でソートされている列のヘッダーが再度クリックされた場合、THE Sort_Engine SHALL その列の値で行を降順にソートする
7. WHEN 降順でソートされている列のヘッダーが再度クリックされた場合、THE Sort_Engine SHALL ソートを解除し、元の表示順に戻す
8. WHEN ソートが適用されている場合、THE Sort_Engine SHALL ソート方向を示すインジケーター（▲ 昇順 / ▼ 降順）を列ヘッダーに表示する
9. WHEN 数値列（チケット数、課題、Q/A、サポート、成果物）がソートされる場合、THE Sort_Engine SHALL 数値として比較しソートする（文字列比較ではなく数値比較）
10. WHEN Deadline_Risk_Flagの列がフィルタされる場合、THE Filter_Engine SHALL 「リスク」「あり」等のテキスト入力でDeadline_Risk_Flagが付与されたプロジェクトを絞り込めるようにする
11. WHEN フィルタまたはソートが適用されている場合、THE Dashboard_Report SHALL プロジェクト行のクリックによる詳細ページ遷移機能を維持する
12. THE Filter_Engine SHALL フィルタ処理をインライン JavaScript で実装し、外部ライブラリに依存しない
13. THE Sort_Engine SHALL ソート処理をインライン JavaScript で実装し、外部ライブラリに依存しない
14. THE Filter_Engine SHALL フィルタ入力欄にデジタル庁デザインシステム v2 準拠のスタイルを適用する
15. WHEN フィルタ入力欄にフォーカスが当たった場合、THE Filter_Engine SHALL キーボード操作（Tab移動、Enter確定）に対応する
16. THE Dashboard_Report SHALL Project_List_Tableに「期限リスク」列を追加し、Deadline_Risk_Flagの有無を表示する

### 要件4: READMEへの機能説明追記

**ユーザーストーリー:** Skillの利用者として、追加された機能（自動抽出・期限リスク検知・フィルタ・ソート）の使い方をREADMEで確認したい。これにより、新機能を迷わず活用できるようにする。

#### 受入条件

1. WHEN 要件1〜3の実装が完了した場合、THE README.md SHALL プロジェクト自動抽出機能の説明（動作条件、抽出ロジック、自動抽出バッジの意味）を記載する
2. WHEN 要件1〜3の実装が完了した場合、THE README.md SHALL 期限リスク検知機能の説明（判定ロジック、「⚠ 期限リスク」バッジの意味、詳細ページでのRisk_Score表示）を記載する
3. WHEN 要件1〜3の実装が完了した場合、THE README.md SHALL 一覧テーブルのフィルタ・ソート機能の操作方法（フィルタ入力、ヘッダークリックによるソート、ソートインジケーター）を記載する
4. THE README.md SHALL 追加機能の説明をダッシュボードセクション内に記載し、既存の説明と整合性を保つ
5. THE REFERENCE.md SHALL 期限リスク検知のRisk_Score算出ロジックと判定基準を記載する
