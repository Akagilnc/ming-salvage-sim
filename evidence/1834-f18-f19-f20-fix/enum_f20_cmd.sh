#!/bin/bash
# F20 full-repo enum: revoked disposition materials + current-nav reference chains.
# Coverage: entire worktree (includes docs/archive/evidence). No path excludes.
set +e
cd /Users/akagilnc/WorkSpace/Ming_LLM-1834-w5
echo '### F20 CMD1 Current/Disposition authority claims (full repo)'
rg -n 'Current F16 evidence|Current F3-R evidence|Current F17|Disposition authority|REVOKED_PACKAGING_KEEP|REVOKED_STUB|REVOKED_TEMPLATE|REVOKED_STALE|REVOKED_AST'
echo "CMD1_EXIT=$?"
echo '### F20 CMD2 revoked / current disposition basenames (full repo)'
rg -n 'f16_hand_verify_after_ruling|f16_disposition_after_counterexample|f16_hand_member_table|f3r_hand_member_table|F17_F3R_REVOCATION|enum_f16_rewrite_shapes_rerun|enum_f16_all_candidates|enum_f16_ast_rewrite|enum_f16_supply_path_after'
echo "CMD2_EXIT=$?"
echo '### F20 CMD3 live claims Current F16 / Disposition authority = hand_verify'
rg -n 'Current F16 evidence\s*=\s*f16_hand_verify|Disposition authority\s*=\s*f16_hand_verify'
echo "CMD3_EXIT=$?"
echo '### F20 CMD4 *.REVOKED* marker files'
find evidence docs archive -name '*REVOKED*' 2>/dev/null | sort
echo "CMD4_FIND_DONE"
