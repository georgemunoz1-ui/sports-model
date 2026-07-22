#!/bin/bash
# Nightly durability push. Requires: git remote 'origin' + stored credential (set up once).
cd /home/claude/work/sportsmodel
git add -A
git -c user.email=agent@local -c user.name=harness commit -qm "auto: $(date -u +%Y-%m-%dT%H:%MZ) cycle" 2>/dev/null
git push -q origin main 2>&1 | tail -1
