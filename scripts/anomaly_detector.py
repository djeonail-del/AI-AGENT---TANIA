#!/usr/bin/env python3
"""
anomaly_detector.py — Proactive Anomaly Detection for Tania
Checks system health and sends Telegram alerts if issues found.

Usage: python3 scripts/anomaly_detector.py [--dry-run]
"""

import json
import sys
import os
import urllib.request
import urllib.error
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
VPS_HOST = os.environ.get("VPS_HOST", "")
VPS_USER = os.environ.get("VPS_USER", "")
VPS_PASS = os.environ.get("VPS_PASS", "")
VPS_CONTAINERS = ["nara", "rina", "lyra"]
DRY_RUN = "--dry-run" in sys.argv


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S WITA")


def send_telegram(message: str) -> bool:
    """Send alert to Telegram."""
    if DRY_RUN:
        print(f"[DRY-RUN] Would send Telegram:\n{message}\n")
        return True
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        return False


def format_alert(issues: list) -> str:
    """Format anomaly alert message."""
    lines = ["⚠️ <b>Tania Anomaly Alert</b>", ""]
    for issue in issues:
        lines.append(f"• {issue}")
    lines.append("")
    lines.append(f"• Detected at: {now_str()}")
    return "\n".join(lines)


def check_supabase_connectivity() -> tuple[bool, str]:
    """Check if Supabase is reachable."""
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 201, 404)  # 404 = reachable but no table
            return ok, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def check_instagram_posting_gap() -> tuple[str | None, dict]:
    """Check if last Instagram post was > 3 days ago. Returns (issue_msg or None, details).
    
    Cross-checks Notion: if there are items with '📅 Scheduled' status and a future date,
    content is ready to go — reduce urgency (info note instead of alert).
    Carousel schema: scheduled_for, publish_time, status (published/pending_review/etc), created_at
    """
    try:
        # Check publish_time (actual post time) for published content
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/carousels?select=publish_time,scheduled_for,status,name&status=eq.published&order=publish_time.desc&limit=1",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            # Fallback: check by scheduled_for for any status
            req2 = urllib.request.Request(
                f"{SUPABASE_URL}/rest/v1/carousels?select=publish_time,scheduled_for,status,name&order=scheduled_for.desc&limit=1",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                data = json.loads(resp2.read().decode())

            if not data:
                return "No carousels found in Supabase", {}

            last = data[0]
            # If most recent scheduled is in future, it's fine
            sched = last.get("scheduled_for")
            if sched:
                sched_dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                if sched_dt > datetime.now(timezone.utc):
                    return None, {"scheduled_future": sched}
            return "No published carousels found — Instagram posting may have stopped", last

        last = data[0]
        # Use publish_time if available, else scheduled_for
        pub_str = last.get("publish_time") or last.get("scheduled_for")
        if not pub_str:
            return "Last carousel has no timestamp", last

        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - pub_dt
        days = delta.total_seconds() / 86400

        # If gap > 3 days, cross-check Notion for upcoming scheduled content
        if days > 3:
            scheduled_count = get_notion_scheduled_future_count()
            if scheduled_count > 0:
                # Content is ready in Notion — not an emergency
                print(f"    [Notion] {scheduled_count} item(s) scheduled for future in Notion — downgrading urgency")
                return None, {
                    "last_published": pub_str,
                    "days_ago": round(days, 1),
                    "notion_scheduled_future": scheduled_count,
                    "note": f"Gap is {days:.1f}d but {scheduled_count} item(s) already scheduled in Notion",
                }
            return (
                f"Instagram posting gap: last post was {days:.1f} days ago ({pub_str[:10]}) "
                f"— no upcoming content scheduled in Notion either",
                last,
            )
        return None, {"last_published": pub_str, "days_ago": round(days, 1)}

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "carousels table not found in Supabase", {}
        body = e.read().decode()[:200]
        return f"Supabase carousels query error: HTTP {e.code} — {body}", {}
    except Exception as e:
        return f"Supabase carousels query error: {e}", {}


NOTION_KEY = os.environ.get("NOTION_KEY", "")
NOTION_DB = os.environ.get("NOTION_DB_ID", "")
NOTION_HANDLED_STATUSES = ["✅ Design Approved", "❌ Rejected", "📅 Scheduled", "📤 Posted"]


def get_notion_handled_names() -> set[str]:
    """Fetch names of all Notion items that have a 'handled' status.

    Uses sequential single-status queries (one per status) to avoid the compound
    OR filter that Notion API rejects with HTTP 400.
    Returns a set of lowercase names. Returns empty set on error (fail open = alert anyway).
    """
    names = set()
    for status in NOTION_HANDLED_STATUSES:
        try:
            payload = json.dumps({
                "filter": {
                    "property": "Status",
                    "select": {"equals": status},
                },
                "page_size": 100,
            }).encode()
            req = urllib.request.Request(
                f"https://api.notion.com/v1/databases/{NOTION_DB}/query",
                data=payload,
                headers={
                    "Authorization": f"Bearer {NOTION_KEY}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            for item in data.get("results", []):
                name_prop = item.get("properties", {}).get("Name", {})
                title_arr = name_prop.get("title", [])
                if title_arr:
                    name = title_arr[0].get("plain_text", "").strip().lower()
                    if name:
                        names.add(name)

        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            print(f"    [Notion] HTTP {e.code} for status '{status}': {body} — skipping")
            continue
        except Exception as e:
            print(f"    [Notion] Could not fetch handled names for status '{status}': {e}")
            continue

    return names  # Fail open: empty set means no cross-check, alerts pass through


def is_handled_in_notion(carousel_name: str, handled_names: set[str]) -> bool:
    """Check if a carousel name matches any handled Notion item (case-insensitive, partial ok)."""
    if not handled_names or not carousel_name:
        return False
    name_lower = carousel_name.strip().lower()
    # Exact match
    if name_lower in handled_names:
        return True
    # Partial match: supabase name contained in notion name or vice versa
    for notion_name in handled_names:
        if name_lower in notion_name or notion_name in name_lower:
            return True
    return False


def get_notion_scheduled_future_count() -> int:
    """Return count of Notion items with status '📅 Scheduled' (content ready to go)."""
    try:
        # Just filter by Scheduled status — if anything is scheduled, content is ready
        payload = json.dumps({
            "filter": {
                "property": "Status",
                "select": {"equals": "📅 Scheduled"},
            },
            "page_size": 10,
        }).encode()
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{NOTION_DB}/query",
            data=payload,
            headers={
                "Authorization": f"Bearer {NOTION_KEY}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return len(data.get("results", []))
    except Exception as e:
        print(f"    [Notion] Could not fetch scheduled count: {e}")
        return 0


def check_notion_pending_count() -> int:
    """Check how many items are in '🎨 Design Ready' status in Notion (not yet reviewed)."""
    try:
        payload = json.dumps({
            "filter": {"property": "Status", "select": {"equals": "🎨 Design Ready"}}
        }).encode()
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{NOTION_DB}/query",
            data=payload,
            headers={
                "Authorization": f"Bearer {NOTION_KEY}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return len(data.get("results", []))
    except Exception:
        return -1  # Unknown, skip cross-check


def check_pending_review_carousels() -> tuple[str | None, dict]:
    """Check for carousels stuck in pending_review > 3 days.
    
    Cross-checks with Notion: if a stuck carousel is already handled in Notion
    (✅ Design Approved / ❌ Rejected / 📅 Scheduled / ✅ Published), skip the alert.
    Only alerts for carousels that are BOTH stuck in Supabase AND not handled in Notion.
    """
    try:
        import urllib.parse
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_enc = urllib.parse.quote(cutoff)
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/carousels?select=id,name,created_at,status&status=eq.pending_review&created_at=lt.{cutoff_enc}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            return None, {"pending_review_stale": 0}

        # Cross-check with Notion
        print(f"    [Notion] Cross-checking {len(data)} stuck carousel(s) against Notion...")
        handled_names = get_notion_handled_names()
        print(f"    [Notion] Found {len(handled_names)} handled items in Notion")

        truly_stuck = []
        for carousel in data:
            name = carousel.get("name", "")
            if is_handled_in_notion(name, handled_names):
                print(f"    [Notion] ✅ Already handled in Notion: \"{name[:40]}\" — skipping")
            else:
                print(f"    [Notion] ⚠️  Not handled in Notion: \"{name[:40]}\" — will alert")
                truly_stuck.append(carousel)

        if truly_stuck:
            count = len(truly_stuck)
            oldest = min(truly_stuck, key=lambda x: x.get("created_at", ""))
            oldest_date = oldest.get("created_at", "?")[:10]
            oldest_name = oldest.get("name", "?")[:40]
            return (
                f"{count} carousel(s) stuck in pending_review > 3 days "
                f"(oldest: \"{oldest_name}\" since {oldest_date}) — needs review in Notion",
                {"count": count, "notion_cross_checked": True},
            )

        # All stuck carousels are already handled in Notion
        return None, {
            "pending_review_stale": len(data),
            "all_handled_in_notion": True,
            "note": f"{len(data)} stuck in Supabase but all already handled in Notion",
        }

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, {"note": "carousels table not found"}
        body = e.read().decode()[:200]
        return f"Pending review check error: HTTP {e.code} — {body}", {}
    except Exception as e:
        return f"Pending review check error: {e}", {}


def check_vps_containers() -> tuple[str | None, dict]:
    """SSH to VPS and check if nara/rina/lyra containers are running."""
    try:
        # Use sshpass or paramiko if available; fallback to subprocess with sshpass
        cmd = [
            "sshpass", "-p", VPS_PASS,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15",
            f"{VPS_USER}@{VPS_HOST}",
            "docker ps --format '{{.Names}}' 2>/dev/null || echo 'docker_not_available'"
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:200]
            stdout = result.stdout.strip()[:200]
            if "sshpass" in stderr.lower() or "not found" in stderr.lower():
                # Try without sshpass - just check connectivity
                return check_vps_containers_fallback()
            return f"VPS SSH error: {stderr or stdout}", {}

        running = result.stdout.strip().split("\n")
        running_lower = [r.lower() for r in running if r]
        down = []
        for container in VPS_CONTAINERS:
            found = any(container in r for r in running_lower)
            if not found:
                down.append(container)

        if down:
            return f"VPS containers DOWN: {', '.join(down)} (running: {len(running_lower)} containers)", {
                "down": down,
                "running_count": len(running_lower),
            }
        return None, {"all_running": VPS_CONTAINERS, "running": running_lower}

    except FileNotFoundError:
        return check_vps_containers_fallback()
    except subprocess.TimeoutExpired:
        return f"VPS SSH timeout ({VPS_HOST}) — server may be unreachable", {}
    except Exception as e:
        return f"VPS container check error: {e}", {}


def check_vps_containers_fallback() -> tuple[str | None, dict]:
    """Fallback: try raw ssh without sshpass."""
    try:
        # Try paramiko
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
        stdin, stdout, stderr = client.exec_command("docker ps --format '{{.Names}}' 2>/dev/null")
        output = stdout.read().decode().strip()
        client.close()

        running = [r for r in output.split("\n") if r]
        running_lower = [r.lower() for r in running]
        down = [c for c in VPS_CONTAINERS if not any(c in r for r in running_lower)]

        if down:
            return f"VPS containers DOWN: {', '.join(down)}", {"down": down}
        return None, {"all_running": True}

    except ImportError:
        # No paramiko - try nc/ping as minimal check
        try:
            result = subprocess.run(
                ["nc", "-z", "-w", "5", VPS_HOST, "22"],
                capture_output=True, timeout=10
            )
            if result.returncode != 0:
                return f"VPS unreachable at {VPS_HOST}:22 — cannot check containers", {}
            return None, {"note": "SSH port open but could not check containers (no sshpass/paramiko)"}
        except Exception as e:
            return f"VPS connectivity check failed: {e}", {}
    except Exception as e:
        return f"VPS SSH error (paramiko): {e}", {}


def run_checks() -> list[str]:
    """Run all anomaly checks. Returns list of issue strings."""
    issues = []
    details = {}

    print("🔍 Running anomaly checks...\n")

    # 1. Supabase connectivity
    print("  [1/4] Supabase connectivity...")
    ok, status = check_supabase_connectivity()
    if ok:
        print(f"    ✅ Supabase reachable ({status})")
    else:
        issue = f"Supabase connectivity FAILED: {status}"
        print(f"    ❌ {issue}")
        issues.append(issue)
        # If Supabase is down, skip dependent checks
        print("\n  ⚠️  Supabase down — skipping carousel checks")
        # Still check VPS
    
    if ok:
        # 2. Instagram posting gap
        print("  [2/4] Instagram posting gap...")
        issue, det = check_instagram_posting_gap()
        if issue:
            print(f"    ⚠️  {issue}")
            issues.append(issue)
            details["instagram"] = det
        else:
            days_ago = det.get("days_ago", "?")
            print(f"    ✅ Last post {days_ago} days ago")

        # 3. Pending review carousels
        print("  [3/4] Pending review carousels...")
        issue, det = check_pending_review_carousels()
        if issue:
            print(f"    ⚠️  {issue}")
            issues.append(issue)
            details["pending_review"] = det
        else:
            print(f"    ✅ No stale pending_review carousels")

    # 4. VPS containers
    print("  [4/4] VPS agent containers...")
    issue, det = check_vps_containers()
    if issue:
        print(f"    ⚠️  {issue}")
        issues.append(issue)
        details["vps"] = det
    else:
        note = det.get("note", "all running")
        print(f"    ✅ {note}")

    return issues


def main():
    if DRY_RUN:
        print("🧪 DRY-RUN MODE — No Telegram messages will be sent\n")

    issues = run_checks()

    print(f"\n{'='*50}")
    if issues:
        print(f"⚠️  Found {len(issues)} anomalie(s):")
        for i in issues:
            print(f"   • {i}")

        alert = format_alert(issues)
        print(f"\n📨 Sending Telegram alert...")
        ok = send_telegram(alert)
        if ok:
            print("  ✅ Alert sent!")
        else:
            print("  ❌ Failed to send alert")
    else:
        print("✅ All systems normal — no anomalies detected")

    print(f"{'='*50}")
    print(f"Completed at: {now_str()}")


if __name__ == "__main__":
    main()
