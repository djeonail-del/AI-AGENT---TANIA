#!/usr/bin/env python3
"""
full_audit.py — Deterministic audit script for Tania's system.
Checks all gaps between Mac mini workspace and VPS agents (Nara/Rina/Lyra).
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(WORKSPACE, ".env")
VPS_HOST = "212.85.27.223"
VPS_USER = "root"

AGENTS = {
    "nara": "/root/.nara-openclaw",
    "rina": "/root/.rina-openclaw",
    "lyra": "/root/.lyra-openclaw",
}

MAC_SPECIFIC_SCRIPTS = {"ollama_proxy.py"}
MAC_SPECIFIC_PREFIXES = ("patch_kimi",)

REQUIRED_ENV_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "OPENCLAW_WORKSPACE",
]

AGENTS_MD_MARKERS = ["last-conversation.md", "Session Startup", "Session Reset Rule"]
HEARTBEAT_MD_MARKERS = ["save_last_conversation.py"]


# ─────────────────────────────────────────────
# COLOR HELPERS
# ─────────────────────────────────────────────
USE_COLOR = sys.stdout.isatty()

def green(s):  return f"\033[92m{s}\033[0m" if USE_COLOR else s
def red(s):    return f"\033[91m{s}\033[0m" if USE_COLOR else s
def yellow(s): return f"\033[93m{s}\033[0m" if USE_COLOR else s
def bold(s):   return f"\033[1m{s}\033[0m" if USE_COLOR else s


PASS_ICON = green("✅ PASS")
FAIL_ICON = red("❌ FAIL")
WARN_ICON = yellow("⚠️  WARN")


# ─────────────────────────────────────────────
# .ENV LOADER
# ─────────────────────────────────────────────
def load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ─────────────────────────────────────────────
# SSH HELPER
# ─────────────────────────────────────────────
def ssh_run(password, command, timeout=15):
    """Run a command on VPS via sshpass+ssh. Returns (stdout, stderr, returncode)."""
    cmd = [
        "sshpass", f"-p{password}",
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=no",
        "-o", f"ConnectTimeout={timeout}",
        f"{VPS_USER}@{VPS_HOST}",
        command,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    return result.stdout, result.stderr, result.returncode


# ─────────────────────────────────────────────
# RESULTS COLLECTOR
# ─────────────────────────────────────────────
results = []  # list of (check_num, label, status, detail)

def record(num, label, status, detail=""):
    results.append((num, label, status, detail))


# ─────────────────────────────────────────────
# CHECKS
# ─────────────────────────────────────────────

def check_1_connectivity(env):
    """VPS SSH connectivity."""
    vps_pass = env.get("VPS_PASS", "")
    if not vps_pass:
        record(1, "VPS Connectivity", "FAIL", "VPS_PASS not set in .env")
        return None

    try:
        stdout, stderr, rc = ssh_run(vps_pass, "echo CONNECTED", timeout=10)
        if rc == 0 and "CONNECTED" in stdout:
            record(1, "VPS Connectivity", "PASS", "SSH OK")
            return vps_pass
        else:
            record(1, "VPS Connectivity", "FAIL", f"SSH failed (rc={rc}): {stderr.strip()[:100]}")
            return None
    except subprocess.TimeoutExpired:
        record(1, "VPS Connectivity", "FAIL", "SSH timeout")
        return None
    except FileNotFoundError:
        record(1, "VPS Connectivity", "FAIL", "sshpass not found — install it first")
        return None


def check_2_scripts_sync(vps_pass):
    """Scripts sync: all required .py files present on all 3 agents."""
    # Collect required scripts from Mac workspace
    scripts_dir = os.path.join(WORKSPACE, "scripts")
    all_scripts = [f for f in os.listdir(scripts_dir) if f.endswith(".py")]
    required = []
    for s in all_scripts:
        if s in MAC_SPECIFIC_SCRIPTS:
            continue
        if any(s.startswith(p) for p in MAC_SPECIFIC_PREFIXES):
            continue
        required.append(s)
    required.sort()

    if not required:
        record(2, "Scripts sync", "WARN", "No required scripts found in local scripts/")
        return

    # Build SSH command to check all agents at once
    checks = []
    for agent, path in AGENTS.items():
        for script in required:
            checks.append(f"[ -f {path}/workspace/scripts/{script} ] && echo 'OK:{agent}:{script}' || echo 'MISSING:{agent}:{script}'")
    cmd = " ; ".join(checks)

    try:
        stdout, _, rc = ssh_run(vps_pass, cmd, timeout=20)
    except subprocess.TimeoutExpired:
        record(2, "Scripts sync", "FAIL", "SSH timeout during scripts check")
        return

    missing = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MISSING:"):
            _, agent, script = line.split(":", 2)
            missing.append(f"{agent}/{script}")

    total = len(required) * len(AGENTS)
    found = total - len(missing)
    if missing:
        record(2, "Scripts sync", "FAIL", f"{found}/{total} — missing: {', '.join(missing[:5])}{'...' if len(missing)>5 else ''}")
    else:
        record(2, "Scripts sync", "PASS", f"{total}/{total} on all agents ({len(required)} scripts × {len(AGENTS)} agents)")


def check_3_hardcoded_paths(vps_pass):
    """Grep scripts/ for /Users/mac/ on all agents."""
    grep_cmds = []
    env_cmds = []
    for agent, path in AGENTS.items():
        grep_cmds.append(
            f"grep -r '/Users/mac/' {path}/workspace/scripts/ --include='*.py' -l 2>/dev/null | "
            f"while read f; do echo 'FOUND:{agent}:'$f; done"
        )
        env_cmds.append(
            f"grep -q '^OPENCLAW_WORKSPACE=' {path}/workspace/.env 2>/dev/null && "
            f"echo 'WSET:{agent}' || echo 'WMISSING:{agent}'"
        )
    cmd = " ; ".join(grep_cmds + env_cmds)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=20)
    except subprocess.TimeoutExpired:
        record(3, "Hardcoded paths", "WARN", "SSH timeout")
        return

    found_files = []
    workspace_set = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("FOUND:"):
            _, agent, fpath = line.split(":", 2)
            found_files.append(f"{agent}:{os.path.basename(fpath)}")
        elif line.startswith("WSET:"):
            workspace_set[line.split(":", 1)[1]] = True
        elif line.startswith("WMISSING:"):
            workspace_set[line.split(":", 1)[1]] = False

    all_workspace_set = all(workspace_set.get(a, False) for a in AGENTS)

    if found_files and all_workspace_set:
        record(3, "Hardcoded paths", "PASS",
               f"Fallback only, OPENCLAW_WORKSPACE set on all agents ({len(found_files)} files have fallback path)")
    elif found_files and not all_workspace_set:
        missing_ws = [a for a, v in workspace_set.items() if not v]
        record(3, "Hardcoded paths", "WARN",
               f"/Users/mac/ found in: {', '.join(found_files[:3])} — OPENCLAW_WORKSPACE missing on: {', '.join(missing_ws)}")
    else:
        record(3, "Hardcoded paths", "PASS", "No hardcoded /Users/mac/ paths found")


def check_4_env_completeness(vps_pass):
    """Check .env has all required keys on all agents."""
    checks = []
    for agent, path in AGENTS.items():
        for key in REQUIRED_ENV_KEYS:
            checks.append(
                f"grep -q '^{key}=.' {path}/workspace/.env 2>/dev/null && "
                f"echo 'OK:{agent}:{key}' || echo 'MISSING:{agent}:{key}'"
            )
    cmd = " ; ".join(checks)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=20)
    except subprocess.TimeoutExpired:
        record(4, ".env completeness", "FAIL", "SSH timeout")
        return

    missing = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MISSING:"):
            _, agent, key = line.split(":", 2)
            missing.append(f"{agent}/{key}")

    if missing:
        record(4, ".env completeness", "FAIL", f"Missing keys: {', '.join(missing)}")
    else:
        total = len(REQUIRED_ENV_KEYS) * len(AGENTS)
        record(4, ".env completeness", "PASS", f"All {total} keys present on all agents")


def check_5_memory_md(vps_pass):
    """MEMORY.md exists and is non-empty on all agents."""
    checks = []
    for agent, path in AGENTS.items():
        checks.append(
            f"[ -s {path}/workspace/MEMORY.md ] && "
            f"echo 'OK:{agent}' || echo 'MISSING:{agent}'"
        )
    cmd = " ; ".join(checks)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=15)
    except subprocess.TimeoutExpired:
        record(5, "MEMORY.md", "FAIL", "SSH timeout")
        return

    missing = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MISSING:"):
            missing.append(line.split(":", 1)[1])

    if missing:
        record(5, "MEMORY.md", "FAIL", f"Missing/empty on: {', '.join(missing)}")
    else:
        record(5, "MEMORY.md", "PASS", f"Exists and non-empty on all {len(AGENTS)} agents")


def check_6_agents_md_quality(vps_pass):
    """AGENTS.md contains required markers."""
    checks = []
    for agent, path in AGENTS.items():
        for marker in AGENTS_MD_MARKERS:
            safe_marker = marker.replace("'", "'\\''")
            checks.append(
                f"grep -q '{safe_marker}' {path}/workspace/AGENTS.md 2>/dev/null && "
                f"echo 'OK:{agent}:{marker}' || echo 'MISSING:{agent}:{marker}'"
            )
    cmd = " ; ".join(checks)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=15)
    except subprocess.TimeoutExpired:
        record(6, "AGENTS.md quality", "WARN", "SSH timeout")
        return

    missing = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MISSING:"):
            _, agent, marker = line.split(":", 2)
            missing.append(f"{agent}/'{marker}'")

    if missing:
        record(6, "AGENTS.md quality", "WARN", f"Missing markers: {'; '.join(missing[:4])}")
    else:
        record(6, "AGENTS.md quality", "PASS", f"All markers present on all agents")


def check_7_heartbeat_md_quality(vps_pass):
    """HEARTBEAT.md contains required markers."""
    checks = []
    for agent, path in AGENTS.items():
        for marker in HEARTBEAT_MD_MARKERS:
            safe_marker = marker.replace("'", "'\\''")
            checks.append(
                f"grep -q '{safe_marker}' {path}/workspace/HEARTBEAT.md 2>/dev/null && "
                f"echo 'OK:{agent}:{marker}' || echo 'MISSING:{agent}:{marker}'"
            )
    cmd = " ; ".join(checks)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=15)
    except subprocess.TimeoutExpired:
        record(7, "HEARTBEAT.md quality", "WARN", "SSH timeout")
        return

    missing = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MISSING:"):
            _, agent, marker = line.split(":", 2)
            missing.append(f"{agent}/'{marker}'")

    if missing:
        record(7, "HEARTBEAT.md quality", "WARN", f"Missing markers: {'; '.join(missing)}")
    else:
        record(7, "HEARTBEAT.md quality", "PASS", "All markers present on all agents")


def check_8_hooks_enabled(vps_pass):
    """openclaw.json has hooks.enabled = true on all agents."""
    checks = []
    for agent, path in AGENTS.items():
        checks.append(
            f"python3 -c \""
            f"import json; d=json.load(open('{path}/openclaw.json')); "
            f"h=d.get('hooks',{{}}); enabled=h.get('enabled',False); "
            f"print('OK:{agent}' if enabled else 'FAIL:{agent}:enabled=' + str(enabled))"
            f"\" 2>/dev/null || echo 'FAIL:{agent}:parse error'"
        )
    cmd = " ; ".join(checks)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=15)
    except subprocess.TimeoutExpired:
        record(8, "hooks enabled", "FAIL", "SSH timeout")
        return

    failures = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("FAIL:"):
            parts = line.split(":", 2)
            agent = parts[1]
            detail = parts[2] if len(parts) > 2 else "unknown"
            failures.append(f"{agent} ({detail})")

    if failures:
        record(8, "hooks enabled", "FAIL", f"hooks.enabled != true on: {', '.join(failures)}")
    else:
        record(8, "hooks enabled", "PASS", "hooks.enabled=true on all agents")


def check_9_hooks_live_context(vps_pass):
    """hooks/live-context/handler.ts exists on all agents."""
    checks = []
    for agent, path in AGENTS.items():
        checks.append(
            f"[ -f {path}/workspace/hooks/live-context/handler.ts ] && "
            f"echo 'OK:{agent}' || echo 'MISSING:{agent}'"
        )
    cmd = " ; ".join(checks)

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=15)
    except subprocess.TimeoutExpired:
        record(9, "hooks/live-context", "FAIL", "SSH timeout")
        return

    missing = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MISSING:"):
            missing.append(line.split(":", 1)[1])

    if missing:
        record(9, "hooks/live-context", "FAIL", f"handler.ts missing on: {', '.join(missing)}")
    else:
        record(9, "hooks/live-context", "PASS", "handler.ts exists on all agents")


def check_10_live_script_test(vps_pass):
    """Run save_last_conversation.py on Nara and check exit code."""
    nara_path = AGENTS["nara"]
    cmd = (
        f"cd {nara_path}/workspace && "
        f"OPENCLAW_WORKSPACE={nara_path}/workspace "
        f"python3 {nara_path}/workspace/scripts/save_last_conversation.py 2>&1; "
        f"echo EXIT_CODE:$?"
    )

    try:
        stdout, _, _ = ssh_run(vps_pass, cmd, timeout=20)
    except subprocess.TimeoutExpired:
        record(10, "Live script test", "FAIL", "SSH timeout — script took >20s")
        return

    # Extract exit code
    exit_code = None
    for line in stdout.splitlines():
        if line.startswith("EXIT_CODE:"):
            try:
                exit_code = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    if exit_code == 0:
        record(10, "Live script test", "PASS", "save_last_conversation.py exited 0 on Nara")
    elif exit_code is not None:
        # Grab last few lines of output for context
        output_lines = [l for l in stdout.splitlines() if not l.startswith("EXIT_CODE:")]
        snippet = " | ".join(output_lines[-2:])[:120]
        record(10, "Live script test", "FAIL", f"Exit code {exit_code} — {snippet}")
    else:
        record(10, "Live script test", "FAIL", "Could not parse exit code from output")


def check_11_git_status():
    """Git status is clean on Tania's workspace."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=WORKSPACE, timeout=10
        )
        if result.returncode != 0:
            record(11, "Git status", "WARN", f"git status failed: {result.stderr.strip()[:80]}")
            return
        dirty = result.stdout.strip()
        if dirty:
            lines = dirty.splitlines()
            record(11, "Git status", "WARN",
                   f"Dirty — {len(lines)} uncommitted change(s): {', '.join(l[3:] for l in lines[:3])}"
                   + ("..." if len(lines) > 3 else ""))
        else:
            record(11, "Git status", "PASS", "clean")
    except subprocess.TimeoutExpired:
        record(11, "Git status", "WARN", "git status timed out")
    except FileNotFoundError:
        record(11, "Git status", "WARN", "git not found")


def check_12_supabase_connectivity(env):
    """Quick HTTP check to Supabase URL."""
    supabase_url = env.get("SUPABASE_URL", "")
    if not supabase_url:
        record(12, "Supabase connectivity", "FAIL", "SUPABASE_URL not set in .env")
        return

    ping_url = supabase_url.rstrip("/") + "/rest/v1/"
    supabase_key = env.get("SUPABASE_KEY", env.get("SUPABASE_ANON_KEY", ""))

    try:
        req = urllib.request.Request(
            ping_url,
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
            if status == 200:
                record(12, "Supabase connectivity", "PASS", f"HTTP {status} from {supabase_url[:40]}...")
            else:
                record(12, "Supabase connectivity", "WARN", f"HTTP {status} (expected 200)")
    except urllib.error.HTTPError as e:
        if e.code in (200, 400):  # 400 = no query params, but server is up
            record(12, "Supabase connectivity", "PASS", f"HTTP {e.code} (server reachable)")
        else:
            record(12, "Supabase connectivity", "FAIL", f"HTTP {e.code}: {str(e)[:60]}")
    except urllib.error.URLError as e:
        record(12, "Supabase connectivity", "FAIL", f"URLError: {str(e.reason)[:80]}")
    except Exception as e:
        record(12, "Supabase connectivity", "FAIL", f"Error: {str(e)[:80]}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    # Header
    now = datetime.now().strftime("%Y-%m-%d %H:%M WITA")
    width = 44
    print()
    print("╔" + "═" * width + "╗")
    print(f"║  {bold('Tania System Full Audit'):<{width-1}}║")
    print(f"║  {now:<{width-2}}║")
    print("╚" + "═" * width + "╝")
    print()

    # Load local .env
    env = load_env(ENV_FILE)

    # Run checks
    print("Running checks...")
    print()

    vps_pass = check_1_connectivity(env)
    if vps_pass:
        check_2_scripts_sync(vps_pass)
        check_3_hardcoded_paths(vps_pass)
        check_4_env_completeness(vps_pass)
        check_5_memory_md(vps_pass)
        check_6_agents_md_quality(vps_pass)
        check_7_heartbeat_md_quality(vps_pass)
        check_8_hooks_enabled(vps_pass)
        check_9_hooks_live_context(vps_pass)
        check_10_live_script_test(vps_pass)
    else:
        # VPS unreachable — skip all VPS checks
        for i, label in [
            (2, "Scripts sync"), (3, "Hardcoded paths"), (4, ".env completeness"),
            (5, "MEMORY.md"), (6, "AGENTS.md quality"), (7, "HEARTBEAT.md quality"),
            (8, "hooks enabled"), (9, "hooks/live-context"), (10, "Live script test"),
        ]:
            record(i, label, "FAIL", "Skipped — VPS unreachable")

    check_11_git_status()
    check_12_supabase_connectivity(env)

    # Print results
    label_width = 30
    for num, label, status, detail in results:
        if status == "PASS":
            icon = PASS_ICON
        elif status == "FAIL":
            icon = FAIL_ICON
        else:
            icon = WARN_ICON

        # Format check label with dots
        check_str = f"[CHECK {num:>2}] {label}"
        dots = "." * max(1, label_width - len(check_str) + 14)
        detail_str = f"  ({detail})" if detail else ""
        print(f"{check_str} {dots} {icon}{detail_str}")

    # Verdict
    print()
    print("═" * (width + 2))
    n_fail = sum(1 for _, _, s, _ in results if s == "FAIL")
    n_warn = sum(1 for _, _, s, _ in results if s == "WARN")
    n_pass = sum(1 for _, _, s, _ in results if s == "PASS")
    total = len(results)

    if n_fail == 0 and n_warn == 0:
        verdict = green(f"VERDICT: {n_pass}/{total} checks passed — FULLY SYNCED ✅")
    elif n_fail == 0:
        verdict = yellow(f"VERDICT: {n_pass}/{total} PASS, {n_warn} WARN — mostly synced, review warnings")
    else:
        verdict = red(f"VERDICT: {n_fail} FAILED, {n_warn} WARN, {n_pass} PASS — ACTION REQUIRED")

    print(verdict)
    print("═" * (width + 2))
    print()

    # Exit code
    if n_fail > 0:
        sys.exit(1)
    elif n_warn > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
