#!/bin/bash
# F20 enum: current evidence navigation citing revoked disposition authority
set -e
cd /Users/akagilnc/WorkSpace/Ming_LLM-1834-w5
echo '### CMD1 current-nav claims of F16 authority / revoked tables'
rg -n 'Current F16 evidence|Disposition authority|f16_hand_verify_after_ruling|REVOKED_PACKAGING_KEEP|f16_disposition_after_counterexample' \
  evidence/1834-f16-f3-f3r-f17-fix/
echo '### CMD2 report cites of revocation nav'
rg -n 'F17_F3R_REVOCATION|f16_hand_verify_after_ruling|f16_disposition_after_counterexample' \
  evidence/1834-f16-f3-f3r-f17-fix/report.md
