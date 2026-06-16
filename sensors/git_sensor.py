"""Git activity sensor — passive, LOCAL-ONLY monitoring of your own commit patterns.

Detects: avoidance (long gaps without commits), hyperfocus (burst commits),
real energy windows (when you actually ship vs. when you claim to work).

Privacy: commit metadata (hash, timestamp, subject) is stored ONLY in the local
SQLite db; nothing is transmitted. Configure exactly what gets scanned via
DOPA_GIT_ROOT (default: current working directory) and DOPA_GIT_SCAN_DIRS
(comma-separated sub-dirs, default: "." — scan the root in place). Point it at
your own project dirs; do not scan directories containing others' confidential work.
"""

import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Default scan root = current working directory (override with DOPA_GIT_ROOT).
WORKSPACE_ROOT = Path(os.environ.get("DOPA_GIT_ROOT", str(Path.cwd())))

# Sub-dirs under the root to scan for repos (override with DOPA_GIT_SCAN_DIRS,
# comma-separated). Default scans the root itself.
DEFAULT_SCAN_DIRS = [
    d.strip() for d in os.environ.get("DOPA_GIT_SCAN_DIRS", ".").split(",") if d.strip()
]


def find_repos(root: Path = WORKSPACE_ROOT, scan_dirs: list[str] | None = None) -> list[Path]:
    """Find git repos in workspace by locating .git files/dirs."""
    repos = []
    dirs = scan_dirs or DEFAULT_SCAN_DIRS
    for d in dirs:
        scan_path = root / d
        if not scan_path.exists():
            continue
        # Find .git files (worktrees) or .git dirs (regular repos)
        for git_path in scan_path.rglob(".git"):
            if git_path.is_dir():
                repos.append(git_path.parent)
            elif git_path.is_file():
                # Worktree — extract the actual working directory
                repos.append(git_path.parent)
    return repos


def git_log_since(repo: Path, since: datetime) -> list[dict]:
    """Get commits since a given time, with author timestamp."""
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo), "log",
                f"--since={since.isoformat()}",
                "--all",
                "--format=%H|%aI|%s",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.debug(f"git log failed for {repo.name}: {result.stderr.strip()}")
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0][:8],
                    "timestamp": parts[1],
                    "subject": parts[2],
                })
        return commits
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"git log error for {repo.name}: {e}")
        return []


def scan_workspace_activity(
    root: Path = WORKSPACE_ROOT,
    window_minutes: int = 60,
    scan_dirs: list[str] | None = None,
) -> dict:
    """
    Scan workspace repos for recent activity.
    Returns aggregated metrics for the ADHD signal pipeline.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    repos = find_repos(root, scan_dirs)

    if not repos:
        return {"repos_found": 0, "commits": [], "metrics": {}}

    all_commits = []
    active_repos = 0
    repo_commit_counts: dict[str, int] = {}

    for repo in repos:
        commits = git_log_since(repo, since)
        for c in commits:
            c["repo"] = repo.name
        all_commits.extend(commits)
        if commits:
            active_repos += 1
            repo_commit_counts[repo.name] = len(commits)

    # Sort by timestamp
    all_commits.sort(key=lambda c: c["timestamp"])

    # Compute metrics
    metrics = _compute_metrics(all_commits, active_repos, len(repos), repo_commit_counts, window_minutes)

    return {
        "repos_found": len(repos),
        "repos_active": active_repos,
        "total_commits": len(all_commits),
        "commits": all_commits,
        "metrics": metrics,
        "window_minutes": window_minutes,
    }


def _compute_metrics(
    commits: list[dict],
    active_repos: int,
    total_repos: int,
    repo_commit_counts: dict[str, int],
    window_minutes: int,
) -> dict:
    """Derive ADHD-relevant metrics from commit patterns."""
    metrics: dict = {
        "ships_in_window": len(commits),
        "active_repo_count": active_repos,
        "repos_scanned": total_repos,
    }

    if not commits:
        metrics["activity_level"] = "none"
        metrics["avoidance_flag"] = True  # no commits in window = potential avoidance
        return metrics

    # Burst detection: many commits close together = hyperfocus
    if len(commits) >= 5:
        timestamps = [
            datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
            for c in commits
        ]
        if len(timestamps) >= 2:
            span_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
            burst_rate = len(commits) / max(span_seconds, 1) * 3600  # commits per hour
            metrics["burst_rate_commits_per_hour"] = round(burst_rate, 1)
            metrics["burst_detected"] = burst_rate > 3  # >3 commits/hour in window

            # Time clustering: if all commits are in a tight cluster, that's hyperfocus
            if len(timestamps) >= 3:
                gaps = [
                    (timestamps[i + 1] - timestamps[i]).total_seconds()
                    for i in range(len(timestamps) - 1)
                ]
                avg_gap = sum(gaps) / len(gaps)
                metrics["avg_minutes_between_commits"] = round(avg_gap / 60, 1)
                metrics["hyperfocus_pattern"] = avg_gap < 300  # <5 min between commits

    # Hour-of-day clustering — when does shipping actually happen?
    hours = [
        datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00")).hour
        for c in commits
    ]
    if hours:
        metrics["commit_hours"] = hours
        # Late night commits (midnight-5am) = potential hyperfocus or delayed sleep phase
        late_night = sum(1 for h in hours if 0 <= h < 6)
        metrics["late_night_ratio"] = round(late_night / len(hours), 2)

    # Repo switching — high count = scattered, low = focused or avoidance
    metrics["repo_switching"] = active_repos
    if active_repos >= 4:
        metrics["fragmentation_flag"] = True

    # Single-repo deep focus
    if active_repos == 1 and len(commits) >= 3:
        metrics["deep_focus_flag"] = True

    metrics["activity_level"] = (
        "high" if len(commits) >= 5
        else "moderate" if len(commits) >= 2
        else "low"
    )

    return metrics


# ---- ADHD signal extraction (for storing alongside camera observations) ----

def get_git_snapshot(window_minutes: int = 60) -> dict:
    """Lightweight wrapper that returns git activity as a sensor snapshot.
    Designed to be called from the daemon loop alongside camera capture.
    """
    try:
        return scan_workspace_activity(window_minutes=window_minutes)
    except Exception as e:
        logger.error(f"Git sensor failed: {e}")
        return {"error": str(e), "repos_found": 0}
