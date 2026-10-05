#!/bin/bash
set +e
cd /Users/akagilnc/WorkSpace/Ming_LLM-1834-w5
echo '### CMD1 constants+symbols'
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' \
  'AMBIGUOUS_CLOSE_COMMANDS|STAY_ATTEND_COMMANDS|CMD_AMBIGUOUS_CLOSE|CMD_STAY_ATTEND|TAG_STAY_ATTEND|stay_attend_in_audience|_ensure_close_night_confirm_cue|陛下是要退朝么'
echo "CMD1_EXIT=$?"
echo '### CMD2 phrase hits (retired phrases; comments noting deletion OK)'
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' \
  '留下听着|今日就到这里吧'
echo "CMD2_EXIT=$?"
