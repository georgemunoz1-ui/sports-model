#!/bin/bash
# Nightly durability push. Requires: git remote 'origin' + stored credential (set up once).
cd /home/claude/work/sportsmodel
git add -A
git -c user.email=agent@local -c user.name=harness commit -qm "auto: $(date -u +%Y-%m-%dT%H:%MZ) cycle" 2>/dev/null
# 2026-08-21: was `git push -q origin main`. `main` is a 1-commit, 2-file stub with NO common
# ancestry with the working branch, so this pushed nothing, exited 0, and the runbook's
# WARN-on-failure path never fired. HEAD is branch-agnostic and pushes the checked-out branch.
git push -q origin HEAD 2>&1 | tail -1
