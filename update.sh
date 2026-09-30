#!/bin/bash
# hourly mind backup for MEOW agent
BK=/home/agentuser/agent-backup
SRC=/home/agentuser/.hermes
mkdir -p $BK
for d in memories cron plugins; do
  [ -d $SRC/$d ] && cp -rL $SRC/$d $BK/ 2>/dev/null
done
cp $SRC/config.yaml $BK/ 2>/dev/null
rsync -a --exclude Hellgram $SRC/skills/ $BK/skills/ 2>/dev/null
mkdir -p $BK/skills/Hellgram-meta
for f in SKILL.md FEATURES.md upstream-commit series; do cp -r $SRC/skills/Hellgram/$f $BK/skills/Hellgram-meta/ 2>/dev/null; done
for f in patches scripts; do cp -r $SRC/skills/Hellgram/$f $BK/skills/Hellgram-meta/ 2>/dev/null; done
date > $BK/.last_backup
