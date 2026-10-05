#!/bin/bash
set +e
cd /Users/akagilnc/WorkSpace/Ming_LLM-1834-w5
echo '### CMD1 extract/assemble/helpers defs+calls (production+tests)'
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' --glob '!TODOS.md' \
  '_extract_secret_order|assemble_secret_order_content|_content_reflects_emperor_intent|_merge_secret_content|_split_audience_context|_choose_assignee|_extract_imperative_assignee|_secret_context_|_secret_confirmation_material|_secret_metadata_from_command|_normalize_dossier_link_proposals|confirm_dossier_links|_secret_prefix_needs_recent_context|_SECRET_CONFIRM_ATOM|_CLAUSE_SPLIT|_is_institution_like_name|_ASSIGNEE_'
echo "CMD1_EXIT=$?"
echo '### CMD2 dedicated tests'
rg -n --glob 'tests/**' \
  '_extract_secret_order|assemble_secret_order_content|test_secret_exclusion_extracts|test_extract_secret_order|test_secret_content_assembly|test_secret_extract_traces|_so_json'
echo "CMD2_EXIT=$?"
echo '### CMD3 keep shared (must remain)'
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' \
  'secret_order_can_land|secret_order_landing_gaps|compose_secret_order_landing_recovery'
echo "CMD3_EXIT=$?"
