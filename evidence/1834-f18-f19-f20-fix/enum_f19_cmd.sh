#!/bin/bash
# F19 full-repo enum: superseded secret-order extract closure + landing shared gates.
# Coverage: entire worktree (includes docs/archive/evidence). No path excludes.
# Call-site proof uses bare "name(" so definitions alone are not counted as consumers.
set +e
cd /Users/akagilnc/WorkSpace/Ming_LLM-1834-w5
echo '### F19 CMD1 extract/assemble/helpers (full repo)'
rg -n '_extract_secret_order|assemble_secret_order_content|_content_reflects_emperor_intent|_merge_secret_content|_split_audience_context|_choose_assignee|_extract_imperative_assignee|_secret_context_|_secret_confirmation_material|_secret_metadata_from_command|_normalize_dossier_link_proposals|confirm_dossier_links|_secret_prefix_needs_recent_context|_SECRET_CONFIRM_ATOM|_CLAUSE_SPLIT|_is_institution_like_name|_ASSIGNEE_'
echo "CMD1_EXIT=$?"
echo '### F19 CMD2 dedicated test names (full repo)'
rg -n 'test_secret_exclusion_extracts|test_extract_secret_order|test_secret_content_assembly|test_secret_extract_traces|_so_json'
echo "CMD2_EXIT=$?"
echo '### F19 CMD3 landing symbols (full repo; classify by call sites)'
rg -n 'secret_order_can_land|secret_order_landing_gaps|compose_secret_order_landing_recovery|_secret_landing_gap_feature|_SECRET_LANDING_GAP_LABELS|secret_order_landing_recovery'
echo "CMD3_EXIT=$?"
echo '### F19 CMD4 call-site proof: compose_secret_order_landing_recovery('
rg -n 'compose_secret_order_landing_recovery\('
echo "CMD4_EXIT=$?"
echo '### F19 CMD5 call-site proof: secret_order_can_land('
rg -n 'secret_order_can_land\('
echo "CMD5_EXIT=$?"
echo '### F19 CMD6 call-site proof: secret_order_landing_gaps('
rg -n 'secret_order_landing_gaps\('
echo "CMD6_EXIT=$?"
