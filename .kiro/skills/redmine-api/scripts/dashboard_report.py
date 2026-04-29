#!/usr/bin/env python3
"""
Redmine ダッシュボードレポート生成ツール

CSVファイルからプロジェクトID一覧を読み込み、
各プロジェクトのチケット状況を3定点（2週間前・1週間前・現在）で集計し、
オフラインで動作するHTMLダッシュボードを出力する。
"""

import os
import sys
import csv
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import time

# --- 設定 ---

JST = timezone(timedelta(hours=9))

# 対象トラッカー名（Redmineの設定に合わせて変更可能）
TARGET_TRACKERS = ["課題", "Q/A", "サポート", "成果物", "進捗報告"]

# レートリミット設定
MAX_PROJECTS = 30        # CSVに記載できるプロジェクト数の上限
API_SLEEP_SEC = 0.5      # APIリクエスト間のスリープ（秒）

# 3定点の定義
def get_checkpoints():
    """3週間前・2週間前・1週間前・現在の4定点を返す"""
    now = datetime.now(JST)
    return [
        ("3週間前", now - timedelta(weeks=3)),
        ("2週間前", now - timedelta(weeks=2)),
        ("1週間前", now - timedelta(weeks=1)),
        ("現在", now),
    ]


# --- API ---

def get_config():
    """環境変数から設定を取得する"""
    url = os.environ.get("REDMINE_URL")
    key = os.environ.get("REDMINE_API_KEY")
    if not url or not key:
        print("エラー: 環境変数 REDMINE_URL と REDMINE_API_KEY を設定してください。", file=sys.stderr)
        sys.exit(1)
    return url.rstrip("/"), key


def api_get(path):
    """Redmine APIにGETリクエストを送信する（レートリミット付き）"""
    base_url, api_key = get_config()
    url = f"{base_url}{path}"
    headers = {"X-Redmine-API-Key": api_key, "Content-Type": "application/json"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"APIエラー ({e.code}): {path}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"接続エラー: {e.reason}", file=sys.stderr)
        return None
    finally:
        time.sleep(API_SLEEP_SEC)


def fetch_all_issues(project_id):
    """プロジェクトの全チケットをjournals付きで取得する（ページネーション対応）"""
    all_issues = []
    offset = 0
    limit = 100
    while True:
        path = (
            f"/projects/{project_id}/issues.json"
            f"?include=journals&status_id=*&limit={limit}&offset={offset}"
        )
        result = api_get(path)
        if not result:
            break
        issues = result.get("issues", [])
        all_issues.extend(issues)
        total = result.get("total_count", 0)
        offset += limit
        if offset >= total:
            break
        print(f"  取得中... {len(all_issues)}/{total}件", file=sys.stderr)
    return all_issues


def fetch_project_name(project_id):
    """プロジェクト名を取得する"""
    result = api_get(f"/projects/{project_id}.json")
    if result:
        return result.get("project", {}).get("name", project_id)
    return project_id


def fetch_subproject_ids(project_id):
    """サブプロジェクトのidentifier一覧を取得する"""
    result = api_get(f"/projects/{project_id}.json?include=children")
    if not result:
        return []
    children = result.get("project", {}).get("children", [])
    return [c.get("identifier", str(c.get("id", ""))) for c in children if c]


def fetch_all_issues_with_subprojects(project_id):
    """プロジェクトとそのサブプロジェクトの全チケットを合算して取得する"""
    # 親プロジェクトのチケット
    all_issues = fetch_all_issues(project_id)
    # サブプロジェクトのチケット
    sub_ids = fetch_subproject_ids(project_id)
    for sub_id in sub_ids:
        print(f"    サブプロジェクト '{sub_id}' のチケットを取得中...", file=sys.stderr)
        sub_issues = fetch_all_issues(sub_id)
        all_issues.extend(sub_issues)
        print(f"    → {len(sub_issues)}件取得", file=sys.stderr)
    return all_issues


def fetch_issue_qa_count(project_id):
    """指定プロジェクトの課題トラッカー + Q/Aトラッカーのオープンチケット総数を取得する。

    Redmine APIの /projects/{id}/issues.json を使用し、
    オープンチケットを取得してトラッカー名が「課題」または「Q/A」のものを合算して返す。
    プロジェクトが存在しない場合やAPIエラー時は -1 を返す。
    """
    total = 0
    offset = 0
    limit = 100
    while True:
        path = (
            f"/projects/{project_id}/issues.json"
            f"?status_id=open&limit={limit}&offset={offset}"
        )
        result = api_get(path)
        if result is None:
            return -1
        issues = result.get("issues", [])
        for issue in issues:
            tracker_name = issue.get("tracker", {}).get("name", "")
            if tracker_name in ("課題", "Q/A"):
                total += 1
        total_count = result.get("total_count", 0)
        offset += limit
        if offset >= total_count:
            break
    return total


def auto_extract_projects(rpm_data, existing_pids, max_projects=MAX_PROJECTS,
                          max_extract=5, today=None):
    """RPM_CSVからサービスイン予定日が操作日以降のプロジェクトを自動抽出する。

    処理手順:
    1. rpm_dataからサービスイン予定日が操作日以降のレコードを抽出
    2. existing_pidsに含まれるプロジェクトを除外
    3. 各プロジェクトの課題+QAチケット総数をAPIから取得
    4. チケット総数の降順で上位max_extract件を選出
    5. MAX_PROJECTSを超えない範囲で件数を調整

    Args:
        rpm_data: load_rpm_data()の戻り値（子案件Noをキーとするdict）
        existing_pids: Projects_CSVのプロジェクトIDリスト
        max_projects: プロジェクト数の上限（デフォルト: MAX_PROJECTS）
        max_extract: 自動抽出の最大件数（デフォルト: 5）
        today: テスト用の操作日注入（デフォルト: 現在日時）

    Returns:
        自動抽出されたプロジェクトIDのリスト
    """
    if today is None:
        today = datetime.now(JST)
    if isinstance(today, datetime):
        today_date = today.date()
    else:
        today_date = today

    existing_set = set(existing_pids)

    # サービスイン予定日のパース（複数フォーマット対応）
    def parse_service_in_date(date_str):
        """サービスイン予定日を複数フォーマットでパースする"""
        if not date_str or not date_str.strip():
            return None
        date_str = date_str.strip()
        formats = [
            "%Y/%m/%d",    # YYYY/MM/DD
            "%Y-%m-%d",    # YYYY-MM-DD
            "%Y年%m月%d日",  # YYYY年MM月DD日
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    # 候補プロジェクトの抽出
    candidates = []
    for pid, info in rpm_data.items():
        # existing_pidsに含まれるプロジェクトを除外
        if pid in existing_set:
            continue

        # サービスイン予定日を取得・パース
        service_in_str = info.get("サービスイン予定日", "")
        if not service_in_str or not service_in_str.strip():
            continue  # 空欄は除外

        service_in_date = parse_service_in_date(service_in_str)
        if service_in_date is None:
            # 不正な日付形式 → スキップして警告
            print(f"警告: プロジェクト '{pid}' のサービスイン予定日 '{service_in_str}' が不正な日付形式です。スキップします。", file=sys.stderr)
            continue

        # サービスイン予定日が操作日以降かチェック
        if service_in_date < today_date:
            continue

        candidates.append(pid)

    # 各候補プロジェクトのチケット数を取得
    scored = []
    for pid in candidates:
        count = fetch_issue_qa_count(pid)
        if count < 0:
            # Redmine上に存在しないプロジェクト → スキップ
            print(f"警告: プロジェクト '{pid}' はRedmine上に存在しないか、APIエラーが発生しました。スキップします。", file=sys.stderr)
            continue
        scored.append((pid, count))

    # チケット数の降順でソート
    scored.sort(key=lambda x: x[1], reverse=True)

    # 上位max_extract件を選出
    extracted = [pid for pid, _ in scored[:max_extract]]

    # MAX_PROJECTSを超えない範囲で件数を調整
    remaining = max_projects - len(existing_pids)
    if remaining < 0:
        remaining = 0
    if len(extracted) > remaining:
        extracted = extracted[:remaining]

    # ログ出力
    if extracted:
        print(f"自動抽出: {len(extracted)}件のプロジェクトを追加", file=sys.stderr)
        for pid in extracted:
            count = next((c for p, c in scored if p == pid), 0)
            print(f"  → {pid} (課題+QA: {count}件)", file=sys.stderr)
    else:
        print("自動抽出: 該当プロジェクトなし（0件）", file=sys.stderr)

    return extracted


# --- CSV読み込み ---

def load_project_ids(csv_path):
    """CSVファイルからプロジェクトidentifierとAIフラグを読み込む"""
    project_ids = []
    ai_flags = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        has_ai_flag = any("ai" in fn.lower() for fn in fieldnames)
        for row in reader:
            values = list(row.values())
            pid = values[0].strip()
            if not pid:
                continue
            project_ids.append(pid)
            if has_ai_flag:
                for fn in fieldnames:
                    if "ai" in fn.lower():
                        ai_flags[pid] = row[fn].strip() in ("1", "true", "yes", "○")
                        break
            if pid not in ai_flags:
                ai_flags[pid] = False
    return project_ids, ai_flags


def load_rpm_data(rpm_path):
    """rpm.csvからプロジェクト補助データを読み込む（子案件Noをキーにする）"""
    rpm_data = {}
    if not rpm_path or not os.path.exists(rpm_path):
        return rpm_data
    with open(rpm_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("子案件No", "").strip()
            if not pid:
                continue
            rpm_data[pid] = {k: v.strip() if v else "" for k, v in row.items()}
    return rpm_data


# --- 状態復元 ---

def parse_datetime(dt_str):
    """Redmineの日時文字列をdatetimeに変換する"""
    if not dt_str:
        return None
    # Redmineは ISO 8601 形式で返す
    dt_str = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(dt_str).astimezone(JST)
    except (ValueError, TypeError):
        return None


def get_status_at(issue, target_dt):
    """指定時点でのチケットのステータスを復元する"""
    created_on = parse_datetime(issue.get("created_on"))
    if not created_on or created_on > target_dt:
        return None  # まだ作成されていない

    current_status = issue.get("status", {}).get("name", "不明")
    # journalsを時系列で走査し、target_dt以前の最後のステータスを見つける
    status = current_status
    # journalsを逆順に見て、target_dt以降の変更を巻き戻す
    journals = issue.get("journals", [])
    # 新しい順にソート
    journals_sorted = sorted(journals, key=lambda j: j.get("created_on", ""), reverse=True)

    for journal in journals_sorted:
        j_dt = parse_datetime(journal.get("created_on"))
        if not j_dt or j_dt <= target_dt:
            break
        # この変更はtarget_dt以降なので巻き戻す
        for detail in journal.get("details", []):
            if detail.get("name") == "status_id":
                old_val = detail.get("old_value")
                if old_val:
                    # ステータスIDから名前への変換は後で行う
                    status = f"__id:{old_val}"
    return status


def get_done_ratio_at(issue, target_dt):
    """指定時点でのチケットの進捗率を復元する"""
    created_on = parse_datetime(issue.get("created_on"))
    if not created_on or created_on > target_dt:
        return None

    current_ratio = issue.get("done_ratio", 0)
    ratio = current_ratio
    journals = issue.get("journals", [])
    journals_sorted = sorted(journals, key=lambda j: j.get("created_on", ""), reverse=True)

    for journal in journals_sorted:
        j_dt = parse_datetime(journal.get("created_on"))
        if not j_dt or j_dt <= target_dt:
            break
        for detail in journal.get("details", []):
            if detail.get("name") == "done_ratio":
                old_val = detail.get("old_value")
                if old_val is not None:
                    ratio = int(old_val)
    return ratio


# --- ステータスID→名前マッピング ---

def fetch_status_map():
    """ステータスIDと名前のマッピングを取得する"""
    result = api_get("/issue_statuses.json")
    if not result:
        return {}
    return {str(s["id"]): s["name"] for s in result.get("issue_statuses", [])}


def resolve_status_name(status_str, status_map):
    """ステータス文字列を名前に解決する"""
    if status_str and status_str.startswith("__id:"):
        sid = status_str.replace("__id:", "")
        return status_map.get(sid, f"ID:{sid}")
    return status_str


# --- 期限リスク検知 ---

# 完了ステータス名のセット（Overdue/Blank算出で除外する）
CLOSED_STATUSES = {"解決", "終了", "却下"}


def _is_overdue_at(issue, checkpoint_dt, status_map):
    """指定時点でチケットが期限超過かどうかを判定する。

    条件:
    - due_dateが存在し、checkpoint_dtより前である
    - 指定時点のステータスが未完了（CLOSED_STATUSES以外）である
    - チケットが指定時点で作成済みである

    Args:
        issue: チケットdict（due_date, status, journals等を含む）
        checkpoint_dt: 判定時点のdatetime
        status_map: ステータスID→名前マッピング

    Returns:
        True: 期限超過かつ未完了, False: それ以外
    """
    # ステータスを復元
    status_raw = get_status_at(issue, checkpoint_dt)
    if status_raw is None:
        return False  # まだ作成されていない
    status_name = resolve_status_name(status_raw, status_map)
    if status_name in CLOSED_STATUSES:
        return False  # 完了済み

    # due_dateの確認
    due_date_str = issue.get("due_date")
    if not due_date_str:
        return False  # 期限未設定はoverdueではない（blank_dueで扱う）

    try:
        due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
        # checkpoint_dtと比較するためtimezone-naiveに変換
        checkpoint_naive = checkpoint_dt.replace(tzinfo=None) if checkpoint_dt.tzinfo else checkpoint_dt
        return due_date < checkpoint_naive
    except (ValueError, TypeError):
        return False  # 不正な日付形式 → 期限未設定として扱う


def _is_blank_due_at(issue, checkpoint_dt, status_map):
    """指定時点でチケットが期限未設定かどうかを判定する。

    条件:
    - due_dateが空欄（未設定）である
    - 指定時点のステータスが未完了（CLOSED_STATUSES以外）である
    - チケットが指定時点で作成済みである

    Args:
        issue: チケットdict（due_date, status, journals等を含む）
        checkpoint_dt: 判定時点のdatetime
        status_map: ステータスID→名前マッピング

    Returns:
        True: 期限未設定かつ未完了, False: それ以外
    """
    # ステータスを復元
    status_raw = get_status_at(issue, checkpoint_dt)
    if status_raw is None:
        return False  # まだ作成されていない
    status_name = resolve_status_name(status_raw, status_map)
    if status_name in CLOSED_STATUSES:
        return False  # 完了済み

    # due_dateの確認
    due_date_str = issue.get("due_date")
    if not due_date_str or not due_date_str.strip():
        return True  # 期限未設定かつ未完了

    # 不正な日付形式も期限未設定として扱う
    try:
        datetime.strptime(due_date_str, "%Y-%m-%d")
        return False  # 有効な日付がある → blank_dueではない
    except (ValueError, TypeError):
        return True  # パース失敗 → 期限未設定として扱う


# --- 集計 ---

def aggregate_data(projects_issues, status_map):
    """全プロジェクトのチケットを3定点×トラッカー別に集計する（全体＋プロジェクト別）"""
    checkpoints = get_checkpoints()
    # 全体集計: {tracker: {checkpoint_label: {status: count}}}
    tracker_stats = {}
    # プロジェクト別集計: {project_id: {tracker: {checkpoint_label: {status: count}}}}
    per_project_stats = {}
    # 成果物の予実データ（全体）
    deliverable_data = []
    # プロジェクト別成果物
    per_project_deliverables = {}

    for tracker_name in TARGET_TRACKERS:
        tracker_stats[tracker_name] = {}
        for label, _ in checkpoints:
            tracker_stats[tracker_name][label] = defaultdict(int)

    for project_id, issues in projects_issues.items():
        per_project_stats[project_id] = {}
        per_project_deliverables[project_id] = []
        for tracker_name in TARGET_TRACKERS:
            per_project_stats[project_id][tracker_name] = {}
            for label, _ in checkpoints:
                per_project_stats[project_id][tracker_name][label] = defaultdict(int)

        for issue in issues:
            tracker = issue.get("tracker", {}).get("name", "")
            if tracker not in TARGET_TRACKERS:
                continue

            for label, dt in checkpoints:
                status = get_status_at(issue, dt)
                if status is None:
                    continue
                status = resolve_status_name(status, status_map)
                tracker_stats[tracker][label][status] += 1
                per_project_stats[project_id][tracker][label][status] += 1

            # 成果物の予実データ
            if tracker == "成果物":
                entry = {
                    "id": issue["id"],
                    "subject": issue.get("subject", ""),
                    "project": project_id,
                    "due_date": issue.get("due_date"),
                    "done_ratio": issue.get("done_ratio", 0),
                    "status": issue.get("status", {}).get("name", "不明"),
                    "ratios": {},
                }
                for label, dt in checkpoints:
                    r = get_done_ratio_at(issue, dt)
                    entry["ratios"][label] = r if r is not None else 0
                deliverable_data.append(entry)
                per_project_deliverables[project_id].append(entry)

    return tracker_stats, deliverable_data, checkpoints, per_project_stats, per_project_deliverables


# --- Risk_Score算出・トレンド判定・AI考察対象決定 ---

def compute_risk_scores(projects_issues, checkpoints, status_map):
    """各プロジェクト・各CheckpointのRisk_Scoreを算出する。

    Risk_Score = Overdue_Count + Blank_Due_Count
    - Overdue_Count: due_date < Checkpoint日 かつ ステータスが未完了のチケット数
    - Blank_Due_Count: due_date が空欄 かつ ステータスが未完了のチケット数
    - 未完了 = ステータスが「解決」「終了」「却下」以外

    対象トラッカー: 課題、Q/A のみ

    Args:
        projects_issues: {project_id: [issue_dict, ...]}
        checkpoints: [(label, datetime), ...] 4定点
        status_map: ステータスID→名前マッピング

    Returns:
        {project_id: [risk_score_3w, risk_score_2w, risk_score_1w, risk_score_now]}
    """
    risk_target_trackers = {"課題", "Q/A"}
    result = {}

    for pid, issues in projects_issues.items():
        scores = []
        for _label, cp_dt in checkpoints:
            overdue = 0
            blank_due = 0
            for issue in issues:
                tracker_name = issue.get("tracker", {}).get("name", "")
                if tracker_name not in risk_target_trackers:
                    continue
                if _is_overdue_at(issue, cp_dt, status_map):
                    overdue += 1
                elif _is_blank_due_at(issue, cp_dt, status_map):
                    blank_due += 1
            scores.append(overdue + blank_due)
        result[pid] = scores

    return result


def detect_deadline_risk(risk_scores):
    """4定点のRisk_Score推移から上昇傾向を判定する。

    判定ロジック:
    - 3区間（3w→2w, 2w→1w, 1w→now）のうち2区間以上でRisk_Scoreが増加 → True
    - 4定点すべてRisk_Score=0 → False

    Args:
        risk_scores: {project_id: [score_3w, score_2w, score_1w, score_now]}

    Returns:
        {project_id: True/False}
    """
    result = {}
    for pid, scores in risk_scores.items():
        # 4定点すべて0 → 上昇傾向ではない
        if all(s == 0 for s in scores):
            result[pid] = False
            continue

        # 3区間の増加判定
        increases = 0
        for i in range(len(scores) - 1):
            if scores[i + 1] > scores[i]:
                increases += 1

        result[pid] = increases >= 2

    return result


def resolve_ai_targets(project_ids, ai_flags, deadline_risk, ai_max=10):
    """AI考察対象プロジェクトを決定する。

    優先順位:
    1. CSVのai_flag=Trueのプロジェクト（project_idsの順序で）
    2. Deadline_Risk_Flag=Trueのプロジェクト（project_idsの順序で）
    重複は除外し、合計ai_max件まで。

    Args:
        project_ids: 全プロジェクトIDリスト（CSV + 自動抽出）
        ai_flags: {pid: bool} CSVのai_flag
        deadline_risk: {pid: bool} detect_deadline_riskの戻り値
        ai_max: AI考察の上限（デフォルト: 10）

    Returns:
        AI考察対象のプロジェクトIDセット
    """
    targets = []
    seen = set()

    # 1. ai_flag=Trueのプロジェクトを優先
    for pid in project_ids:
        if len(targets) >= ai_max:
            break
        if ai_flags.get(pid) and pid not in seen:
            targets.append(pid)
            seen.add(pid)

    # 2. Deadline_Risk_Flag=Trueのプロジェクトを追加
    for pid in project_ids:
        if len(targets) >= ai_max:
            break
        if deadline_risk.get(pid) and pid not in seen:
            targets.append(pid)
            seen.add(pid)

    return set(targets)


# --- HTML生成 ---

def _render_tracker_table(tracker_name, stats, checkpoint_labels, checkpoint_dates):
    """トラッカー別ステータス推移テーブルのHTMLを生成する"""
    parts = []
    parts.append(f'<div class="section"><h3>{tracker_name} — ステータス推移</h3>')
    parts.append('<table><thead><tr><th class="th-primary">ステータス</th>')
    for label, date_str in zip(checkpoint_labels, checkpoint_dates):
        parts.append(f'<th class="th-secondary">{label}<br>({date_str})</th>')
    parts.append('<th class="th-secondary">増減</th></tr></thead><tbody>')

    tracker_statuses = set()
    for label in checkpoint_labels:
        tracker_statuses.update(stats.get(label, {}).keys())
    tracker_statuses = sorted(tracker_statuses)

    for status in tracker_statuses:
        parts.append(f'<tr><td style="text-align:left;font-weight:var(--font-weight-bold);">{status}</td>')
        values = []
        for label in checkpoint_labels:
            val = stats.get(label, {}).get(status, 0)
            values.append(val)
            parts.append(f'<td>{val if val > 0 else "-"}</td>')
        first_val = next((v for v in values if v > 0), None)
        last_val = next((v for v in reversed(values) if v > 0), None)
        if first_val is not None and last_val is not None:
            diff = last_val - first_val
            if diff > 0:
                parts.append(f'<td class="trend-up">+{diff}</td>')
            elif diff < 0:
                parts.append(f'<td class="trend-down">{diff}</td>')
            else:
                parts.append('<td class="trend-flat">±0</td>')
        else:
            parts.append('<td class="trend-flat">-</td>')
        parts.append('</tr>')

    # 合計行
    parts.append('<tr class="row-total"><td style="text-align:left;">合計</td>')
    totals = []
    for label in checkpoint_labels:
        t = sum(stats.get(label, {}).values())
        totals.append(t)
        parts.append(f'<td>{t if t > 0 else "-"}</td>')
    first_t = next((v for v in totals if v > 0), None)
    last_t = next((v for v in reversed(totals) if v > 0), None)
    if first_t is not None and last_t is not None:
        diff = last_t - first_t
        if diff > 0:
            parts.append(f'<td class="trend-up">+{diff}</td>')
        elif diff < 0:
            parts.append(f'<td class="trend-down">{diff}</td>')
        else:
            parts.append('<td class="trend-flat">±0</td>')
    else:
        parts.append('<td class="trend-flat">-</td>')
    parts.append('</tr></tbody></table></div>')
    return "\n".join(parts)


def _render_deliverable_table(deliverable_data, checkpoint_labels, checkpoint_dates):
    """成果物のサマリーバー + ガントチャート風タイムラインHTMLを生成する"""
    if not deliverable_data:
        return ""
    today = datetime.now(JST).date()
    parts = ['<div class="sec"><h3>成果物 — 予実管理</h3>']

    # サマリー集計
    completed = 0
    in_progress = 0
    overdue = 0
    no_due = 0
    for d in deliverable_data:
        done = d.get("done_ratio", 0)
        due = d.get("due_date")
        if done >= 100:
            completed += 1
        elif due:
            try:
                if datetime.strptime(due, "%Y-%m-%d").date() < today and done < 100:
                    overdue += 1
                else:
                    in_progress += 1
            except ValueError:
                in_progress += 1
        else:
            no_due += 1
    total = len(deliverable_data)

    # サマリーバー
    parts.append('<div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;">')
    bar_items = [
        (completed, "完了", "var(--c-ok1)"),
        (in_progress, "進行中", "var(--c-b6)"),
        (overdue, "遅延", "#B40000"),
        (no_due, "期日未設定", "var(--c-g3)"),
    ]
    for count, label, color in bar_items:
        if count == 0:
            continue
        parts.append(
            f'<div style="display:flex;align-items:center;gap:6px;font:var(--fw) 14px/1.3 var(--ff);">'
            f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:{color};"></span>'
            f'<strong>{count}</strong> {label}</div>')
    parts.append(f'<div style="font:var(--fw) 14px/1.3 var(--ff);color:var(--c-g5);margin-left:auto;">合計 {total}件</div>')
    parts.append('</div>')

    # ステータスバー（横棒）
    if total > 0:
        parts.append('<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:20px;background:var(--c-g2);">')
        for count, _, color in bar_items:
            if count == 0:
                continue
            pct = count / total * 100
            parts.append(f'<div style="width:{pct:.1f}%;background:{color};"></div>')
        parts.append('</div>')

    # ガントチャート用の日付範囲を計算
    dated_items = []
    undated_items = []
    for d in deliverable_data:
        if d.get("due_date"):
            dated_items.append(d)
        else:
            undated_items.append(d)

    if dated_items:
        # タイムライン範囲: 最も古い作成日〜最も遠い期日（+余白）
        all_dues = []
        for d in dated_items:
            try:
                all_dues.append(datetime.strptime(d["due_date"], "%Y-%m-%d").date())
            except ValueError:
                pass
        if all_dues:
            timeline_start = min(today - timedelta(days=28), min(all_dues) - timedelta(days=7))
            timeline_end = max(today + timedelta(days=7), max(all_dues) + timedelta(days=7))
            timeline_days = (timeline_end - timeline_start).days
            if timeline_days < 1:
                timeline_days = 1

            # SVGガントチャート
            row_h = 32
            pad_l = 200
            pad_r = 20
            pad_t = 30
            chart_w = 560
            bar_area_w = chart_w - pad_l - pad_r
            svg_h = pad_t + len(dated_items) * row_h + 20

            parts.append(f'<svg viewBox="0 0 {chart_w} {svg_h}" style="width:100%;max-width:{chart_w}px;height:auto;" role="img" aria-label="成果物ガントチャート">')

            # 今日の線
            today_x = pad_l + (today - timeline_start).days / timeline_days * bar_area_w
            parts.append(f'<line x1="{today_x:.1f}" y1="{pad_t-10}" x2="{today_x:.1f}" y2="{svg_h-10}" stroke="#B40000" stroke-width="1.5" stroke-dasharray="4,3"/>')
            parts.append(f'<text x="{today_x:.1f}" y="{pad_t-14}" text-anchor="middle" font-size="10" fill="#B40000" font-family="\'Noto Sans JP\',sans-serif">今日</text>')

            # 月の区切り線とラベル
            d_cursor = timeline_start.replace(day=1)
            while d_cursor <= timeline_end:
                if d_cursor >= timeline_start:
                    mx = pad_l + (d_cursor - timeline_start).days / timeline_days * bar_area_w
                    parts.append(f'<line x1="{mx:.1f}" y1="{pad_t-5}" x2="{mx:.1f}" y2="{svg_h-10}" stroke="#D9DCE2" stroke-width="0.5"/>')
                    parts.append(f'<text x="{mx+2:.1f}" y="{pad_t-2}" font-size="9" fill="#6B7682" font-family="\'Noto Sans JP\',sans-serif">{d_cursor.strftime("%m/%d")}</text>')
                if d_cursor.month == 12:
                    d_cursor = d_cursor.replace(year=d_cursor.year+1, month=1)
                else:
                    d_cursor = d_cursor.replace(month=d_cursor.month+1)

            # 各成果物のバー
            for idx, d in enumerate(sorted(dated_items, key=lambda x: x.get("due_date", "9999"))):
                y = pad_t + idx * row_h
                done = d.get("done_ratio", 0)
                due_str = d.get("due_date", "")
                subject = d.get("subject", "")[:18]
                try:
                    due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                is_overdue = due_date < today and done < 100

                # ラベル
                label_color = "#B40000" if is_overdue else "#3D454D"
                parts.append(f'<text x="{pad_l-6}" y="{y+20}" text-anchor="end" font-size="11" fill="{label_color}" font-family="\'Noto Sans JP\',sans-serif">#{d["id"]} {subject}</text>')

                # 予定バー（作成日〜期日）
                bar_start_x = pad_l
                bar_end_x = pad_l + (due_date - timeline_start).days / timeline_days * bar_area_w
                bar_w = max(bar_end_x - bar_start_x, 4)
                parts.append(f'<rect x="{bar_start_x:.1f}" y="{y+10}" width="{bar_w:.1f}" height="14" fill="#D9DCE2" rx="3"><title>予定: 〜{due_str}</title></rect>')

                # 実績バー（進捗率分）
                actual_w = bar_w * done / 100
                if done >= 100:
                    fill = "var(--c-ok1)"
                elif is_overdue:
                    fill = "#B40000"
                else:
                    fill = "var(--c-b6)"
                if actual_w > 0:
                    parts.append(f'<rect x="{bar_start_x:.1f}" y="{y+10}" width="{actual_w:.1f}" height="14" fill="{fill}" rx="3"><title>実績: {done}%</title></rect>')

                # 進捗率ラベル
                label_x = bar_start_x + bar_w + 4
                parts.append(f'<text x="{label_x:.1f}" y="{y+21}" font-size="10" fill="{label_color}" font-weight="700" font-family="\'Noto Sans JP\',sans-serif">{done}%</text>')

                # 期日マーカー
                due_x = bar_end_x
                parts.append(f'<line x1="{due_x:.1f}" y1="{y+8}" x2="{due_x:.1f}" y2="{y+26}" stroke="{label_color}" stroke-width="1.5"/>')

            parts.append('</svg>')

    # 期日未設定の成果物
    if undated_items:
        parts.append('<div style="margin-top:12px;font:var(--fw) 14px/1.3 var(--ff);color:var(--c-g5);">')
        parts.append('<strong>期日未設定:</strong> ')
        items_str = ", ".join(f'#{d["id"]} {d.get("subject","")}' for d in undated_items)
        parts.append(f'{items_str}</div>')

    parts.append('</div>')
    return "\n".join(parts)


def _get_latest_progress_report(issues):
    """最新の進捗報告チケットの説明文またはコメントを取得する"""
    now = datetime.now(JST)
    progress_issues = []
    for issue in issues:
        if issue.get("tracker", {}).get("name") != "進捗報告":
            continue
        updated = parse_datetime(issue.get("updated_on"))
        progress_issues.append((updated or now, issue))
    if not progress_issues:
        return None, None
    progress_issues.sort(key=lambda x: x[0], reverse=True)
    latest = progress_issues[0][1]
    # 最新のコメント（journals）があればそれを使う、なければ説明文
    journals = latest.get("journals", [])
    notes_journals = [j for j in journals if j.get("notes")]
    if notes_journals:
        notes_journals.sort(key=lambda j: j.get("created_on", ""), reverse=True)
        text = notes_journals[0].get("notes", "")
        author = notes_journals[0].get("user", {}).get("name", "不明")
        date_str = parse_datetime(notes_journals[0].get("created_on"))
        date_label = date_str.strftime("%Y/%m/%d") if date_str else ""
    else:
        text = latest.get("description", "")
        author = latest.get("author", {}).get("name", "不明")
        date_str = parse_datetime(latest.get("updated_on"))
        date_label = date_str.strftime("%Y/%m/%d") if date_str else ""
    return {
        "id": latest["id"],
        "subject": latest.get("subject", ""),
        "text": text,
        "author": author,
        "date": date_label,
    }, latest


def _render_progress_report(issues):
    """最新の進捗報告セクションHTMLを生成する"""
    report, _ = _get_latest_progress_report(issues)
    if not report or not report["text"]:
        return ""
    text = report["text"]
    truncated = len(text) > 300
    display_text = text[:300] if truncated else text
    # 改行をbrタグに変換
    display_text = display_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    full_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>") if truncated else ""

    uid = f"progress-{report['id']}"
    parts = [
        '<div class="sec"><h3>📋 プロマネ報告（最新の進捗報告）</h3>',
        f'<p style="font:var(--fw) 12px/1.3 var(--ff);color:var(--c-g5);margin-bottom:8px;">'
        f'#{report["id"]} {report["subject"]} ｜ {report["author"]} ｜ {report["date"]}</p>',
        f'<div style="font:var(--fw) 14px/1.7 var(--ff);color:var(--c-g7);background:var(--c-g50);'
        f'border-radius:var(--r);padding:12px;border-left:3px solid var(--c-g3);">',
        f'<span id="{uid}-short">{display_text}',
    ]
    if truncated:
        parts.append(
            f'<br><button onclick="document.getElementById(\'{uid}-short\').style.display=\'none\';'
            f'document.getElementById(\'{uid}-full\').style.display=\'inline\';" '
            f'style="font:var(--fb) 12px/1 var(--ff);color:var(--c-b7);background:none;border:none;'
            f'cursor:pointer;text-decoration:underline;margin-top:4px;">続きを読む</button>')
        parts.append(f'</span><span id="{uid}-full" style="display:none;">{full_text}</span>')
    else:
        parts.append('</span>')
    parts.append('</div></div>')
    return "\n".join(parts)


def _get_recent_issue_topics(issues, max_count=3):
    """直近1週間で更新された課題チケットのタイトルを取得する"""
    now = datetime.now(JST)
    one_week_ago = now - timedelta(weeks=1)
    recent = []
    for issue in issues:
        if issue.get("tracker", {}).get("name") != "課題":
            continue
        updated = parse_datetime(issue.get("updated_on"))
        if updated and updated >= one_week_ago:
            recent.append((updated, issue))
    recent.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in recent[:max_count]]


def _render_recent_topics(issues):
    """直近1週間の課題トピックHTMLを生成する"""
    topics = _get_recent_issue_topics(issues)
    if not topics:
        return '<div class="sec"><h3>課題トピック（直近1週間）</h3><p style="color:var(--c-g5);font:var(--fw) 14px/1.3 var(--ff);">直近1週間に更新された課題はありません。</p></div>'
    parts = ['<div class="sec"><h3>課題トピック（直近1週間）</h3><ul style="list-style:none;padding:0;">']
    for issue in topics:
        sid = issue["id"]
        subj = issue.get("subject", "")
        status = issue.get("status", {}).get("name", "")
        priority = issue.get("priority", {}).get("name", "")
        assignee = issue.get("assigned_to", {}).get("name", "未割当")
        parts.append(
            f'<li style="padding:8px 0;border-bottom:1px solid var(--c-g2);font:var(--fw) 14px/1.5 var(--ff);">'
            f'<strong>#{sid}</strong> {subj}'
            f'<br><span style="color:var(--c-g5);font-size:12px;">{status} ｜ {priority} ｜ {assignee}</span></li>')
    parts.append('</ul></div>')
    return "\n".join(parts)


def _render_ai_placeholder(project_id, project_name, issues, tracker_stats, rpm_info=None, risk_scores=None, deadline_risk=None):
    """AI考察プレースホルダーHTMLを生成する"""
    if risk_scores is None:
        risk_scores = {}
    if deadline_risk is None:
        deadline_risk = {}
    # Kiroが後から考察テキストを挿入するためのプレースホルダー
    # data属性にプロジェクト情報を埋め込み、Kiroが識別できるようにする
    topics = _get_recent_issue_topics(issues)
    topic_titles = "; ".join(f"#{t['id']} {t.get('subject','')}" for t in topics)

    # 集計サマリーをdata属性に埋め込む
    summary_parts = []
    for tn in ["課題", "Q/A", "サポート", "成果物"]:
        cur = tracker_stats.get(tn, {}).get("現在", {})
        total = sum(cur.values())
        closed = cur.get("解決", 0) + cur.get("終了", 0)
        summary_parts.append(f"{tn}:{total}件(解決終了:{closed})")

    # 進捗報告の最新テキストを埋め込む（先頭500文字）
    report, _ = _get_latest_progress_report(issues)
    report_text = ""
    if report and report["text"]:
        report_text = report["text"][:500].replace('"', '&quot;').replace('\n', ' ')

    # rpm.csv情報を埋め込む
    rpm_summary = ""
    if rpm_info:
        rpm_parts = []
        for k in ["工程", "状況", "進捗状況", "進捗率", "影響度区分", "完了予定日", "サービスイン予定日"]:
            v = rpm_info.get(k, "")
            if v:
                rpm_parts.append(f"{k}:{v}")
        rpm_summary = ", ".join(rpm_parts).replace('"', '&quot;')

    # data-risk-scores属性（Deadline_Risk_Flagプロジェクトの場合）
    risk_scores_attr = ''
    if deadline_risk.get(project_id):
        scores_list = risk_scores.get(project_id, [0, 0, 0, 0])
        risk_scores_attr = f' data-risk-scores="{",".join(str(s) for s in scores_list)}"'

    return (
        f'<div class="sec" id="ai-insight-{project_id}" '
        f'data-project="{project_id}" '
        f'data-project-name="{project_name}" '
        f'data-recent-topics="{topic_titles}" '
        f'data-summary="{", ".join(summary_parts)}" '
        f'data-progress-report="{report_text}" '
        f'data-rpm="{rpm_summary}"{risk_scores_attr}>'
        f'<h3>🤖 AI考察</h3>'
        f'<div class="ai-content" style="font:var(--fw) 14px/1.7 var(--ff);color:var(--c-g7);'
        f'background:var(--c-b1);border-radius:var(--r);padding:16px;border-left:4px solid var(--c-b7);">'
        f'<p style="color:var(--c-g5);font-style:italic;">Kiroによる考察が挿入されます。'
        f'ダッシュボード生成後、Kiroに「AI考察を生成して」と指示してください。</p>'
        f'</div></div>')


def _render_risk_score_table(pid, risk_scores, checkpoints):
    """詳細ページ用のRisk_Score推移テーブルHTMLを生成する。

    4定点のRisk_Score推移を数値テーブルとして表示する。

    Args:
        pid: プロジェクトID
        risk_scores: {project_id: [score_3w, score_2w, score_1w, score_now]}
        checkpoints: [(label, datetime), ...]

    Returns:
        Risk_Score推移テーブルのHTML文字列。データがない場合は空文字列。
    """
    scores = risk_scores.get(pid)
    if not scores:
        return ""
    checkpoint_labels = [c[0] for c in checkpoints]
    checkpoint_dates = [c[1].strftime("%m/%d") for c in checkpoints]

    parts = []
    parts.append('<div class="sec"><h3>⚠ 期限リスクスコア推移</h3>')
    parts.append('<table><thead><tr><th class="tp">指標</th>')
    for label, date_str in zip(checkpoint_labels, checkpoint_dates):
        parts.append(f'<th class="ts">{label}<br>({date_str})</th>')
    parts.append('<th class="ts">増減</th></tr></thead><tbody>')

    # Risk_Score行
    parts.append('<tr><td style="text-align:left;font-weight:var(--font-weight-bold);">Risk_Score<br><span style="font-size:11px;color:var(--c-g5);">(期限超過+期限未設定)</span></td>')
    for s in scores:
        if s > 0:
            parts.append(f'<td style="font-weight:var(--fb);color:var(--c-er2);">{s}</td>')
        else:
            parts.append('<td>0</td>')
    # 増減
    first_val = scores[0]
    last_val = scores[-1]
    diff = last_val - first_val
    if diff > 0:
        parts.append(f'<td class="trend-up" style="color:var(--c-er2);font-weight:var(--fb);">+{diff}</td>')
    elif diff < 0:
        parts.append(f'<td class="trend-down" style="color:var(--c-ok2);font-weight:var(--fb);">{diff}</td>')
    else:
        parts.append('<td class="trend-flat">±0</td>')
    parts.append('</tr>')

    # トレンド行
    parts.append('<tr><td style="text-align:left;">トレンド</td>')
    for i in range(len(scores)):
        if i == 0:
            parts.append('<td>-</td>')
        else:
            d = scores[i] - scores[i - 1]
            if d > 0:
                parts.append(f'<td style="color:var(--c-er2);">↑+{d}</td>')
            elif d < 0:
                parts.append(f'<td style="color:var(--c-ok2);">↓{d}</td>')
            else:
                parts.append('<td style="color:var(--c-g5);">→±0</td>')
    parts.append('<td>-</td></tr>')

    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_filter_sort_js():
    """フィルタ・ソート用のインラインJavaScriptを生成する。

    機能:
    - テーブルID「project-list-table」を対象
    - 各列ヘッダー直下の <input class="col-filter"> による部分一致フィルタ（indexOf使用）
    - 複数列のAND条件フィルタ
    - 列ヘッダークリックによる3段階ソート（none → asc → desc → none）
    - 数値列は数値比較ソート、テキスト列はlocaleCompareによる文字列比較
    - ソートインジケーター（▲/▼）表示
    - 元の順序を data-original-index で保持し、ソート解除時に復元
    - 空文字はソート時に最後尾に配置
    - フィルタ入力欄にデジタル庁デザインシステムv2準拠のスタイルを適用
    - キーボード操作（Tab移動、Enter確定）に対応
    - 外部ライブラリに依存しない

    Returns:
        インラインJavaScript文字列
    """
    return """
(function(){
  var table = document.getElementById('project-list-table');
  if (!table) return;
  var thead = table.querySelector('thead');
  var tbody = table.querySelector('tbody');
  if (!thead || !tbody) return;

  // ソート状態: {col: number, dir: 'asc'|'desc'|'none'}
  var sortState = {col: -1, dir: 'none'};

  // 数値列の判定用インデックスセット（ヘッダーテキストで判定）
  var numCols = {};
  var headers = thead.querySelectorAll('tr:first-child th');
  for (var i = 0; i < headers.length; i++) {
    var txt = headers[i].textContent.trim();
    if (['チケット数','課題','Q/A','サポート','成果物'].indexOf(txt) >= 0) {
      numCols[i] = true;
    }
  }

  // フィルタ処理
  function applyFilters() {
    var filters = table.querySelectorAll('input.col-filter');
    var rows = tbody.querySelectorAll('tr');
    for (var r = 0; r < rows.length; r++) {
      var show = true;
      var cells = rows[r].querySelectorAll('td');
      for (var f = 0; f < filters.length; f++) {
        var val = filters[f].value.toLowerCase();
        if (!val) continue;
        var colIdx = parseInt(filters[f].getAttribute('data-col'), 10);
        if (colIdx >= cells.length) { show = false; break; }
        var cellText = cells[colIdx].textContent.toLowerCase();
        if (cellText.indexOf(val) < 0) { show = false; break; }
      }
      rows[r].style.display = show ? '' : 'none';
    }
  }

  // フィルタ入力イベント
  var filterInputs = table.querySelectorAll('input.col-filter');
  for (var fi = 0; fi < filterInputs.length; fi++) {
    filterInputs[fi].addEventListener('input', applyFilters);
    filterInputs[fi].addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { applyFilters(); }
    });
    // フィルタ入力欄のクリックでソートが発火しないようにする
    filterInputs[fi].addEventListener('click', function(e) { e.stopPropagation(); });
  }

  // ソートインジケーター更新
  function updateIndicators() {
    for (var i = 0; i < headers.length; i++) {
      var ind = headers[i].querySelector('.sort-ind');
      if (ind) {
        if (sortState.col === i) {
          ind.textContent = sortState.dir === 'asc' ? ' \\u25B2' : sortState.dir === 'desc' ? ' \\u25BC' : '';
        } else {
          ind.textContent = '';
        }
      }
    }
  }

  // ソートインジケーター要素を各ヘッダーに追加
  for (var si = 0; si < headers.length; si++) {
    var span = document.createElement('span');
    span.className = 'sort-ind';
    span.style.fontSize = '11px';
    span.style.marginLeft = '2px';
    headers[si].appendChild(span);
    headers[si].style.cursor = 'pointer';
    headers[si].setAttribute('data-col-idx', si);
    headers[si].addEventListener('click', function() {
      var colIdx = parseInt(this.getAttribute('data-col-idx'), 10);
      sortTable(colIdx);
    });
  }

  // ソート処理
  function sortTable(colIdx) {
    // 3段階トグル
    if (sortState.col === colIdx) {
      if (sortState.dir === 'asc') sortState.dir = 'desc';
      else if (sortState.dir === 'desc') { sortState.dir = 'none'; sortState.col = -1; }
      else sortState.dir = 'asc';
    } else {
      sortState.col = colIdx;
      sortState.dir = 'asc';
    }

    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

    if (sortState.dir === 'none') {
      // 元の順序に復元
      rows.sort(function(a, b) {
        var ai = parseInt(a.getAttribute('data-original-index'), 10) || 0;
        var bi = parseInt(b.getAttribute('data-original-index'), 10) || 0;
        return ai - bi;
      });
    } else {
      var isNum = !!numCols[colIdx];
      var asc = sortState.dir === 'asc';
      rows.sort(function(a, b) {
        var ac = a.querySelectorAll('td');
        var bc = b.querySelectorAll('td');
        var av = colIdx < ac.length ? ac[colIdx].textContent.trim() : '';
        var bv = colIdx < bc.length ? bc[colIdx].textContent.trim() : '';
        // 空文字は最後尾
        if (av === '' && bv === '') return 0;
        if (av === '') return 1;
        if (bv === '') return -1;
        var result;
        if (isNum) {
          var an = parseFloat(av.replace(/[^\\d.\\-]/g, '')) || 0;
          var bn = parseFloat(bv.replace(/[^\\d.\\-]/g, '')) || 0;
          result = an - bn;
        } else {
          result = av.localeCompare(bv, 'ja');
        }
        return asc ? result : -result;
      });
    }

    // DOMに反映
    for (var i = 0; i < rows.length; i++) {
      tbody.appendChild(rows[i]);
    }
    updateIndicators();
  }
})();
"""


def _render_trend_chart(tracker_name, stats, checkpoint_labels, checkpoint_dates):
    """トラッカーの合計数と解決・終了数の折れ線グラフ（インラインSVG）を生成する"""
    total_counts = []
    closed_counts = []
    for label in checkpoint_labels:
        s = stats.get(label, {})
        total_counts.append(sum(s.values()))
        closed_counts.append(s.get("解決", 0) + s.get("終了", 0))

    max_val = max(total_counts) if total_counts else 0
    if max_val == 0:
        return ""

    w, h = 560, 240
    pad_l, pad_r, pad_t, pad_b = 40, 20, 30, 50
    chart_w = w - pad_l - pad_r
    chart_h = h - pad_t - pad_b
    n_points = len(checkpoint_labels)

    svg = [f'<svg viewBox="0 0 {w} {h}" style="width:100%;max-width:{w}px;height:auto;" role="img" aria-label="{tracker_name}の合計数と解決・終了数の推移グラフ">']

    for i in range(5):
        y = pad_t + chart_h - (chart_h * i / 4)
        val = int(max_val * i / 4)
        svg.append(f'<line x1="{pad_l}" y1="{y}" x2="{w-pad_r}" y2="{y}" stroke="#D9DCE2" stroke-width="1"/>')
        svg.append(f'<text x="{pad_l-6}" y="{y+4}" text-anchor="end" font-size="11" fill="#6B7682" font-family="\'Noto Sans JP\',sans-serif">{val}</text>')

    gap = chart_w / (n_points - 1) if n_points > 1 else 0

    def plot_line(counts, color, label_name):
        points = []
        for idx, val in enumerate(counts):
            x = pad_l + gap * idx
            y = pad_t + chart_h - (val / max_val * chart_h) if max_val > 0 else pad_t + chart_h
            points.append((x, y, val))
        line_points = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in points)
        svg.append(f'<polyline points="{line_points}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>')
        for x, y, val in points:
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="#FFF" stroke-width="1.5"><title>{label_name}: {val}件</title></circle>')
            svg.append(f'<text x="{x:.1f}" y="{y-10:.1f}" text-anchor="middle" font-size="11" fill="{color}" font-weight="700" font-family="\'Noto Sans JP\',sans-serif">{val}</text>')

    plot_line(total_counts, "#0072EF", f"{tracker_name}合計")
    plot_line(closed_counts, "#259D63", "解決・終了")

    for idx, (label, date_str) in enumerate(zip(checkpoint_labels, checkpoint_dates)):
        x = pad_l + gap * idx
        svg.append(f'<text x="{x:.1f}" y="{h-pad_b+16}" text-anchor="middle" font-size="12" fill="#3D454D" font-family="\'Noto Sans JP\',sans-serif">{label}</text>')
        svg.append(f'<text x="{x:.1f}" y="{h-pad_b+30}" text-anchor="middle" font-size="10" fill="#6B7682" font-family="\'Noto Sans JP\',sans-serif">({date_str})</text>')

    svg.append(f'<line x1="{pad_l}" y1="{pad_t-16}" x2="{pad_l+20}" y2="{pad_t-16}" stroke="#0072EF" stroke-width="2.5"/>')
    svg.append(f'<text x="{pad_l+24}" y="{pad_t-12}" font-size="10" fill="#3D454D" font-family="\'Noto Sans JP\',sans-serif">{tracker_name}合計</text>')
    lx = pad_l + len(tracker_name) * 12 + 40
    svg.append(f'<line x1="{lx}" y1="{pad_t-16}" x2="{lx+20}" y2="{pad_t-16}" stroke="#259D63" stroke-width="2.5"/>')
    svg.append(f'<text x="{lx+24}" y="{pad_t-12}" font-size="10" fill="#3D454D" font-family="\'Noto Sans JP\',sans-serif">解決・終了</text>')

    svg.append('</svg>')
    return f'<div style="margin-bottom:16px;">{"".join(svg)}</div>'


def generate_html(tracker_stats, deliverable_data, checkpoints, project_ids,
                   per_project_stats, per_project_deliverables, projects_issues,
                   project_names=None, ai_flags=None, rpm_data=None,
                   auto_extracted=None, risk_scores=None, deadline_risk=None,
                   ai_targets=None):
    """一覧ページ＋プロジェクト別詳細ページを含むHTMLダッシュボードを生成する"""
    if project_names is None:
        project_names = {}
    if ai_flags is None:
        ai_flags = {}
    if rpm_data is None:
        rpm_data = {}
    if auto_extracted is None:
        auto_extracted = set()
    if risk_scores is None:
        risk_scores = {}
    if deadline_risk is None:
        deadline_risk = {}
    if ai_targets is None:
        ai_targets = set()
    now = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")
    checkpoint_labels = [c[0] for c in checkpoints]
    checkpoint_dates = [c[1].strftime("%m/%d") for c in checkpoints]

    CSS = """
:root{--c-b9:#003875;--c-b8:#004B9E;--c-b7:#005FC6;--c-b6:#0072EF;--c-b1:#E8F4FF;
--c-w:#FFF;--c-bk:#000;--c-g50:#F7F8FA;--c-g1:#F0F1F4;--c-g2:#D9DCE2;--c-g3:#B4BAC5;
--c-g5:#6B7682;--c-g7:#3D454D;--c-g8:#1A1E23;--c-ok1:#259D63;--c-ok2:#1B7548;
--c-er2:#B40000;--c-wa1:#F09000;--ff:'Noto Sans JP',-apple-system,BlinkMacSystemFont,sans-serif;
--fw:400;--fb:700;--r:8px;--rs:4px;--sh:0 1px 2px rgba(0,0,0,.06),0 1px 3px rgba(0,0,0,.1);
--sh2:0 2px 4px rgba(0,0,0,.06),0 4px 6px rgba(0,0,0,.1)}
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
body{font:var(--fw) 16px/1.7 var(--ff);letter-spacing:.02em;color:var(--c-g8);background:var(--c-g50);padding:24px;max-width:1140px;margin:0 auto}
.hdr{border-bottom:3px solid var(--c-b7);padding-bottom:16px;margin-bottom:32px}
.hdr h1{font:var(--fb) 24px/1.5 var(--ff);color:var(--c-g8)}
.hdr .meta{font:var(--fw) 14px/1.3 var(--ff);color:var(--c-g5);margin-top:4px}
.sec{background:var(--c-w);border-radius:var(--r);padding:24px;margin-bottom:24px;box-shadow:var(--sh)}
.sec h2{font:var(--fb) 20px/1.5 var(--ff);color:var(--c-g8);margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid var(--c-b7)}
.sec h3{font:var(--fb) 18px/1.6 var(--ff);color:var(--c-g8);margin-bottom:12px}
table{width:100%;border-collapse:collapse;font:var(--fw) 14px/1.3 var(--ff)}
th,td{padding:8px 16px;text-align:center;border:1px solid var(--c-g2)}
th{font-weight:var(--fb);background:var(--c-g1);color:var(--c-g7)}
.tp{background:var(--c-b7);color:var(--c-w)}.ts{background:var(--c-b1);color:var(--c-b9)}
.rt{background:var(--c-g1)}.rt td{font-weight:var(--fb)}
.bc{display:flex;align-items:center;gap:4px}
.bt{flex:1;height:16px;background:var(--c-g2);border-radius:var(--rs);overflow:hidden}
.bf{height:100%;border-radius:var(--rs)}.bl{font:var(--fw) 14px/1.3 var(--ff);min-width:40px;text-align:right}
.tok{color:var(--c-ok2)}.ter{color:var(--c-er2);font-weight:var(--fb)}.tnt{color:var(--c-g5)}
.tu{color:var(--c-er2)}.td{color:var(--c-ok2)}.tf{color:var(--c-g5)}
.pg{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.pc{background:var(--c-w);border-radius:var(--r);padding:20px;box-shadow:var(--sh);border-left:4px solid var(--c-b7);cursor:pointer;transition:box-shadow .2s,transform .15s}
.pc:hover{box-shadow:var(--sh2);transform:translateY(-2px)}.pc:focus-visible{outline:2px solid var(--c-b6);outline-offset:2px}
.pc h3{font:var(--fb) 18px/1.6 var(--ff);color:var(--c-b8);margin-bottom:8px}
.pc .cm{font:var(--fw) 14px/1.3 var(--ff);color:var(--c-g5);margin-bottom:12px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font:var(--fb) 14px/1.3 var(--ff);padding:4px 12px;border-radius:var(--rs);background:var(--c-g1);color:var(--c-g7)}
.chip .cn{font-size:18px;margin-right:4px}.chip .cd{font-size:12px;margin-left:2px}
.bb{display:inline-flex;align-items:center;gap:6px;font:var(--fb) 16px/1.7 var(--ff);color:var(--c-b7);background:none;border:none;cursor:pointer;padding:8px 0;margin-bottom:16px;text-decoration:underline;text-underline-offset:3px}
.bb:hover{color:var(--c-b9)}.bb:focus-visible{outline:2px solid var(--c-b6);outline-offset:2px}
.page{display:none}.page.active{display:block}
  tbody tr[role="button"]:hover{background:var(--c-b1)}
  tbody tr[role="button"]:focus-visible{outline:2px solid var(--c-b6);outline-offset:-2px}
.ft{font:var(--fw) 14px/1.3 var(--ff);color:var(--c-g5);text-align:center;padding-top:24px;border-top:1px solid var(--c-g2);margin-top:32px}
"""

    h = []
    h.append(f'<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">')
    h.append(f'<meta name="viewport" content="width=device-width,initial-scale=1.0">')
    h.append(f'<title>Redmine ダッシュボード - {now}</title>')
    h.append(f'<style>{CSS}</style></head><body>')
    h.append(f'<header class="hdr"><h1>Redmine プロジェクトダッシュボード</h1>')
    h.append(f'<p class="meta">生成日時: {now} ｜ 対象プロジェクト: {len(project_ids)}件</p></header>')

    # ===== 一覧ページ =====
    # AI考察対象プロジェクトの特定（ai_targetsが渡されていればそれを使用）
    AI_MAX = 10
    ai_enabled_pids = ai_targets if ai_targets else set()
    if not ai_targets:
        # フォールバック: ai_flagsから上位AI_MAX件を選出
        ai_cnt = 0
        for pid in project_ids:
            if ai_flags.get(pid) and ai_cnt < AI_MAX:
                ai_enabled_pids.add(pid)
                ai_cnt += 1
    h.append('<div id="page-list" class="page active">')
    h.append('<section class="sec"><h2>プロジェクト一覧</h2>')
    # テーブルヘッダー
    tracker_cols = ["課題", "Q/A", "サポート", "成果物"]
    has_rpm = bool(rpm_data)
    h.append('<table id="project-list-table"><thead><tr>')
    h.append('<th class="tp" style="text-align:left;">プロジェクト</th>')
    if has_rpm:
        h.append('<th class="tp">影響度</th>')
        h.append('<th class="tp">重要案件</th>')
        h.append('<th class="tp">新領域</th>')
        h.append('<th class="tp">工程</th>')
        h.append('<th class="tp">着手年月</th>')
        h.append('<th class="tp">サービスイン</th>')
    h.append('<th class="tp">チケット数</th>')
    for tn in tracker_cols:
        h.append(f'<th class="ts">{tn}</th>')
    h.append('<th class="ts">期限リスク</th>')
    h.append('<th class="ts">AI</th>')
    h.append('</tr>')
    # フィルタ入力行
    col_count = 1 + (6 if has_rpm else 0) + 1 + len(tracker_cols) + 1 + 1  # プロジェクト + rpm列 + チケット数 + トラッカー列 + 期限リスク + AI
    h.append('<tr>')
    for ci in range(col_count):
        h.append(f'<td style="padding:4px 6px;"><input class="col-filter" data-col="{ci}" type="text" '
                 f'placeholder="フィルタ" aria-label="列{ci+1}のフィルタ" '
                 f'style="width:100%;padding:4px 8px;font:var(--fw) 12px/1.3 var(--ff);'
                 f'border:1px solid var(--c-g3);border-radius:var(--rs);background:var(--c-w);'
                 f'color:var(--c-g7);box-sizing:border-box;"></td>')
    h.append('</tr>')
    h.append('</thead><tbody>')
    for row_idx, pid in enumerate(project_ids):
        ic = len(projects_issues.get(pid, []))
        ps = per_project_stats.get(pid, {})
        pname = project_names.get(pid, pid)
        rpm = rpm_data.get(pid, {})
        ai_badge = '🤖' if pid in ai_enabled_pids else ''
        # 自動抽出バッジ
        auto_badge = ' <span style="display:inline-block;font-size:11px;padding:1px 6px;border-radius:var(--rs);background:#E8F4FF;color:var(--c-b7);font-weight:var(--fb);margin-left:4px;">🔍 自動抽出</span>' if pid in auto_extracted else ''
        # 期限リスクバッジ（プロジェクト名セルに表示）
        risk_badge = ''
        if deadline_risk.get(pid):
            scores_list = risk_scores.get(pid, [0, 0, 0, 0])
            trend_str = '→'.join(str(s) for s in scores_list)
            risk_badge = f' <span style="display:inline-block;font-size:11px;padding:1px 6px;border-radius:var(--rs);background:#FFF3E0;color:#B40000;font-weight:var(--fb);margin-left:4px;" title="Risk_Score推移: {trend_str}">⚠ 期限リスク</span>'
        h.append(f'<tr data-original-index="{row_idx}" style="cursor:pointer;" tabindex="0" role="button" aria-label="プロジェクト {pid} の詳細を表示" onclick="go(\'{pid}\')" onkeydown="if(event.key===\'Enter\')go(\'{pid}\')">')
        h.append(f'<td style="text-align:left;"><strong style="color:var(--c-b7);">{pname}</strong>{auto_badge}{risk_badge}<br><span style="font-size:12px;color:var(--c-g5);">{pid}</span></td>')
        if has_rpm:
            h.append(f'<td>{rpm.get("影響度区分", "-")}</td>')
            h.append(f'<td>{rpm.get("重要案件区分", "-")}</td>')
            h.append(f'<td>{rpm.get("新領域案件", "-")}</td>')
            h.append(f'<td>{rpm.get("工程", "-")}</td>')
            h.append(f'<td>{rpm.get("着手年月", "-")}</td>')
            h.append(f'<td>{rpm.get("サービスイン予定日", "-")}</td>')
        h.append(f'<td>{ic}</td>')
        for tn in tracker_cols:
            cur = ps.get(tn, {}).get("現在", {})
            tn_now = sum(cur.values())
            wa = ps.get(tn, {}).get("1週間前", {})
            tn_wa = sum(wa.values())
            df = tn_now - tn_wa
            if df > 0: diff_html = f' <span class="tu" style="font-size:11px;">+{df}</span>'
            elif df < 0: diff_html = f' <span class="td" style="font-size:11px;">{df}</span>'
            else: diff_html = ''
            h.append(f'<td>{tn_now}{diff_html}</td>')
        # 期限リスク列
        if deadline_risk.get(pid):
            scores_list = risk_scores.get(pid, [0, 0, 0, 0])
            trend_str = '→'.join(str(s) for s in scores_list)
            h.append(f'<td style="color:var(--c-er2);font-weight:var(--fb);" title="Risk_Score推移: {trend_str}">⚠ あり</td>')
        else:
            h.append('<td style="color:var(--c-g5);">-</td>')
        h.append(f'<td>{ai_badge}</td>')
        h.append('</tr>')
    h.append('</tbody></table>')
    h.append('</section>')

    h.append('</div>')

    # ===== 詳細ページ（プロジェクトごと） =====
    for pid in project_ids:
        ps = per_project_stats.get(pid, {})
        pd = per_project_deliverables.get(pid, [])
        ic = len(projects_issues.get(pid, []))
        h.append(f'<div id="page-{pid}" class="page">')
        h.append('<button class="bb" onclick="back()" aria-label="一覧に戻る">← 一覧に戻る</button>')
        pname = project_names.get(pid, pid)
        h.append(f'<section class="sec"><h2>{pname}</h2>')
        h.append(f'<p style="font:var(--fw) 14px/1.3 var(--ff);color:var(--c-g5);margin-bottom:16px;">{pid} ｜ チケット総数: {ic}件</p>')
        # rpm.csv属性情報
        rpm = rpm_data.get(pid, {})
        if rpm:
            rpm_display_fields = [
                ("本部", "本部"), ("部", "部"), ("案件No", "案件No"),
                ("子案件名", "子案件名"), ("影響度区分", "影響度区分"),
                ("重要案件区分", "重要案件区分"), ("新領域案件", "新領域案件"),
                ("案件種類", "案件種類"), ("工程", "工程"),
                ("コスト(工数)", "コスト(工数)"), ("状況", "状況"),
                ("進捗状況", "進捗状況"), ("コスト(工数)割合", "コスト(工数)割合"),
                ("進捗率", "進捗率"), ("開始日", "開始日"),
                ("完了予定日", "完了予定日"), ("完了実績日", "完了実績日"),
                ("着手年月", "着手年月"), ("サービスイン予定日", "サービスイン予定日"),
                ("進捗更新日", "進捗更新日"),
            ]
            h.append('<div style="background:var(--c-g50);border-radius:var(--r);padding:12px;margin-bottom:16px;font:var(--fw) 13px/1.5 var(--ff);display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:4px 16px;">')
            for label, key in rpm_display_fields:
                val = rpm.get(key, "")
                if val:
                    h.append(f'<div><span style="color:var(--c-g5);">{label}:</span> <strong>{val}</strong></div>')
            h.append('</div>')
        # プロマネ報告（最新の進捗報告）
        h.append(_render_progress_report(projects_issues.get(pid, [])))
        # 課題トピック（直近1週間）
        h.append(_render_recent_topics(projects_issues.get(pid, [])))
        # Risk_Score推移テーブル（期限リスクデータがある場合）
        h.append(_render_risk_score_table(pid, risk_scores, checkpoints))
        # AI考察（ai_targetsセットベース）
        if pid in ai_enabled_pids:
            h.append(_render_ai_placeholder(pid, pname, projects_issues.get(pid, []), ps, rpm_data.get(pid), risk_scores=risk_scores, deadline_risk=deadline_risk))
        # 折れ線グラフ（課題・Q/A・サポート）
        for tn in ["課題", "Q/A", "サポート"]:
            chart_html = _render_trend_chart(tn, ps.get(tn, {}), checkpoint_labels, checkpoint_dates)
            if chart_html:
                h.append(f'<div class="sec"><h3>{tn} — 合計数と解決・終了数の推移</h3>{chart_html}</div>')
        h.append(_render_deliverable_table(pd, checkpoint_labels, checkpoint_dates))
        h.append('</section></div>')

    h.append('<script>function go(p){document.querySelectorAll(".page").forEach(function(e){e.classList.remove("active")});var el=document.getElementById("page-"+p);if(el){el.classList.add("active");window.scrollTo(0,0)}}function back(){document.querySelectorAll(".page").forEach(function(e){e.classList.remove("active")});document.getElementById("page-list").classList.add("active");window.scrollTo(0,0)}</script>')
    h.append(f'<script>{_render_filter_sort_js()}</script>')
    h.append(f'<footer class="ft">デジタル庁デザインシステム v2 準拠 ｜ Redmine API Skill</footer>')
    h.append('</body></html>')
    return "\n".join(h)


# --- メイン ---

def main():
    parser = argparse.ArgumentParser(description="Redmine ダッシュボードレポート生成")
    parser.add_argument("csv", help="プロジェクトID一覧のCSVファイルパス")
    parser.add_argument("-o", "--output", default="dashboard.html", help="出力HTMLファイルパス（デフォルト: dashboard.html）")
    parser.add_argument("--rpm", default=None, help="プロジェクト補助データCSV（rpm.csv）のパス")
    args = parser.parse_args()

    # CSV読み込み
    print(f"CSVファイル読み込み: {args.csv}", file=sys.stderr)
    project_ids, ai_flags = load_project_ids(args.csv)
    if not project_ids:
        print("エラー: CSVからプロジェクトIDが読み込めませんでした。", file=sys.stderr)
        sys.exit(1)
    if len(project_ids) > MAX_PROJECTS:
        print(f"エラー: プロジェクト数が上限を超えています（{len(project_ids)}件 > 上限{MAX_PROJECTS}件）。", file=sys.stderr)
        print(f"CSVのプロジェクト数を{MAX_PROJECTS}件以下に減らしてください。", file=sys.stderr)
        sys.exit(1)
    print(f"対象プロジェクト: {len(project_ids)}件（上限{MAX_PROJECTS}件）", file=sys.stderr)

    # rpm.csv読み込み
    rpm_data = {}
    if args.rpm:
        print(f"rpm.csv読み込み: {args.rpm}", file=sys.stderr)
        rpm_data = load_rpm_data(args.rpm)
        print(f"  → {len(rpm_data)}件のプロジェクト補助データを取得", file=sys.stderr)

    # 自動抽出処理（--rpm指定時のみ）
    auto_extracted = set()
    if args.rpm and rpm_data:
        extracted_pids = auto_extract_projects(rpm_data, project_ids)
        for pid in extracted_pids:
            project_ids.append(pid)
            ai_flags[pid] = False
            auto_extracted.add(pid)

    # ステータスマッピング取得
    print("ステータス情報を取得中...", file=sys.stderr)
    status_map = fetch_status_map()

    # 各プロジェクトのチケット取得（サブプロジェクト含む）
    projects_issues = {}
    project_names = {}
    for pid in project_ids:
        print(f"プロジェクト '{pid}' のチケットを取得中...", file=sys.stderr)
        project_names[pid] = fetch_project_name(pid)
        issues = fetch_all_issues_with_subprojects(pid)
        projects_issues[pid] = issues
        print(f"  → {project_names[pid]}: {len(issues)}件取得（サブプロジェクト含む）", file=sys.stderr)

    # 集計
    print("データを集計中...", file=sys.stderr)
    tracker_stats, deliverable_data, checkpoints, per_project_stats, per_project_deliverables = aggregate_data(projects_issues, status_map)

    # Risk_Score算出・トレンド判定
    print("期限リスクを分析中...", file=sys.stderr)
    risk_scores = compute_risk_scores(projects_issues, checkpoints, status_map)
    deadline_risk = detect_deadline_risk(risk_scores)
    risk_count = sum(1 for v in deadline_risk.values() if v)
    print(f"  → 期限リスク検知: {risk_count}件", file=sys.stderr)

    # AI考察対象決定
    ai_targets = resolve_ai_targets(project_ids, ai_flags, deadline_risk)
    print(f"  → AI考察対象: {len(ai_targets)}件", file=sys.stderr)

    # HTML生成
    print("HTMLダッシュボードを生成中...", file=sys.stderr)
    html = generate_html(tracker_stats, deliverable_data, checkpoints, project_ids,
                          per_project_stats, per_project_deliverables, projects_issues,
                          project_names, ai_flags, rpm_data,
                          auto_extracted=auto_extracted,
                          risk_scores=risk_scores,
                          deadline_risk=deadline_risk,
                          ai_targets=ai_targets)

    # 出力
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"ダッシュボード出力完了: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
