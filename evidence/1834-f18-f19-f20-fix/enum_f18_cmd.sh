#!/bin/bash
# F18 full-repo enum: retired audience command cuts + character dialogue cues.
# Coverage: entire worktree (includes docs/archive/evidence). No path excludes.
set +e
cd /Users/akagilnc/WorkSpace/Ming_LLM-1834-w5
echo '### F18 CMD1 symbols+cues (full repo)'
rg -n 'AMBIGUOUS_CLOSE_COMMANDS|STAY_ATTEND_COMMANDS|CMD_AMBIGUOUS_CLOSE|CMD_STAY_ATTEND|TAG_STAY_ATTEND|stay_attend_in_audience|_ensure_close_night_confirm_cue|陛下是要退朝么|ambiguous_close|stay_attend'
echo "CMD1_EXIT=$?"
echo '### F18 CMD2 retired phrases (full repo)'
rg -n '留下听着|今日就到这里吧'
echo "CMD2_EXIT=$?"
echo '### F18 CMD3 active court-break / dismiss seam (full repo; keep class)'
rg -n 'recognize_audience_command|COURT_BREAK_COMMANDS|CMD_CLOSE_NIGHT|MINISTER_DISMISS_COMMANDS'
echo "CMD3_EXIT=$?"
