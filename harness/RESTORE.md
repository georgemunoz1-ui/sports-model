# DISASTER RESTORE (container reclaimed / repo gone)
1. Get the latest `sportsmodel_backup_*.bundle` from Taco (sent via chat on Sundays + after big changes).
2. `mkdir -p /home/claude/work && cd /home/claude/work`
3. `git clone sportsmodel_backup_YYYY-MM-DD.bundle sportsmodel && cd sportsmodel && git checkout main`
4. `python3 harness/healthcheck.py` — then resume normal cycles per AGENTS.md.
5. Re-grade any days between bundle date and today from statsapi (runbook postgame, per missing date).
If no bundle available: the conversation record + statsapi can rebuild everything (proven 2026-07-22),
but it costs a session. Bundles are cheaper. If a GitHub origin exists: `git clone <url>` instead.
