# 実装計画: ダッシュボード機能拡張

## 概要

Redmineダッシュボードレポート（`dashboard_report.py`）に対して、(1) RPM_CSVからのプロジェクト自動抽出エンジン、(2) 期限リスク検知（Risk_Score算出 + Deadline_Risk_Flag）、(3) AI考察対象決定ロジックの拡張、(4) 一覧テーブルのフィルタ・ソートエンジン、(5) HTML生成の更新、(6) プロパティベーステスト、(7) 既存テスト更新、(8) ドキュメント更新を段階的に実装する。

## タスク

- [x] 1. 自動抽出エンジンの実装
  - [x] 1.1 `fetch_issue_qa_count()` 関数を `dashboard_report.py` に追加する
    - 指定プロジェクトの課題トラッカー + Q/Aトラッカーのオープンチケット総数をRedmine APIから取得する
    - プロジェクトが存在しない場合は `-1` を返す
    - 既存の `api_get()` を利用してAPIリクエストを送信する
    - _要件: 1.2, 1.10_

  - [x] 1.2 `auto_extract_projects()` 関数を `dashboard_report.py` に追加する
    - `rpm_data` からサービスイン予定日が操作日以降のレコードを抽出する
    - サービスイン予定日が空欄のレコードを除外する
    - `existing_pids` に含まれるプロジェクトを除外する
    - 各プロジェクトの `fetch_issue_qa_count()` を呼び出し、チケット総数の降順で上位5件を選出する
    - `MAX_PROJECTS` を超えない範囲で件数を調整する
    - 不正な日付形式のレコードはスキップし、stderrに警告を出力する
    - Redmine上に存在しないプロジェクト（`fetch_issue_qa_count()` が `-1`）はスキップする
    - 自動抽出結果をstderrにログ出力する
    - テスト用の `today` パラメータ（操作日注入）をサポートする
    - _要件: 1.1, 1.3, 1.4, 1.7, 1.9, 1.10, 1.11_

  - [x] 1.3 `main()` 関数に自動抽出処理の呼び出しを統合する
    - `--rpm` オプション指定時のみ `auto_extract_projects()` を呼び出す
    - 自動抽出されたプロジェクトIDを `project_ids` リストの末尾に追加する
    - 自動抽出プロジェクトの `ai_flag` を `False` に設定する
    - 自動抽出プロジェクトのチケット取得・集計処理を既存フローに統合する
    - `auto_extracted` セット（自動抽出されたプロジェクトIDの集合）を作成し、`generate_html()` に渡す
    - _要件: 1.4, 1.5, 1.8, 1.12_

- [x] 2. Risk_Score算出と期限リスク検知の実装
  - [x] 2.1 `CLOSED_STATUSES` 定数と補助関数を `dashboard_report.py` に追加する
    - `CLOSED_STATUSES = {"解決", "終了", "却下"}` を定義する
    - `_is_overdue_at(issue, checkpoint_dt, status_map)` 関数を実装する（指定時点で期限超過かつ未完了か判定）
    - `_is_blank_due_at(issue, checkpoint_dt, status_map)` 関数を実装する（指定時点で期限未設定かつ未完了か判定）
    - 既存の `get_status_at()` と `resolve_status_name()` を利用してステータスを復元する
    - _要件: 2.1, 2.10, 2.11_

  - [x] 2.2 `compute_risk_scores()` 関数を `dashboard_report.py` に追加する
    - 各プロジェクト・各Checkpointの Overdue_Count + Blank_Due_Count を算出する
    - 対象トラッカーは「課題」「Q/A」のみ
    - チケットデータが存在しないCheckpointは Risk_Score = 0 とする
    - 戻り値: `{project_id: [risk_score_3w, risk_score_2w, risk_score_1w, risk_score_now]}`
    - _要件: 2.1, 2.2, 2.8_

  - [x] 2.3 `detect_deadline_risk()` 関数を `dashboard_report.py` に追加する
    - 3区間（3w→2w, 2w→1w, 1w→now）のうち2区間以上でRisk_Scoreが増加 → `True`
    - 4定点すべてRisk_Score=0 → `False`
    - 戻り値: `{project_id: True/False}`
    - _要件: 2.3, 2.4, 2.7_

  - [x] 2.4 `main()` 関数にRisk_Score算出・トレンド判定の呼び出しを統合する
    - `aggregate_data()` の後に `compute_risk_scores()` を呼び出す
    - `compute_risk_scores()` の結果を `detect_deadline_risk()` に渡す
    - `risk_scores` と `deadline_risk` を `generate_html()` に渡す
    - _要件: 2.1, 2.2, 2.3, 2.4_

- [x] 3. AI考察対象決定ロジックの拡張
  - [x] 3.1 `resolve_ai_targets()` 関数を `dashboard_report.py` に追加する
    - `ai_flag=True` のプロジェクトを `project_ids` の順序で優先的に選出する
    - 次に `Deadline_Risk_Flag=True` のプロジェクトを `project_ids` の順序で追加する
    - 重複を除外し、合計 `ai_max`（デフォルト10）件まで
    - 戻り値: AI考察対象のプロジェクトIDセット
    - _要件: 2.12, 2.13_

  - [x] 3.2 `AI_MAX` を 5 → 10 に変更し、`main()` で `resolve_ai_targets()` を呼び出す
    - `generate_html()` 内の `AI_MAX = 5` を `AI_MAX = 10` に変更する
    - `main()` で `resolve_ai_targets()` を呼び出し、結果を `ai_targets` として `generate_html()` に渡す
    - `generate_html()` 内のAI考察プレースホルダー生成ロジックを `ai_targets` セットベースに変更する
    - _要件: 2.12, 2.13_

- [x] 4. チェックポイント — テスト実行と動作確認
  - すべてのテストが通ることを確認し、疑問点があればユーザーに質問する。

- [x] 5. フィルタ・ソートJavaScriptエンジンの実装
  - [x] 5.1 `_render_filter_sort_js()` 関数を `dashboard_report.py` に追加する
    - テーブルID `project-list-table` を対象とするインラインJavaScriptを生成する
    - フィルタ処理: 各列ヘッダー直下の `<input class="col-filter">` による部分一致フィルタ（`indexOf` 使用、正規表現不使用）
    - 複数列のAND条件フィルタ
    - ソート処理: 列ヘッダークリックによる3段階トグル（none → asc → desc → none）
    - 数値列（チケット数、課題、Q/A、サポート、成果物）は数値比較ソート
    - テキスト列は `localeCompare` による文字列比較ソート
    - ソートインジケーター（▲/▼）表示
    - 元の順序を `data-original-index` で保持し、ソート解除時に復元する
    - 空文字はソート時に最後尾に配置する
    - フィルタ入力欄にデジタル庁デザインシステムv2準拠のスタイルを適用する
    - キーボード操作（Tab移動、Enter確定）に対応する
    - 外部ライブラリに依存しない
    - _要件: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15_

- [x] 6. HTML生成の更新（`generate_html()` の変更）
  - [x] 6.1 一覧テーブルの構造を更新する
    - テーブルに `id="project-list-table"` を付与する
    - 「期限リスク」列をAI列の前に追加する
    - 各行に `data-original-index` 属性を付与する
    - フィルタ入力行（`<tr>` with `<input>` elements）をヘッダー直下に追加する
    - `_render_filter_sort_js()` の出力を `<script>` タグで埋め込む
    - _要件: 3.1, 3.16_

  - [x] 6.2 自動抽出バッジと期限リスクバッジを表示する
    - `auto_extracted` セットに含まれるプロジェクトの行に「🔍 自動抽出」バッジを表示する
    - `deadline_risk` が `True` のプロジェクトの行に「⚠ 期限リスク」バッジを表示する
    - 期限リスクバッジのツールチップに4定点のRisk_Score推移（例: 「3→5→4→7」）を表示する
    - 「期限リスク」列にDeadline_Risk_Flagの有無を表示する
    - _要件: 1.6, 2.5, 2.6, 3.16_

  - [x] 6.3 `generate_html()` の引数を拡張し、新規パラメータを受け取る
    - `auto_extracted=None`（set[str]）、`risk_scores=None`（dict[str, list[int]]）、`deadline_risk=None`（dict[str, bool]）、`ai_targets=None`（set[str]）を追加する
    - AI考察プレースホルダー生成を `ai_targets` セットベースに変更する
    - Deadline_Risk_FlagプロジェクトのAI考察プレースホルダーに `data-risk-scores` 属性を追加する
    - _要件: 2.12, 2.13, 2.14_

  - [x] 6.4 `_render_risk_score_table()` 関数を追加し、詳細ページにRisk_Score推移テーブルを表示する
    - 4定点のRisk_Score推移を数値テーブルとして詳細ページに表示する
    - `generate_html()` の詳細ページ生成部分から呼び出す
    - _要件: 2.9_

- [x] 7. チェックポイント — テスト実行と動作確認
  - すべてのテストが通ることを確認し、疑問点があればユーザーに質問する。

- [ ] 8. プロパティベーステスト（Hypothesis）の作成
  - [ ]* 8.1 `test_properties.py` を新規作成し、プロパティ1（RPMフィルタリングの正確性）のテストを実装する
    - **プロパティ1: RPMフィルタリングの正確性**
    - 任意のRPM_CSVデータセットと操作日に対して、`auto_extract_projects` が返すプロジェクトIDリストに含まれるすべてのプロジェクトは、サービスイン予定日が操作日以降であり、かつ空欄でないことを検証する
    - `fetch_issue_qa_count` をモックし、純粋なフィルタリングロジックのみをテストする
    - **検証対象: 要件 1.1, 1.9**

  - [ ]* 8.2 プロパティ2（自動抽出の選出と除外）のテストを実装する
    - **プロパティ2: 自動抽出の選出と除外**
    - 任意のCSVプロジェクトリストとRPM候補リストに対して、返却リストが (a) CSVプロジェクトリストに含まれるプロジェクトを一切含まず、(b) チケット総数の降順で並んでおり、(c) 最大5件以下であることを検証する
    - **検証対象: 要件 1.3, 1.4**

  - [ ]* 8.3 プロパティ3（自動抽出のMAX_PROJECTS制限）のテストを実装する
    - **プロパティ3: 自動抽出のMAX_PROJECTS制限**
    - 任意のCSVプロジェクト数（1〜30）と自動抽出候補数（0〜10）に対して、合計がMAX_PROJECTS（30）を超えないことを検証する
    - **検証対象: 要件 1.7**

  - [ ]* 8.4 プロパティ4（自動抽出プロジェクトのai_flag無効）のテストを実装する
    - **プロパティ4: 自動抽出プロジェクトのai_flag無効**
    - 任意の自動抽出されたプロジェクトに対して、`ai_flag` が常に `False` であることを検証する
    - **検証対象: 要件 1.12**

  - [ ]* 8.5 プロパティ5（Risk_Score算出の正確性）のテストを実装する
    - **プロパティ5: Risk_Score算出の正確性**
    - 任意のチケットセットとCheckpoint日時に対して、Risk_Scoreが「未完了かつ（期限超過 or 期限未設定）のチケット数」と等しいことを検証する
    - 完了ステータス（解決・終了・却下）のチケットがRisk_Scoreに含まれないことを検証する
    - **検証対象: 要件 2.1, 2.2, 2.10, 2.11**

  - [ ]* 8.6 プロパティ6（上昇傾向判定の正確性）のテストを実装する
    - **プロパティ6: 上昇傾向判定の正確性**
    - 任意の4つのRisk_Score値に対して、(a) 3区間中2区間以上で増加している場合のみ `True`、(b) 全て0の場合は `False` を返すことを検証する
    - **検証対象: 要件 2.3, 2.4, 2.7**

  - [ ]* 8.7 プロパティ7（AI考察対象決定と上限）のテストを実装する
    - **プロパティ7: AI考察対象決定と上限**
    - 任意のプロジェクトリスト、ai_flag、Deadline_Risk_Flagに対して、(a) ai_flag=True または Deadline_Risk_Flag=True のプロジェクトのみを含み、(b) 合計10件以下であり、(c) ai_flag=True が優先されることを検証する
    - **検証対象: 要件 2.12, 2.13**

- [x] 9. 既存テストの更新（モックデータ拡張）
  - [x] 9.1 `test_dashboard.py` にモックデータと検証を追加する
    - 自動抽出バッジ（「🔍 自動抽出」）の表示確認
    - 期限リスクバッジ（「⚠ 期限リスク」）の表示確認
    - Risk_Scoreテーブルの表示確認
    - フィルタ入力欄（`<input class="col-filter">`）の存在確認
    - ソートインジケーターの存在確認
    - 「期限リスク」列の存在確認
    - `data-risk-scores` 属性の存在確認
    - `generate_html()` の新規引数（`auto_extracted`, `risk_scores`, `deadline_risk`, `ai_targets`）を渡すようにモックデータを更新する
    - _要件: 1.6, 2.5, 2.6, 2.9, 2.14, 3.1, 3.8, 3.16_

  - [x] 9.2 `test_dashboard_20prj.py` にモックデータと検証を追加する
    - 20プロジェクト規模で `auto_extracted`, `risk_scores`, `deadline_risk`, `ai_targets` のモックデータを生成する
    - `generate_html()` の新規引数を渡すように更新する
    - 生成されたHTMLに新機能（フィルタ入力欄、期限リスク列、自動抽出バッジ）が含まれることを確認する
    - _要件: 1.6, 2.5, 3.1, 3.16_

- [x] 10. チェックポイント — 全テスト実行と動作確認
  - すべてのテストが通ることを確認し、疑問点があればユーザーに質問する。

- [x] 11. ドキュメント更新
  - [x] 11.1 `README.md` にダッシュボード新機能の説明を追記する
    - プロジェクト自動抽出機能の説明（動作条件、抽出ロジック、自動抽出バッジの意味）
    - 期限リスク検知機能の説明（判定ロジック、「⚠ 期限リスク」バッジの意味、詳細ページでのRisk_Score表示）
    - フィルタ・ソート機能の操作方法（フィルタ入力、ヘッダークリックによるソート、ソートインジケーター）
    - 「制限事項」テーブルの「AI考察の上限」を5件→10件に更新する
    - _要件: 4.1, 4.2, 4.3, 4.4_

  - [x] 11.2 `REFERENCE.md` に期限リスク検知のリファレンスを追記する
    - Risk_Score算出ロジック（Overdue_Count + Blank_Due_Count）の説明
    - 完了ステータスの除外条件
    - 上昇傾向の判定基準（3区間中2区間以上増加）
    - Deadline_Risk_Flagの意味と表示
    - _要件: 4.5_

  - [x] 11.3 `SKILL.md` のAI考察上限を更新する
    - 「上限: 最大5件まで」を「上限: 最大10件まで」に更新する
    - _要件: 2.13_

  - [x] 11.4 `.kiro/hooks/redmine-dashboard.kiro.hook` のプロンプトを更新する
    - AI考察の最大件数を「最大5件」→「最大10件」に変更する
    - _要件: 2.13_

- [x] 12. 最終チェックポイント — 全テスト実行と最終確認
  - すべてのテストが通ることを確認し、疑問点があればユーザーに質問する。

## 備考

- `*` マーク付きのタスクはオプションであり、スキップ可能です
- 各タスクは具体的な要件番号を参照しており、トレーサビリティを確保しています
- チェックポイントでは段階的な検証を行い、問題の早期発見を目指します
- プロパティベーステストはユニバーサルな正確性プロパティを検証し、ユニットテストは具体的な例示とエッジケースを検証します
- `dashboard_report.py` 本体はPython標準ライブラリのみで動作します。Hypothesisはテスト実行時のみ必要です
