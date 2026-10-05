# F21 freeish crop-write candidates (NOT auto-KEEP; chase dataflow)
ALL_CROP_WRITE_SHAPES=1721 FREEISH_NAME_CANDIDATES=132

| path:line | shape | targets | src |
|---|---|---|---|
| `ming_sim/action_clusters.py:255` | assign | label | `label = str(obj.get("动作类型") or "").strip()` |
| `ming_sim/action_materialize.py:1035` | assign | text | `text = value.strip()` |
| `ming_sim/action_materialize.py:1259` | assign | body | `body = (` |
| `ming_sim/appointment_tenure.py:46` | assign | text | `text = str(value or "").strip()` |
| `ming_sim/assets.py:27` | assign | text | `text = file.read().strip()` |
| `ming_sim/audience_night.py:697` | assign | message | `message = (` |
| `ming_sim/audience_night.py:757` | assign | message | `message = f"死账校验失败：已殁者不可{context}：{('、'.join(dead))}"` |
| `ming_sim/audience_night.py:1994` | assign | text | `text = str(message or "").strip()` |
| `ming_sim/audience_night.py:2019` | assign | text | `text = str(message or "").strip()` |
| `ming_sim/audience_translate.py:246` | assign | body | `body = "\n".join(lines)` |
| `ming_sim/breach_plea.py:81` | assign | text | `text = str(origin_ref or "").strip()` |
| `ming_sim/breach_plea.py:95` | assign | text | `text = str(origin_context or "").strip()` |
| `ming_sim/centrifuge_ledger.py:99` | assign | text | `text = str(value).strip()` |
| `ming_sim/cli_backend.py:864` | assign | text | `text = (stdout_text + stderr).split("OpenAI Codex v")[0]` |
| `ming_sim/cli_backend.py:896` | assign | text | `text = "".join(` |
| `ming_sim/cli_backend.py:1310` | append | <append> | `lines.append(f"{name}（别名：{'、'.join(aliases)}）")` |
| `ming_sim/cli_backend.py:2572` | assign | title | `title = str(` |
| `ming_sim/cli_backend.py:2578` | assign | body | `body = str(` |
| `ming_sim/cli_backend.py:3504` | assign | body | `body = t[i:j + 1]` |
| `ming_sim/content.py:313` | append | <append> | `events.append(` |
| `ming_sim/context.py:267` | append | <append> | `parts.append("；".join(bits))` |
| `ming_sim/covert_progress.py:133` | assign | text | `text = str(raw or "").strip()` |
| `ming_sim/covert_progress.py:159` | assign | text | `text = str(seed_guilt or "").strip()` |
| `ming_sim/covert_progress.py:312` | assign | text | `text = str(raw or "").strip()` |
| `ming_sim/covert_progress.py:792` | assign | text | `text = str(raw or "").strip()` |
| `ming_sim/credit_events.py:65` | assign | text | `text = str(origin or "").strip()` |
| `ming_sim/credit_events.py:98` | assign | text | `text = str(part or "").strip()` |
| `ming_sim/db.py:6155` | append | <append> | `clauses.append(f"name IN ({','.join('?' for _ in wanted)})")` |
| `ming_sim/db.py:7380` | assign | reason | `reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")` |
| `ming_sim/db.py:7882` | append | <append> | `own.append(` |
| `ming_sim/db.py:7899` | append | <append> | `other.append(` |
| `ming_sim/db.py:7981` | assign | reason | `reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")` |
| `ming_sim/db.py:8807` | assign | reason | `reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")` |
| `ming_sim/db.py:12997` | append | <append> | `out.append({` |
| `ming_sim/db.py:13666` | assign | display | `display = {` |
| `ming_sim/db.py:13857` | append | <append> | `base_roster.append({` |
| `ming_sim/db.py:14246` | append | <append> | `roster.append({` |
| `ming_sim/db.py:16677` | assign | title | `title = str(payload.get("target_id") or "").strip()` |
| `ming_sim/db.py:18522` | kwarg | decree_text | `return self._materialize_office_appointment_dossier(` |
| `ming_sim/db.py:19960` | assign | text | `text = payload_json.strip()` |
| `ming_sim/db.py:19992` | assign | text | `text = str(raw).strip()` |
| `ming_sim/db.py:20624` | assign | text | `text = str(value).strip().lower()` |
| `ming_sim/decree_vocabulary.py:372` | append | <append> | `facts.append("标记：" + "、".join(markers))` |
| `ming_sim/due_review.py:49` | assign | text | `text = str(entry_kind or ENTRY_KIND_STAGED).strip()` |
| `ming_sim/due_review.py:77` | assign | text | `text = str(origin_ref or "").strip()` |
| `ming_sim/entities/affair/store.py:463` | append | <append> | `out.append({` |
| `ming_sim/entities/affair/store.py:542` | assign | text | `text = str(origin_ref or "").strip()` |
| `ming_sim/execution_pressure.py:52` | assign | text | `text = str(raw).strip()` |
| `ming_sim/execution_pressure.py:142` | append | <append> | `parts.append(f"{kinds}∈{'/'.join(sorted(scopes))}")` |
| `ming_sim/fiscal_fact_brief.py:569` | append | <append> | `entries.append({` |
| `ming_sim/fiscal_fact_brief.py:589` | append | <append> | `lines.append("\t".join([` |
| `ming_sim/flows.py:1591` | assign | reason | `reason = str(item.get("reason") or "").strip()` |
| `ming_sim/highlight_judge.py:26` | assign | text | `text = str(raw or "").strip()` |
| `ming_sim/issues.py:232` | assign | text | `text = str(origin_ref or "").strip()` |
| `ming_sim/issues.py:506` | assign | text | `text = str(resolve_condition or "").strip()` |
| `ming_sim/issues.py:516` | assign | text | `text = str(resolve_condition or "").strip()` |
| `ming_sim/issues.py:806` | assign | display | `display = str(create.get("display") or "").strip() or (db._stem_of(str(create.get("key") or "")) or str(create.get("key") or ""))` |
| `ming_sim/issues.py:2198` | append | <append> | `candidates.append({` |
| `ming_sim/issues.py:2325` | assign | reason | `reason = f"人物核心主体永久死亡：{', '.join(dead_subjects)}"` |
| `ming_sim/issues.py:2843` | assign | title | `title = str(item.get("new_title") or item.get("title") or "").strip()` |
| `ming_sim/issues.py:4385` | append | <append> | `warns.append(` |
| `ming_sim/issues.py:4389` | append | <append> | `warns.append(` |
| `ming_sim/issues.py:4397` | append | <append> | `warns.append(` |
| `ming_sim/issues.py:5221` | assign | reason | `reason = str(cl.get("reason") or "").strip().lower()` |
| `ming_sim/issues.py:6158` | assign | title | `title = str(item.get("new_title") or item.get("title") or "").strip()` |
| `ming_sim/issues.py:8064` | append | <append> | `applied_person_changes.append({` |
| `ming_sim/issues.py:8489` | append | <append> | `applied_person_changes.append({` |
| `ming_sim/issues.py:8499` | append | <append> | `created_armies.append({` |
| `ming_sim/issues.py:8589` | append | <append> | `event_person_results.append({` |
| `ming_sim/issues.py:8750` | assign | display | `display = str(create.get("display") or "").strip() or (db._stem_of(key) or key)` |
| `ming_sim/matching.py:69` | append | <append> | `aliases.append(part.strip())` |
| `ming_sim/matching.py:102` | assign | text | `text = str(raw).strip()` |
| `ming_sim/matching.py:180` | append | <append> | `aliases.append(part.strip())` |
| `ming_sim/matching.py:202` | assign | text | `text = str(raw).strip()` |
| `ming_sim/materials.py:96` | assign | text | `text = str(name or "").strip() or "未名"` |
| `ming_sim/materials.py:276` | append | <append> | `out.append(str(item.relative_to(root_r)).replace("\\", "/"))` |
| `ming_sim/materials.py:299` | assign | text | `text = str(value or "").strip()` |
| `ming_sim/materials.py:479` | assign | opening_text | `opening_text = raw_latest if raw_latest.strip() else "见目录。"` |
| `ming_sim/materials.py:529` | assign | situation | `situation = raw_situation if raw_situation.strip() else "见目录。"` |
| `ming_sim/materials.py:553` | assign | situation | `situation = raw_situation if raw_situation.strip() else "见目录。"` |
| `ming_sim/materials.py:564` | assign | text | `text = f"{body}（尚未入档）" if body.strip() else "尚未入档"` |
| `ming_sim/materials.py:587` | append | <append> | `lines.append({` |
| `ming_sim/materials.py:645` | append | <append> | `handled.append(visible[dir_key][:2])` |
| `ming_sim/materials.py:709` | append | <append> | `parts.append(spoken if spoken.strip() else "（尚无）")` |
| `ming_sim/materials.py:802` | assign | body | `body = "\n".join(` |
| `ming_sim/materials.py:1108` | append | <append> | `affairs.append({` |
| `ming_sim/materials.py:1580` | append | <append> | `rows.append(("封闭结局", "、".join(item["terminal_reason_labels"])))` |
| `ming_sim/materials.py:1581` | assign | body | `body = "\n".join(f"{label}：{value}" for label, value in rows)` |
| `ming_sim/materials.py:1616` | assign | body | `body = "\n".join(` |
| `ming_sim/materials.py:2219` | append | <append> | `parts.append(spoken if spoken.strip() else "（尚无）")` |
| `ming_sim/month_chain.py:1755` | assign | body | `body = event_id[len(_DECREE_QUESTION_PREFIX):]` |
| `ming_sim/office_rank.py:31` | assign | text | `text = str(office or "").strip()` |
| `ming_sim/office_rank.py:34` | assign | text | `text = re.sub(r"^(?:前/原任/原)", "", text).strip()` |
| `ming_sim/office_rank.py:35` | assign | text | `text = (text.replace("兼掌", ",").replace("兼署", ",").replace("兼", ",")` |
| `ming_sim/office_rank.py:69` | assign | text | `text = str(title or "").strip()` |
| `ming_sim/relation_read.py:104` | assign | summary | `summary = "\n".join(summary_parts)` |
| `ming_sim/rescript_actions.py:472` | assign | label | `label = str(req.get("label") or "").strip()` |
| `ming_sim/rescript_actions.py:704` | assign | decree_text | `decree_text = note_raw if note_raw.strip() else label_raw` |
| `ming_sim/rescript_actions.py:1180` | kwarg | decree_text | `dossier_id = int(db.create_decree_dossier(` |
| `ming_sim/rescript_draft.py:379` | append | <append> | `bits.append("必填" + "/".join(str(k) for k in req))  # type: ignore[union-attr]` |
| `ming_sim/rescript_draft.py:381` | append | <append> | `bits.append("须具其一" + "/".join(str(k) for k in group))  # type: ignore[union-attr]` |
| `ming_sim/rescript_draft.py:386` | append | <append> | `bits.append(` |
| `ming_sim/rescript_draft.py:393` | append | <append> | `bits.append(` |
| `ming_sim/rescript_draft.py:398` | append | <append> | `bits.append("target_kind∈" + "/".join(str(k) for k in tk))  # type: ignore[union-attr]` |
| `ming_sim/rescript_draft.py:406` | append | <append> | `bits.append(` |
| `ming_sim/rescript_draft.py:411` | append | <append> | `bits.append("可填" + "/".join(str(k) for k in opt))  # type: ignore[union-attr]` |
| `ming_sim/rescript_draft.py:413` | append | <append> | `parts.append(f"{action}（" + "；".join(bits) + "）")` |
| `ming_sim/rescript_draft.py:528` | assign | text | `text = str(val).strip()` |
| `ming_sim/rescript_draft.py:1153` | assign | text | `text = match.group(1).strip()` |
| `ming_sim/rescript_draft.py:1155` | assign | text | `text = raw.strip()` |
| `ming_sim/session.py:1310` | assign | answer | `answer = "".join(chunks)` |
| `ming_sim/session.py:2314` | append | <append> | `out.append({` |
| `ming_sim/settlement_payload.py:37` | assign | label | `label = str(option.get("label") or "").strip()` |
| `ming_sim/settlement_payload.py:192` | assign | title | `title = str(item.get("title") or "").strip()` |
| `ming_sim/settlement_payload.py:213` | assign | title | `title = str(out.get("title") or "").strip()` |
| `ming_sim/staged_commitment.py:41` | assign | text | `text = raw.strip()` |
| `ming_sim/staged_commitment.py:99` | assign | text | `text = stages.strip()` |
| `ming_sim/staged_commitment.py:250` | assign | criterion | `criterion = title if title.strip() else "依限奏报"` |
| `ming_sim/staged_commitment.py:255` | append | <append> | `due.append({` |
| `ming_sim/supervision.py:185` | assign | text | `text = str(raw or "").strip()` |
| `ming_sim/supervision.py:223` | assign | body | `body = raw[len(ns):]` |
| `ming_sim/value_matrix.py:51` | assign | text | `text = str(raw or "").strip()` |
| `scripts/jisi_army_dispatch_probe.py:135` | append | <append> | `results.append({` |
| `scripts/military_flow_probe.py:150` | append | <append> | `results.append({` |
| `scripts/play_as_emperor.py:217` | assign | text | `text = raw.strip()` |
| `scripts/play_as_emperor.py:480` | append | <append> | `state.history.append({"step": step, "prompt": prompt_hint.strip(), "reasoning": reasoning, "input": action})` |
| `web/src/highlights.ts:41` | ts_line | — | `segments.push({ text: displayContent.slice(cursor), highlight: false });` |
| `web/src/highlights.ts:45` | ts_line | — | `segments.push({ text: displayContent.slice(cursor, bestIdx), highlight: false });` |
| `web/src/useSettlementFlow.ts:300` | ts_line | report | `const report = fromPayload.trim() ? fromPayload : fromState;` |
| `web_app.py:244` | assign | text | `text = text.replace(src, dst)` |
| `web_app.py:879` | append | <append> | `out.append({` |
| `web_app.py:3083` | assign | text | `text = str(cur).strip()` |
