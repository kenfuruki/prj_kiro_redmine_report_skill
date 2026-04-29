#!/usr/bin/env python3
"""
20プロジェクト規模のダッシュボードテスト
各プロジェクト30〜50チケット、合計約800チケットのモックデータで負荷確認する。
"""

import sys
import os
import random
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard_report import (
    JST, TARGET_TRACKERS, get_checkpoints,
    aggregate_data, generate_html,
    compute_risk_scores, detect_deadline_risk, resolve_ai_targets,
)

random.seed(42)

STATUS_MAP = {
    "1": "新規", "2": "進行中", "3": "解決",
    "4": "フィードバック", "5": "終了", "6": "却下"
}

TRACKER_WEIGHTS = {"課題": 40, "Q/A": 20, "サポート": 15, "成果物": 25}
STATUS_FLOW = [
    (1, "新規"), (2, "進行中"), (3, "解決"), (5, "終了")
]


def make_journals(created_days_ago, current_status_idx, current_ratio):
    """ランダムなジャーナル（変更履歴）を生成する"""
    journals = []
    now = datetime.now(JST)
    # ステータス変更履歴
    if current_status_idx > 0:
        days_between = created_days_ago // (current_status_idx + 1)
        for i in range(current_status_idx):
            days_ago = created_days_ago - (i + 1) * days_between
            if days_ago < 0:
                days_ago = 1
            old_id, _ = STATUS_FLOW[i]
            new_id, _ = STATUS_FLOW[i + 1]
            journals.append({
                "id": random.randint(1000, 99999),
                "user": {"id": 1, "name": "担当者"},
                "notes": "",
                "created_on": (now - timedelta(days=days_ago)).isoformat(),
                "details": [{
                    "property": "attr", "name": "status_id",
                    "old_value": str(old_id), "new_value": str(new_id),
                }],
            })
    # 進捗率変更履歴（成果物用）
    if current_ratio > 0:
        steps = random.randint(1, 4)
        ratio_step = current_ratio // steps
        for i in range(steps):
            days_ago = created_days_ago - (i + 1) * (created_days_ago // (steps + 1))
            if days_ago < 0:
                days_ago = 1
            old_r = i * ratio_step
            new_r = (i + 1) * ratio_step if i < steps - 1 else current_ratio
            journals.append({
                "id": random.randint(1000, 99999),
                "user": {"id": 1, "name": "担当者"},
                "notes": "",
                "created_on": (now - timedelta(days=days_ago)).isoformat(),
                "details": [{
                    "property": "attr", "name": "done_ratio",
                    "old_value": str(old_r), "new_value": str(new_r),
                }],
            })
    return journals


def generate_project_issues(project_id, num_issues):
    """1プロジェクト分のモックチケットを生成する"""
    now = datetime.now(JST)
    issues = []
    issue_id_base = hash(project_id) % 10000 + 1000

    for i in range(num_issues):
        # トラッカーをランダム選択（重み付き）
        tracker = random.choices(
            list(TRACKER_WEIGHTS.keys()),
            weights=list(TRACKER_WEIGHTS.values()),
            k=1
        )[0]

        created_days_ago = random.randint(1, 35)
        status_idx = random.randint(0, min(3, created_days_ago // 5))
        status_id, status_name = STATUS_FLOW[status_idx]

        done_ratio = 0
        due_date = None
        if tracker == "成果物":
            done_ratio = random.choice([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
            if random.random() > 0.15:  # 85%は期日あり
                due_offset = random.randint(-10, 30)
                due_date = (now + timedelta(days=due_offset)).strftime("%Y-%m-%d")

        journals = make_journals(created_days_ago, status_idx, done_ratio)

        issues.append({
            "id": issue_id_base + i,
            "tracker": {"id": 1, "name": tracker},
            "subject": f"{tracker}_{project_id}_{i+1:03d}",
            "status": {"id": status_id, "name": status_name},
            "priority": {"id": random.choice([1, 2, 3, 4]), "name": ["低め", "通常", "高め", "急いで"][random.randint(0, 3)]},
            "assigned_to": {"id": random.randint(1, 10), "name": f"メンバー{random.randint(1, 10)}"},
            "author": {"id": 1, "name": "作成者"},
            "done_ratio": done_ratio,
            "due_date": due_date,
            "created_on": (now - timedelta(days=created_days_ago)).isoformat(),
            "updated_on": now.isoformat(),
            "journals": journals,
        })
    return issues


def main():
    print("=== 20プロジェクト規模テスト ===\n")

    # 20プロジェクト生成
    project_ids = [f"prj-{chr(65+i)}{chr(65+j)}" for i in range(4) for j in range(5)]  # prj-AA 〜 prj-DE
    project_names = {pid: f"プロジェクト{pid[-2:]}" for pid in project_ids}
    ai_flags = {pid: (i % 3 == 0) for i, pid in enumerate(project_ids)}  # 3つに1つAIフラグON
    projects_issues = {}
    total_issues = 0

    t0 = time.time()
    for pid in project_ids:
        num = random.randint(30, 50)
        projects_issues[pid] = generate_project_issues(pid, num)
        total_issues += num

    t1 = time.time()
    print(f"モックデータ生成: {len(project_ids)}プロジェクト, {total_issues}チケット ({t1-t0:.2f}秒)")

    # 集計
    t2 = time.time()
    tracker_stats, deliverable_data, cps, per_project_stats, per_project_deliverables = \
        aggregate_data(projects_issues, STATUS_MAP)
    t3 = time.time()
    print(f"集計処理: {t3-t2:.2f}秒")

    # 集計サマリー
    checkpoint_labels = [c[0] for c in cps]
    print(f"\n全体集計（現在）:")
    for tn in TARGET_TRACKERS:
        cur = tracker_stats.get(tn, {}).get("現在", {})
        total = sum(cur.values())
        print(f"  {tn}: {total}件")
    print(f"  成果物（予実対象）: {len(deliverable_data)}件")

    # Risk_Score算出・トレンド判定
    risk_scores = compute_risk_scores(projects_issues, cps, STATUS_MAP)
    deadline_risk = detect_deadline_risk(risk_scores)
    print(f"\n期限リスク検知:")
    risk_count = sum(1 for v in deadline_risk.values() if v)
    print(f"  ⚠ 期限リスクあり: {risk_count}件")

    # 自動抽出モック（最後の3プロジェクトを自動抽出扱い）
    auto_extracted = set(project_ids[-3:])

    # AI考察対象決定
    ai_targets = resolve_ai_targets(project_ids, ai_flags, deadline_risk)
    print(f"  AI考察対象: {len(ai_targets)}件")

    # HTML生成
    t4 = time.time()
    # rpm.csvモックデータ
    rpm_data = {}
    phases = ["01_SP", "02_SA", "03_UC", "04_SS", "05_PS/PG/PT", "06_IT", "07_ST", "08_UAT", "09_OT"]
    statuses = ["進行中", "進行中", "遅延気味", "進行中", "順調"]
    for i, pid in enumerate(project_ids):
        rpm_data[pid] = {
            "本部": "IT本部", "部": f"部門{chr(65+i%5)}",
            "案件No": f"PRJ-{i+1:03d}", "子案件No": pid,
            "子案件名": project_names[pid],
            "影響度区分": ["大", "中", "小"][i % 3],
            "重要案件区分": "重要" if i % 4 == 0 else "",
            "案件種類": ["新規開発", "保守", "改修"][i % 3],
            "工程": phases[i % len(phases)],
            "コスト(工数)": f"{random.randint(20, 200)}人月",
            "状況": statuses[i % len(statuses)],
            "進捗率": f"{random.randint(10, 90)}%",
            "開始日": "2026/01/15",
            "完了予定日": "2026/09/30",
            "サービスイン予定日": "2026/10/01",
            "進捗更新日": "2026/04/25",
        }

    html = generate_html(
        tracker_stats, deliverable_data, cps, project_ids,
        per_project_stats, per_project_deliverables, projects_issues,
        project_names, ai_flags, rpm_data,
        auto_extracted=auto_extracted,
        risk_scores=risk_scores,
        deadline_risk=deadline_risk,
        ai_targets=ai_targets,
    )
    t5 = time.time()
    print(f"\nHTML生成: {t5-t4:.2f}秒")

    output_path = "test_dashboard_20prj.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    html_kb = len(html.encode("utf-8")) / 1024
    print(f"HTMLサイズ: {html_kb:.1f} KB")
    print(f"合計処理時間: {t5-t0:.2f}秒")
    print(f"\n✅ テスト完了: {output_path}")
    print(f"   ブラウザで開いて動作確認してください。")

    # --- HTML内容の検証 ---
    print("\n--- HTML内容の検証 ---")
    errors = []

    if 'class="col-filter"' in html:
        print("  ✅ フィルタ入力欄（col-filter）が存在")
    else:
        errors.append("フィルタ入力欄（col-filter）が見つかりません")

    if "期限リスク" in html:
        print("  ✅ 「期限リスク」列が存在")
    else:
        errors.append("「期限リスク」列が見つかりません")

    if "自動抽出" in html:
        print("  ✅ 「🔍 自動抽出」バッジが存在")
    else:
        errors.append("「🔍 自動抽出」バッジが見つかりません")

    if errors:
        print(f"\n❌ 検証エラー: {len(errors)}件")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\n✅ すべての検証に合格しました")


if __name__ == "__main__":
    main()
