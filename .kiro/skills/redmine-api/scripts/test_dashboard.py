#!/usr/bin/env python3
"""
ダッシュボードレポートのテスト（モックデータ使用）
Redmine APIへの接続なしで、集計→HTML生成の動作を検証する。
"""

import sys
import os
from datetime import datetime, timedelta, timezone

# dashboard_report.py を同じディレクトリからインポート
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard_report import (
    JST, TARGET_TRACKERS, get_checkpoints,
    aggregate_data, generate_html,
    _render_tracker_table, _render_deliverable_table,
    compute_risk_scores, detect_deadline_risk, resolve_ai_targets,
)


def make_issue(issue_id, tracker, subject, status_id, status_name,
               done_ratio=0, due_date=None, project_id="prj-alpha",
               created_days_ago=30, journals=None):
    """モックチケットを生成する"""
    now = datetime.now(JST)
    created = now - timedelta(days=created_days_ago)
    return {
        "id": issue_id,
        "tracker": {"id": 1, "name": tracker},
        "subject": subject,
        "status": {"id": status_id, "name": status_name},
        "priority": {"id": 2, "name": "通常"},
        "assigned_to": {"id": 1, "name": "テスト太郎"},
        "author": {"id": 1, "name": "テスト太郎"},
        "done_ratio": done_ratio,
        "due_date": due_date,
        "created_on": created.isoformat(),
        "updated_on": now.isoformat(),
        "journals": journals or [],
    }


def make_journal(days_ago, status_old=None, status_new=None, ratio_old=None, ratio_new=None):
    """モックジャーナル（変更履歴）を生成する"""
    now = datetime.now(JST)
    dt = now - timedelta(days=days_ago)
    details = []
    if status_old is not None and status_new is not None:
        details.append({
            "property": "attr",
            "name": "status_id",
            "old_value": str(status_old),
            "new_value": str(status_new),
        })
    if ratio_old is not None and ratio_new is not None:
        details.append({
            "property": "attr",
            "name": "done_ratio",
            "old_value": str(ratio_old),
            "new_value": str(ratio_new),
        })
    return {
        "id": 1000 + days_ago,
        "user": {"id": 1, "name": "テスト太郎"},
        "notes": "",
        "created_on": dt.isoformat(),
        "details": details,
    }


def build_mock_data():
    """テスト用のモックデータを構築する"""
    now = datetime.now(JST)

    # ステータスマッピング
    status_map = {
        "1": "新規", "2": "進行中", "3": "解決", "5": "終了", "6": "却下"
    }

    # --- プロジェクト prj-alpha ---
    alpha_issues = [
        # 課題: 3週間前から存在、1週間前に進行中→解決
        make_issue(101, "課題", "ログイン画面のレイアウト崩れ", 3, "解決",
                   created_days_ago=25,
                   journals=[
                       make_journal(20, status_old=1, status_new=2),  # 新規→進行中
                       make_journal(5, status_old=2, status_new=3),   # 進行中→解決
                   ]),
        # 課題: 2週間前に作成、まだ新規
        make_issue(102, "課題", "検索機能が遅い", 1, "新規",
                   created_days_ago=12),
        # 課題: 1週間前に作成、進行中
        make_issue(103, "課題", "CSVエクスポートのエンコーディング", 2, "進行中",
                   created_days_ago=5,
                   journals=[
                       make_journal(3, status_old=1, status_new=2),
                   ]),
        # Q/A: 3週間前から存在、終了済み
        make_issue(201, "Q/A", "APIの認証方式について", 5, "終了",
                   created_days_ago=22,
                   journals=[
                       make_journal(15, status_old=1, status_new=2),
                       make_journal(10, status_old=2, status_new=5),
                   ]),
        # Q/A: 1週間前に作成
        make_issue(202, "Q/A", "バッチ処理の実行タイミング", 1, "新規",
                   created_days_ago=6),
        # サポート: 2週間前から存在
        make_issue(301, "サポート", "本番環境のログ調査依頼", 2, "進行中",
                   created_days_ago=13,
                   journals=[
                       make_journal(10, status_old=1, status_new=2),
                   ]),
        # 成果物: 期日あり、進捗変化あり
        make_issue(401, "成果物", "基本設計書 v1.0", 2, "進行中",
                   done_ratio=70,
                   due_date=(now + timedelta(days=7)).strftime("%Y-%m-%d"),
                   created_days_ago=28,
                   journals=[
                       make_journal(18, ratio_old=0, ratio_new=20),
                       make_journal(11, ratio_old=20, ratio_new=50),
                       make_journal(4, ratio_old=50, ratio_new=70),
                   ]),
        # 成果物: 期日超過、遅延
        make_issue(402, "成果物", "テスト計画書", 2, "進行中",
                   done_ratio=40,
                   due_date=(now - timedelta(days=3)).strftime("%Y-%m-%d"),
                   created_days_ago=25,
                   journals=[
                       make_journal(14, ratio_old=0, ratio_new=20),
                       make_journal(7, ratio_old=20, ratio_new=40),
                   ]),
        # 成果物: 完了済み
        make_issue(403, "成果物", "要件定義書", 5, "終了",
                   done_ratio=100,
                   due_date=(now - timedelta(days=10)).strftime("%Y-%m-%d"),
                   created_days_ago=35,
                   journals=[
                       make_journal(25, ratio_old=0, ratio_new=30),
                       make_journal(18, ratio_old=30, ratio_new=60),
                       make_journal(12, ratio_old=60, ratio_new=100, status_old=2, status_new=5),
                   ]),
        # 進捗報告: プロマネが状況を記載
        make_issue(901, "進捗報告", "第4週 進捗報告", 2, "進行中",
                   created_days_ago=5,
                   journals=[
                       make_journal(2),
                   ]),
    ]
    # 進捗報告チケットに説明文を設定
    alpha_issues[-1]["description"] = (
        "【今週の進捗】\n"
        "・基本設計書の作成が70%まで進捗。来週中に完了見込み。\n"
        "・テスト計画書は期日超過しており、リソース追加を検討中。\n"
        "・CSVエクスポートのエンコーディング問題が新たに発生。調査開始済み。\n"
        "【リスク】\n"
        "・テスト計画書の遅延がテストフェーズ全体に影響する可能性あり。\n"
        "・検索機能の性能問題は未着手。優先度の見直しが必要。\n"
        "【詳細状況】\n"
        "・基本設計書はレビュー指摘事項の反映が残っており、レビュアーとの調整を進めている。\n"
        "・テスト計画書については、テスト対象範囲の見直しが必要との指摘があり、再検討中。\n"
        "・CSVエクスポートの問題は文字コードの変換処理に起因しており、ライブラリの更新で対応予定。\n"
        "・来週はレビュー会議を2回予定しており、基本設計書の完了を目指す。\n"
        "・テスト計画書のリカバリーについては、外部リソースの投入を上長に相談済み。回答待ち。\n"
        "【来週の予定】\n"
        "・基本設計書レビュー会議（5/1, 5/3）\n"
        "・テスト計画書リカバリープラン策定\n"
        "・CSVエクスポート修正・単体テスト\n"
        "・検索機能の性能調査着手判断"
    )

    # バグチケット（フェーズ別: IT/ST/UAT）
    bug_issues_alpha = [
        make_issue(1001, "バグ", "IT: ログイン時にセッションが切れる", 2, "進行中",
                   created_days_ago=20,
                   journals=[make_journal(15, status_old=1, status_new=2)]),
        make_issue(1002, "バグ", "IT: 一覧画面のページネーション不具合", 3, "解決",
                   created_days_ago=18,
                   journals=[make_journal(14, status_old=1, status_new=2), make_journal(8, status_old=2, status_new=3)]),
        make_issue(1003, "バグ", "IT: CSVダウンロードで文字化け", 1, "新規",
                   created_days_ago=5),
        make_issue(1004, "バグ", "ST: 帳票出力の合計値が不正", 2, "進行中",
                   created_days_ago=12,
                   journals=[make_journal(10, status_old=1, status_new=2)]),
        make_issue(1005, "バグ", "ST: 検索条件のAND/OR動作が逆", 1, "新規",
                   created_days_ago=6),
        make_issue(1006, "バグ", "ST: 日付入力のバリデーション漏れ", 1, "新規",
                   created_days_ago=3),
        make_issue(1007, "バグ", "UAT: 承認フローで差し戻しが効かない", 1, "新規",
                   created_days_ago=2),
    ]
    # fixed_versionを設定
    for bug in bug_issues_alpha:
        subj = bug["subject"]
        if subj.startswith("IT:"):
            bug["fixed_version"] = {"id": 10, "name": "06_IT"}
        elif subj.startswith("ST:"):
            bug["fixed_version"] = {"id": 11, "name": "07_ST"}
        elif subj.startswith("UAT:"):
            bug["fixed_version"] = {"id": 12, "name": "08_UAT"}
    alpha_issues.extend(bug_issues_alpha)

    # 成果物にバージョン（工程）を設定
    for issue in alpha_issues:
        if issue["id"] == 401:
            issue["fixed_version"] = {"id": 20, "name": "04_SS"}
        elif issue["id"] == 402:
            issue["fixed_version"] = {"id": 20, "name": "04_SS"}
        elif issue["id"] == 403:
            issue["fixed_version"] = {"id": 21, "name": "03_UC"}

    # テストスイートチケット（IT/STフェーズ）
    test_suite_issues = [
        make_issue(1101, "テストスイート", "IT_ログイン機能テスト", 2, "進行中", created_days_ago=10),
        make_issue(1102, "テストスイート", "IT_検索機能テスト", 5, "終了", created_days_ago=15),
        make_issue(1103, "テストスイート", "ST_帳票出力テスト", 1, "新規", created_days_ago=5),
    ]
    test_suite_issues[0]["fixed_version"] = {"id": 10, "name": "06_IT"}
    test_suite_issues[0]["custom_fields"] = [
        {"id": 100, "name": "予定ケース数", "value": "50"},
        {"id": 101, "name": "実績ケース数", "value": "35"},
    ]
    test_suite_issues[1]["fixed_version"] = {"id": 10, "name": "06_IT"}
    test_suite_issues[1]["custom_fields"] = [
        {"id": 100, "name": "予定ケース数", "value": "30"},
        {"id": 101, "name": "実績ケース数", "value": "30"},
    ]
    test_suite_issues[2]["fixed_version"] = {"id": 11, "name": "07_ST"}
    test_suite_issues[2]["custom_fields"] = [
        {"id": 100, "name": "予定ケース数", "value": "80"},
        {"id": 101, "name": "実績ケース数", "value": "0"},
    ]
    alpha_issues.extend(test_suite_issues)

    # --- プロジェクト prj-beta ---
    beta_issues = [
        # 課題: 最近作成
        make_issue(501, "課題", "画面遷移時のエラー", 1, "新規",
                   project_id="prj-beta", created_days_ago=3),
        # 課題: 2週間前に作成、期限超過（Risk_Score上昇用）
        make_issue(502, "課題", "データ不整合の調査", 2, "進行中",
                   project_id="prj-beta", created_days_ago=13,
                   due_date=(now - timedelta(days=10)).strftime("%Y-%m-%d"),
                   journals=[
                       make_journal(10, status_old=1, status_new=2),
                   ]),
        # Q/A: 1週間前に作成、期限未設定（Risk_Score上昇用）
        make_issue(503, "Q/A", "認証フローの確認", 1, "新規",
                   project_id="prj-beta", created_days_ago=6),
        # Q/A: 最近作成、期限超過（Risk_Score上昇用）
        make_issue(504, "Q/A", "API仕様の不明点", 1, "新規",
                   project_id="prj-beta", created_days_ago=2,
                   due_date=(now - timedelta(days=1)).strftime("%Y-%m-%d")),
        # サポート: 3週間前から
        make_issue(601, "サポート", "アカウント発行依頼", 5, "終了",
                   project_id="prj-beta", created_days_ago=20,
                   journals=[
                       make_journal(18, status_old=1, status_new=2),
                       make_journal(15, status_old=2, status_new=5),
                   ]),
        # 成果物: 期日未設定
        make_issue(701, "成果物", "運用手順書", 1, "新規",
                   done_ratio=0, project_id="prj-beta",
                   created_days_ago=8),
    ]

    projects_issues = {
        "prj-alpha": alpha_issues,
        "prj-beta": beta_issues,
    }
    project_ids = ["prj-alpha", "prj-beta"]

    return projects_issues, project_ids, status_map


def main():
    print("=== ダッシュボードレポート テスト（モックデータ） ===\n")

    projects_issues, project_ids, status_map = build_mock_data()

    # チェックポイント確認
    checkpoints = get_checkpoints()
    print("定点:")
    for label, dt in checkpoints:
        print(f"  {label}: {dt.strftime('%Y-%m-%d %H:%M')}")
    print()

    # 集計
    print("集計中...")
    tracker_stats, deliverable_data, cps, per_project_stats, per_project_deliverables = \
        aggregate_data(projects_issues, status_map)

    # 集計結果の確認
    checkpoint_labels = [c[0] for c in cps]
    print("\n--- 全体集計 ---")
    for tn in TARGET_TRACKERS:
        print(f"\n[{tn}]")
        for label in checkpoint_labels:
            stats = tracker_stats.get(tn, {}).get(label, {})
            if stats:
                items = ", ".join(f"{k}: {v}" for k, v in sorted(stats.items()))
                print(f"  {label}: {items}")
            else:
                print(f"  {label}: (データなし)")

    print("\n--- 成果物 予実 ---")
    for d in deliverable_data:
        ratios = ", ".join(f"{k}: {v}%" for k, v in d["ratios"].items())
        print(f"  #{d['id']} {d['subject']} | 期日: {d['due_date']} | 進捗: {d['done_ratio']}% | {ratios}")

    print("\n--- プロジェクト別 ---")
    for pid in project_ids:
        print(f"\n[{pid}] チケット数: {len(projects_issues[pid])}")
        for tn in TARGET_TRACKERS:
            cur = per_project_stats.get(pid, {}).get(tn, {}).get("現在", {})
            total = sum(cur.values())
            if total > 0:
                print(f"  {tn}: {total}件")

    # Risk_Score算出・トレンド判定・AI考察対象決定
    print("\nRisk_Score算出中...")
    risk_scores = compute_risk_scores(projects_issues, cps, status_map)
    deadline_risk = detect_deadline_risk(risk_scores)
    print("Risk_Score:")
    for pid in project_ids:
        scores = risk_scores.get(pid, [0, 0, 0, 0])
        flag = deadline_risk.get(pid, False)
        print(f"  {pid}: {scores} → {'⚠ リスク' if flag else 'OK'}")

    # 自動抽出モック（prj-betaを自動抽出扱いにする）
    auto_extracted = {"prj-beta"}

    # AI考察対象決定
    ai_flags_map = {"prj-alpha": True, "prj-beta": False}
    ai_targets = resolve_ai_targets(project_ids, ai_flags_map, deadline_risk)
    print(f"\nAI考察対象: {ai_targets}")

    # HTML生成
    print("\nHTML生成中...")
    html = generate_html(
        tracker_stats, deliverable_data, cps, project_ids,
        per_project_stats, per_project_deliverables, projects_issues,
        {"prj-alpha": "アルファプロジェクト", "prj-beta": "ベータプロジェクト"},
        ai_flags_map,
        {
            "prj-alpha": {
                "本部": "IT本部", "部": "開発部", "案件No": "A-001",
                "子案件No": "prj-alpha", "子案件名": "アルファプロジェクト",
                "影響度区分": "大", "重要案件区分": "重要", "新領域案件": "",
                "案件種類": "新規開発", "工程": "04_SS",
                "コスト(工数)": "120人月", "状況": "進行中",
                "進捗状況": "概ね順調", "コスト(工数)割合": "60%",
                "進捗率": "55%", "開始日": "2026/01/15",
                "完了予定日": "2026/09/30", "完了実績日": "",
                "着手年月": "2026/01", "サービスイン予定日": "2026/10/01",
                "進捗更新日": "2026/04/25",
            },
            "prj-beta": {
                "本部": "IT本部", "部": "保守部", "案件No": "B-002",
                "子案件No": "prj-beta", "子案件名": "ベータプロジェクト",
                "影響度区分": "中", "重要案件区分": "", "新領域案件": "",
                "案件種類": "保守", "工程": "06_IT",
                "コスト(工数)": "30人月", "状況": "進行中",
                "進捗状況": "", "コスト(工数)割合": "",
                "進捗率": "70%", "開始日": "2026/03/01",
                "完了予定日": "2026/06/30", "完了実績日": "",
                "着手年月": "2026/03", "サービスイン予定日": "2026/07/01",
                "進捗更新日": "2026/04/22",
            },
        },
        auto_extracted=auto_extracted,
        risk_scores=risk_scores,
        deadline_risk=deadline_risk,
        ai_targets=ai_targets,
    )

    output_path = "test_dashboard.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ テスト完了: {output_path} ({len(html):,} bytes)")
    print(f"   ブラウザで開いて確認してください。")

    # --- HTML内容の検証 ---
    print("\n--- HTML内容の検証 ---")
    errors = []

    # フィルタ入力欄の存在確認
    if 'class="col-filter"' in html:
        print("  ✅ フィルタ入力欄（col-filter）が存在")
    else:
        errors.append("フィルタ入力欄（col-filter）が見つかりません")

    # 期限リスク列の存在確認
    if "期限リスク" in html:
        print("  ✅ 「期限リスク」列が存在")
    else:
        errors.append("「期限リスク」列が見つかりません")

    # 自動抽出バッジの存在確認
    if "自動抽出" in html:
        print("  ✅ 「🔍 自動抽出」バッジが存在")
    else:
        errors.append("「🔍 自動抽出」バッジが見つかりません")

    # data-risk-scores属性の存在確認
    if "data-risk-scores" in html:
        print("  ✅ data-risk-scores属性が存在")
    else:
        errors.append("data-risk-scores属性が見つかりません")

    # ソートインジケーター関連のJS存在確認
    if "sortTable" in html or "sort-indicator" in html or "▲" in html or "data-original-index" in html:
        print("  ✅ ソート機能関連のコードが存在")
    else:
        errors.append("ソート機能関連のコードが見つかりません")

    # project-list-table IDの存在確認
    if 'id="project-list-table"' in html:
        print("  ✅ project-list-table IDが存在")
    else:
        errors.append("project-list-table IDが見つかりません")

    if errors:
        print(f"\n❌ 検証エラー: {len(errors)}件")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\n✅ すべての検証に合格しました")


if __name__ == "__main__":
    main()
