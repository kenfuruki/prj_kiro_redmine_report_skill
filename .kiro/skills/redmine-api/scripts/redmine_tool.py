#!/usr/bin/env python3
"""
Redmine API ツール
環境変数 REDMINE_URL と REDMINE_API_KEY を使用してRedmine REST APIを操作する。
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse


def _load_env_file():
    """ワークスペースルートの .env ファイルを自動読み込みする。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "..", "..", "..", "..", ".env"),
        os.path.join(script_dir, "..", "..", "..", ".env"),
        os.path.join(script_dir, "..", ".env"),
        os.path.join(script_dir, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for env_path in candidates:
        env_path = os.path.normpath(env_path)
        if os.path.exists(env_path):
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip()
                            if key and not os.environ.get(key):
                                os.environ[key] = value
            except OSError:
                pass
            break


_load_env_file()


def get_config():
    """環境変数から設定を取得する"""
    url = os.environ.get("REDMINE_URL")
    key = os.environ.get("REDMINE_API_KEY")
    if not url or not key:
        print("エラー: 環境変数 REDMINE_URL と REDMINE_API_KEY を設定してください。", file=sys.stderr)
        print("  source .env  # bash の場合", file=sys.stderr)
        sys.exit(1)
    return url.rstrip("/"), key


def api_request(method, path, data=None):
    """Redmine APIリクエストを実行する"""
    base_url, api_key = get_config()
    url = f"{base_url}{path}"
    headers = {
        "X-Redmine-API-Key": api_key,
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        error_messages = {
            401: "認証エラー: APIキーが無効です。",
            403: "権限エラー: このリソースへのアクセス権がありません。",
            404: "未検出: 指定されたリソースが見つかりません。",
            422: f"バリデーションエラー: {error_body}",
        }
        msg = error_messages.get(e.code, f"HTTPエラー {e.code}: {error_body}")
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"接続エラー: {e.reason}", file=sys.stderr)
        sys.exit(1)


# --- チケット操作 ---

def list_issues(project=None, assigned_to=None, status="open", limit=25, offset=0):
    """チケット一覧を取得する"""
    params = {"limit": limit, "offset": offset, "status_id": status}
    if assigned_to:
        params["assigned_to_id"] = assigned_to
    path = f"/projects/{project}/issues.json" if project else "/issues.json"
    query = urllib.parse.urlencode(params)
    result = api_request("GET", f"{path}?{query}")
    issues = result.get("issues", [])
    total = result.get("total_count", 0)
    print(f"チケット一覧（{total}件中 {offset+1}〜{offset+len(issues)}件）:")
    for i in issues:
        assignee = i.get("assigned_to", {}).get("name", "未割当")
        print(f"  #{i['id']} [{i['status']['name']}] {i['priority']['name']} - {i['subject']} ({assignee})")
    return result


def get_issue(issue_id, include_journals=True):
    """チケット詳細を取得する"""
    includes = "journals,attachments" if include_journals else ""
    path = f"/issues/{issue_id}.json"
    if includes:
        path += f"?include={includes}"
    result = api_request("GET", path)
    issue = result.get("issue", {})
    print(f"チケット #{issue['id']}: {issue['subject']}")
    print(f"  ステータス: {issue['status']['name']}")
    print(f"  優先度: {issue['priority']['name']}")
    print(f"  担当者: {issue.get('assigned_to', {}).get('name', '未割当')}")
    print(f"  作成者: {issue.get('author', {}).get('name', '不明')}")
    print(f"  進捗率: {issue.get('done_ratio', 0)}%")
    if issue.get("due_date"):
        print(f"  期日: {issue['due_date']}")
    if issue.get("description"):
        print(f"  説明: {issue['description'][:200]}")
    journals = issue.get("journals", [])
    if journals:
        print(f"  コメント ({len(journals)}件):")
        for j in journals[-5:]:
            if j.get("notes"):
                print(f"    [{j.get('created_on', '')}] {j.get('user', {}).get('name', '不明')}: {j['notes'][:100]}")
    return result


def create_issue(project_id, subject, description="", tracker_id=None, priority_id=None, assigned_to_id=None):
    """チケットを作成する"""
    issue_data = {"project_id": project_id, "subject": subject}
    if description:
        issue_data["description"] = description
    if tracker_id:
        issue_data["tracker_id"] = int(tracker_id)
    if priority_id:
        issue_data["priority_id"] = int(priority_id)
    if assigned_to_id:
        issue_data["assigned_to_id"] = int(assigned_to_id)
    result = api_request("POST", "/issues.json", {"issue": issue_data})
    issue = result.get("issue", {})
    print(f"チケット作成完了: #{issue.get('id')} - {issue.get('subject')}")
    return result


def update_issue(issue_id, status_id=None, assigned_to_id=None, priority_id=None, done_ratio=None, due_date=None, notes=None):
    """チケットを更新する"""
    issue_data = {}
    if status_id:
        issue_data["status_id"] = int(status_id)
    if assigned_to_id:
        issue_data["assigned_to_id"] = int(assigned_to_id)
    if priority_id:
        issue_data["priority_id"] = int(priority_id)
    if done_ratio is not None:
        issue_data["done_ratio"] = int(done_ratio)
    if due_date:
        issue_data["due_date"] = due_date
    if notes:
        issue_data["notes"] = notes
    if not issue_data:
        print("エラー: 更新する項目を指定してください。", file=sys.stderr)
        sys.exit(1)
    api_request("PUT", f"/issues/{issue_id}.json", {"issue": issue_data})
    print(f"チケット #{issue_id} を更新しました。")


def search_issues(keyword):
    """チケットを検索する"""
    query = urllib.parse.urlencode({"q": keyword, "issues": 1})
    result = api_request("GET", f"/search.json?{query}")
    results = result.get("results", [])
    print(f"検索結果（'{keyword}'）: {len(results)}件")
    for r in results:
        print(f"  #{r.get('id', '?')} - {r.get('title', '不明')} ({r.get('datetime', '')})")
    return result


# --- プロジェクト操作 ---

def list_projects():
    """プロジェクト一覧を取得する"""
    result = api_request("GET", "/projects.json")
    projects = result.get("projects", [])
    print(f"プロジェクト一覧（{len(projects)}件）:")
    for p in projects:
        print(f"  [{p['identifier']}] {p['name']} - {p.get('description', '')[:80]}")
    return result


def get_project(project_id):
    """プロジェクト詳細を取得する"""
    result = api_request("GET", f"/projects/{project_id}.json?include=trackers,issue_categories")
    proj = result.get("project", {})
    print(f"プロジェクト: {proj['name']} ({proj['identifier']})")
    print(f"  説明: {proj.get('description', 'なし')[:200]}")
    trackers = proj.get("trackers", [])
    if trackers:
        print(f"  トラッカー: {', '.join(t['name'] for t in trackers)}")
    return result


def list_members(project_id):
    """プロジェクトメンバー一覧を取得する"""
    result = api_request("GET", f"/projects/{project_id}/memberships.json")
    members = result.get("memberships", [])
    print(f"メンバー一覧（{len(members)}件）:")
    for m in members:
        user = m.get("user", m.get("group", {}))
        roles = ", ".join(r["name"] for r in m.get("roles", []))
        print(f"  {user.get('name', '不明')} - {roles}")
    return result


def list_versions(project_id):
    """バージョン（マイルストーン）一覧を取得する"""
    result = api_request("GET", f"/projects/{project_id}/versions.json")
    versions = result.get("versions", [])
    print(f"バージョン一覧（{len(versions)}件）:")
    for v in versions:
        print(f"  {v['name']} [{v['status']}] 期日: {v.get('due_date', '未設定')}")
    return result


# --- メイン ---

def main():
    parser = argparse.ArgumentParser(description="Redmine APIツール")
    sub = parser.add_subparsers(dest="command", help="コマンド")

    # チケット一覧
    p = sub.add_parser("issues", help="チケット一覧取得")
    p.add_argument("--project", help="プロジェクトID")
    p.add_argument("--assigned-to", help="担当者ID（meで自分）")
    p.add_argument("--status", default="open", help="ステータス（open/closed/*）")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--offset", type=int, default=0)

    # チケット詳細
    p = sub.add_parser("issue", help="チケット詳細取得")
    p.add_argument("id", type=int, help="チケットID")

    # チケット作成
    p = sub.add_parser("create", help="チケット作成")
    p.add_argument("--project", required=True, help="プロジェクトID")
    p.add_argument("--subject", required=True, help="題名")
    p.add_argument("--description", default="", help="説明")
    p.add_argument("--tracker", help="トラッカーID")
    p.add_argument("--priority", help="優先度ID")
    p.add_argument("--assigned-to", help="担当者ID")

    # チケット更新
    p = sub.add_parser("update", help="チケット更新")
    p.add_argument("id", type=int, help="チケットID")
    p.add_argument("--status", help="ステータスID")
    p.add_argument("--assigned-to", help="担当者ID")
    p.add_argument("--priority", help="優先度ID")
    p.add_argument("--done-ratio", help="進捗率（0〜100）")
    p.add_argument("--due-date", help="期日（YYYY-MM-DD）")
    p.add_argument("--notes", help="コメント")

    # チケット検索
    p = sub.add_parser("search", help="チケット検索")
    p.add_argument("keyword", help="検索キーワード")

    # プロジェクト一覧
    sub.add_parser("projects", help="プロジェクト一覧取得")

    # プロジェクト詳細
    p = sub.add_parser("project", help="プロジェクト詳細取得")
    p.add_argument("id", help="プロジェクトID")

    # メンバー一覧
    p = sub.add_parser("members", help="メンバー一覧取得")
    p.add_argument("project", help="プロジェクトID")

    # バージョン一覧
    p = sub.add_parser("versions", help="バージョン一覧取得")
    p.add_argument("project", help="プロジェクトID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "issues":
        list_issues(args.project, args.assigned_to, args.status, args.limit, args.offset)
    elif args.command == "issue":
        get_issue(args.id)
    elif args.command == "create":
        create_issue(args.project, args.subject, args.description, args.tracker, args.priority, getattr(args, "assigned_to", None))
    elif args.command == "update":
        update_issue(args.id, args.status, getattr(args, "assigned_to", None), args.priority, args.done_ratio, args.due_date, args.notes)
    elif args.command == "search":
        search_issues(args.keyword)
    elif args.command == "projects":
        list_projects()
    elif args.command == "project":
        get_project(args.id)
    elif args.command == "members":
        list_members(args.project)
    elif args.command == "versions":
        list_versions(args.project)


if __name__ == "__main__":
    main()
