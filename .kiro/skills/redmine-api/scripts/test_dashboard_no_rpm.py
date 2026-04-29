#!/usr/bin/env python3
"""
rpm.csvなしのダッシュボードテスト
rpm_dataを空にして、rpm.csv列が表示されないことを確認する。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# test_dashboard.pyからモックデータ構築を再利用
from test_dashboard import build_mock_data
from dashboard_report import (
    get_checkpoints, aggregate_data, generate_html,
)


def main():
    print("=== rpm.csvなしテスト ===\n")

    projects_issues, project_ids, status_map = build_mock_data()

    tracker_stats, deliverable_data, cps, per_project_stats, per_project_deliverables = \
        aggregate_data(projects_issues, status_map)

    # rpm_data=None（rpm.csvなし）
    html = generate_html(
        tracker_stats, deliverable_data, cps, project_ids,
        per_project_stats, per_project_deliverables, projects_issues,
        {"prj-alpha": "アルファプロジェクト", "prj-beta": "ベータプロジェクト"},
        {"prj-alpha": True, "prj-beta": False},
        None  # rpm_dataなし
    )

    output_path = "test_dashboard_no_rpm.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ テスト完了: {output_path} ({len(html):,} bytes)")
    print("   rpm.csv列が表示されていないことをブラウザで確認してください。")


if __name__ == "__main__":
    main()
