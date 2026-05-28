#!/bin/zsh

cd /Users/skyhua/ai-collab || exit 1

print "=== success previews ==="
python3 /Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/preview.py --all --scenario success

print ""
print "=== planner-fail previews ==="
python3 /Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/preview.py --all --scenario planner-fail
