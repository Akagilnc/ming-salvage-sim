# J18 机械枚举成员表

谓词见 j18-enum-cmd.txt（票面全文：双载体承接、专用实况账本、聚合、专用资格校验及配套记录/核算/供料/恢复/旧专测/失效说明）。

合计命中 263，文件 14。

## docs/DELTA_SCHEMA.md (11)
- L382: ``loss = ordered - arrived`。「该路是否实有护送」只认逐路已落实况（`dossier_escort_outcomes`，`
- L383: `由转译 `escort_results` 节落账），不凭案卷关联存在、不凭密令整体成败或结案。仍**不二次扣库**、`
- L398: `### `commissions[].secret_order.escort_pending_targets` — 同夜暗护指向（#1900）`
- L405: `已经成案的当场承接。`GameDB._resolve_covert_escort_carry` 按实际案卷 id 序落笔。`
- L409: `载荷 `escort_sources`（每项 `{secret_order_dossier_id, relation_type, note}`），读缝`
- L410: ``GameDB.escort_source_dossiers_of`。默认批量按 pending id 序提交、拨银先成案时，密令案卷`
- L411: `id 更大，走既有 `escort_links` 关联槽（新密令指旧拨银），不写 `escort_sources`。`
- L413: `护行主体凭据由 `_escort_source_relation` 按「关联槽那条链 ∪ 承接落点那条记录」合取。`
- L415: `「谁护谁」的配对由**单一读口** `GameDB.list_escort_link_pairs()` 出（两处载体取并集，同一对重复时以 0054 槽为准）；权威目标目录的 `escort_link` 行与 `record_monthly_supervision_presence``
- L411: `id 更大，走既有 `escort_links` 关联槽（新密令指旧拨银），不写 `escort_sources`。`
- L414: `受理前已成案的旧拨银仍只走 `escort_links` 声明入口，不进这条暂存承接。`

## docs/adr/0054-ledger-cross-links-and-effect-backrefs.md (1)
- L11: `#1900 的重构验收只引用 [#1812「重构验收（2026-10-02 陛下重定）」](https://github.com/Akagilnc/ming-salvage-sim/issues/1812)。此前本 ADR 指定的 `escort_pending_targets` / `escort_sources` `

## docs/evidence/issue-1571/boundary-inventory.md (2)
- L135: `- 13 个 → supervision 子模块（6 公开 #22-24/#26-28 + 7 私有实现件；`trigger_supervision_countermeasures` 拆分移段适配器组，其纯读半析出 supervision 公开第 7 入口 `list_supervision_countermeasur`
- L166: `| `_grant_escort_presence` | db.py:12826-12834 | 子模块 reconciliation |  |`

## docs/evidence/issue-1571/pr-slices.md (2)
- L125: `- 内容：`_grant_escort_presence`（9）、`list_monthly_grant_reconciliation_targets`（42）、`list_dossier_reconciliations`（29）、`list_open_grant_reconciliations`（22）、`recor`
- L128: `- 依赖：PR-2（`merge_execution_note` 叶与颁赏纯件 `_grant_allocation_is_monthly/honorific` 均已进 kernel）、PR-5（`list_dossier_links`——`_grant_escort_presence` 用）。`

## ming_sim/audience_translate.py (21)
- L46: `"escort_results",`
- L223: `# #1900：在途拨帑案卷与其已立的护送关联——escort_links / escort_results 只认这里`
- L229: `escorted = db._grant_escort_presence(int(row["id"]))`
- L240: `# #1900：「谁护谁」的配对行。单一读口 list_escort_link_pairs 出 0054 槽的链`
- L241: `# 与同夜承接记录；escort_links / escort_results 只认这里的精确案卷 id。`
- L242: `for pair in db.list_escort_link_pairs():`
- L258: `"escort_links 与 escort_results 的案卷 id 必须取对应目录中的精确 id，禁止编造。\n"`
- L307: `'"escort_pending_targets": [{"pending_action_id": "被暗护的拨银交办在本夜暂存清单里的 id", '`
- L340: `'  "escort_results": [\n'`
- L438: `"被护数笔就写几条；只交代「谁护谁」，此路此趟究竟护没护成由 escort_results 另报，"`
- L441: `"escort_pending_targets 按【本夜暂存清单】里那道拨银交办的 id 指过去（暗护的案卷"`
- L447: `"同样由 escort_results 另报，escort_source_dossier_id 留空。\n"`
- L45: `"escort_links",`
- L213: `# 前者。不列这一行，escort_links 在真实流程里第一次根本无从指向。`
- L223: `# #1900：在途拨帑案卷与其已立的护送关联——escort_links / escort_results 只认这里`
- L241: `# 与同夜承接记录；escort_links / escort_results 只认这里的精确案卷 id。`
- L258: `"escort_links 与 escort_results 的案卷 id 必须取对应目录中的精确 id，禁止编造。\n"`
- L336: `'  "escort_links": [\n'`
- L436: `"- 命人护行／沿途照看某笔**在途拨帑** → escort_links 一条，escort_source_dossier_id 填【权威目标目录】"`
- L442: `"此刻还没成案，指不到 dossier 行）；已成案的旧拨银仍走上面的 escort_links。\n"`
- L443: `"- **本场新交办的拨银自带押解**（「着某人押解护送」）→ 不另立密令、不另挂 escort_links，"`

## ming_sim/audience_translation.py (2)
- L316: `escort_links=empty, escort_results=empty,`
- L316: `escort_links=empty, escort_results=empty,`

## ming_sim/db.py (56)
- L1592: `CREATE TABLE IF NOT EXISTS dossier_escort_outcomes (`
- L1606: `CREATE INDEX IF NOT EXISTS idx_dossier_escort_outcomes_source`
- L1607: `ON dossier_escort_outcomes(escort_source_dossier_id, turn, id);`
- L9231: `"dossier_escort_outcomes": "id",`
- L12172: `def record_dossier_escort_result(`
- L12204: `return self._insert_escort_outcome(`
- L12214: `relation = self._escort_source_relation(did, sid)`
- L12217: `return self._insert_escort_outcome(`
- L12221: `def _escort_source_relation(self, grant_dossier_id: int, source_dossier_id: int) -> Optional[str]:`
- L12227: ```escort_sources`` 里记回指。`
- L12229: `关系类型一律取自既有真源，经 :meth:`list_escort_link_pairs` 单一读口，`
- L12234: `for pair in self.list_escort_link_pairs():`
- L12242: `def _insert_escort_outcome(`
- L12248: `INSERT INTO dossier_escort_outcomes`
- L12264: `return self.list_dossier_escort_outcomes(did, through_turn=int(turn))[-1]`
- L12267: `def _coerce_escort_outcome_row(row: Any) -> Dict[str, object]:`
- L12279: `def list_dossier_escort_outcomes(`
- L12283: `sql = "SELECT * FROM dossier_escort_outcomes WHERE dossier_id=?"`
- L12290: `self._coerce_escort_outcome_row(row)`
- L12294: `def list_escort_outcomes_for_source(self, source_dossier_id: int) -> List[Dict[str, object]]:`
- L12297: `"SELECT * FROM dossier_escort_outcomes "`
- L12301: `return [self._coerce_escort_outcome_row(row) for row in rows]`
- L12303: `def _same_night_grant_commission(`
- L12308: `受理时的资格见 :meth:`_is_staged_grant_commission`（还须仍 pending、尚未成案）。`
- L12330: `def _is_staged_grant_commission(`
- L12338: `if not self._same_night_grant_commission(`
- L12355: `def _carry_pending_covert_escort_targets(`
- L12363: `:meth:`_resolve_covert_escort_carry` 当场承接；若仍未成案，指向留到它成案。`
- L12366: `raw = payload.get("escort_pending_targets")`
- L12391: `if not self._same_night_grant_commission(`
- L12406: `self._write_dossier_payload_key(int(dossier["id"]), "escort_pending_targets", resolved)`
- L12407: `self._resolve_covert_escort_carry(commit=commit)`
- L12409: `def _resolve_covert_escort_carry(self, *, commit: bool = False) -> None:`
- L12414: ```escort_sources``（关联槽要求新指旧，装不下旧密令指向新拨银）。`
- L12426: `).get("escort_pending_targets")`
- L12466: `sources = payload.get("escort_sources")`
- L12476: `grant_dossier_id, "escort_sources", sources,`
- L12481: `escort_dossier_id, "escort_pending_targets", remaining,`
- L12485: `def escort_source_dossiers_of(self, dossier_id: int) -> List[Dict[str, object]]:`
- L12493: `sources = payload.get("escort_sources")`
- L12498: `def list_covert_escorts_aimed_at_pending(`
- L12504: `只读密令案卷载荷上已经校验过的 ``escort_pending_targets``。`
- L12513: `targets = self._dossier_payload_dict(dossier_id).get("escort_pending_targets")`
- L12556: `def escort_route_ledger_text(self) -> str:`
- L12576: `SELECT dossier_id FROM dossier_escort_outcomes`
- L12593: `escorted, source, _relation, note = self._grant_escort_presence(dossier_id)`
- L12602: `def list_escort_link_pairs(self) -> List[Dict[str, object]]:`
- L12606: `走 ``escort_sources``（关联槽装不下旧密令指向新拨银，见 ADR 0054）。`
- L12622: `for entry in self.escort_source_dossiers_of(int(row["id"])):`
- L12657: `def _grant_escort_presence(`
- L12668: `"SELECT * FROM dossier_escort_outcomes WHERE dossier_id=? "`
- L12749: `escorted, source_id, relation, note = self._grant_escort_presence(`
- L12824: `实际护送（``_grant_escort_presence``），二者皆引擎定，代码无软判可 clamp。`
- L12913: `pair for pair in self.list_escort_link_pairs()`
- L18745: `self._carry_pending_covert_escort_targets(`
- L19703: `self._resolve_covert_escort_carry(commit=commit)`

## ming_sim/declaration_dispatch.py (32)
- L143: `escort_results: SectionResult`
- L165: `escort_results=self.escort_results.merge(other.escort_results),`
- L173: `"inquiries", "rushes", "travel_tones", "escort_links", "escort_results",`
- L186: `escort_links=empty, escort_results=empty,`
- L333: `escort_links=_dispatch_escort_links(`
- L336: `escort_results=_dispatch_escort_results(`
- L337: `db, state, declaration.get("escort_results"), source=source,`
- L384: `月度拨帑核账各有自己的真源与节拍（``dossier_escort_outcomes`` ＋`
- L701: `("escort_results", "dossier_id"),`
- L1187: `def _covert_pending_targets(`
- L1195: `if "escort_pending_targets" not in secret:`
- L1197: `raw = secret.get("escort_pending_targets")`
- L1216: `if not db._is_staged_grant_commission(`
- L1438: `# 直挂；同夜暂存的拨银交办由 escort_pending_targets 承接。`
- L1440: `kept_targets, target_errors = _covert_pending_targets(`
- L1450: `staged_secret["escort_pending_targets"] = kept_targets`
- L1774: `同夜暂存拨银的暗护指向由调用方放入已校验的 ``escort_pending_targets``。`
- L1794: `def _escort_source_dossier_id(`
- L1814: `def _dispatch_escort_links(`
- L1820: ```escort_results`` 一节。逐项拒收，坏项不牵连同批合法项。`
- L1828: `source_id = _escort_source_dossier_id(db, item.get("escort_source_dossier_id"))`
- L1877: `def _dispatch_escort_results(`
- L1895: `source_id = _escort_source_dossier_id(`
- L1915: `row = db.record_dossier_escort_result(`
- L142: `escort_links: SectionResult`
- L164: `escort_links=self.escort_links.merge(other.escort_links),`
- L173: `"inquiries", "rushes", "travel_tones", "escort_links", "escort_results",`
- L186: `escort_links=empty, escort_results=empty,`
- L333: `escort_links=_dispatch_escort_links(`
- L334: `db, state, declaration.get("escort_links"), source=source,`
- L702: `("escort_links", "target_dossier_id"),`
- L1814: `def _dispatch_escort_links(`

## ming_sim/decree_forecast.py (3)
- L137: `if pending_action_id and hasattr(db, "list_covert_escorts_aimed_at_pending"):`
- L138: `covert_sources = db.list_covert_escorts_aimed_at_pending(int(pending_action_id))`
- L141: `payload["escort_sources"] = list(covert_sources)`

## ming_sim/materials.py (7)
- L966: `if hasattr(db, "list_escort_link_pairs"):`
- L967: `for pair in db.list_escort_link_pairs():`
- L985: `if not hasattr(db, "_grant_escort_presence"):`
- L995: `escorted, source_id, _relation, note = db._grant_escort_presence(dossier_id)`
- L1489: `db.escort_route_ledger_text()`
- L1490: `if hasattr(db, "escort_route_ledger_text") else ""`
- L1719: `escorted, escort_source_id, escort_relation, escort_note = db._grant_escort_presence(`

## ming_sim/month_chain.py (7)
- L1018: `def _escort_route_facts(db: Any, dossier_id: int) -> Dict[str, object]:`
- L1022: `案卷关联反推。这里直接读 ``dossier_escort_outcomes`` 唯一真源。`
- L1025: `"escort_routes": db.list_dossier_escort_outcomes(int(dossier_id)),`
- L1026: `"escort_routes_as_escort_source": db.list_escort_outcomes_for_source(`
- L1038: ```dossier_escort_outcomes`` 读（#1900 读取闭环）。`
- L1047: `row.update(_escort_route_facts(db, int(row.get("dossier_id") or 0)))`
- L1056: `order.update(_escort_route_facts(db, int(dossier["id"])))`

## ming_sim/month_translate.py (1)
- L79: `"- 本段若交代某笔在途拨帑此趟护没护成，按路在 escort_results 逐路声明 escorted"`

## tests/test_escort_route_1900.py (117)
- L6: `- 转译声明 ``commissions[].secret_order`` → 密令暂存／成案核；``escort_pending_targets```
- L8: `拨银的 ``escort_sources``；默认批量按 pending id 序、拨银先成案时走关联槽。单向新指旧，`
- L11: `- 转译声明 ``escort_results`` → ``GameDB.record_dossier_escort_result``（逐路实况）`
- L12: `- ``list_dossier_escort_outcomes`` / ``list_monthly_grant_reconciliation_targets```
- L139: `"escort_results": [`
- L145: `landed = db.list_dossier_escort_outcomes(grant)`
- L161: `assert reopened.list_dossier_escort_outcomes(grant) == landed`
- L162: `assert reopened.list_escort_outcomes_for_source(escort_dossier) == landed`
- L184: `"escort_results": [`
- L192: `by_route = {r["dossier_id"]: r for r in db.list_escort_outcomes_for_source(escort_dossier)}`
- L215: `"escort_results": [`
- L243: `result = _declare(db, state, {"escort_results": [`
- L247: `assert result.escort_results.applied == []`
- L248: `assert [r.category for r in result.escort_results.rejected] == ["invalid_state"]`
- L249: `assert db.list_dossier_escort_outcomes(grant) == []`
- L267: `result = _declare(db, state, {"escort_results": [`
- L271: `assert result.escort_results.applied == []`
- L272: `assert [r.category for r in result.escort_results.rejected] == ["invalid_shape"]`
- L273: `assert db.list_dossier_escort_outcomes(grant) == []`
- L299: `"escort_results": [`
- L314: `assert [item.category for item in result.escort_results.rejected] == ["invalid_state"]`
- L315: `assert [int(row["dossier_id"]) for row in result.escort_results.applied] == [grant]`
- L320: `assert db.list_dossier_escort_outcomes(assignment) == []`
- L338: `"escort_results": [{`
- L343: `assert result.escort_links.applied == [] and result.escort_results.applied == []`
- L345: `assert [r.category for r in result.escort_results.rejected] == ["hallucinated_id"]`
- L359: `"escort_results": [{`
- L377: `assert len(db.list_dossier_escort_outcomes(grant)) == 1`
- L381: `_declare(db, state, {"escort_results": [{`
- L390: `assert [r["turn"] for r in db.list_dossier_escort_outcomes(grant)] == [first, first + 2]`
- L405: `result = _declare(db, state, {"escort_results": [`
- L408: `assert result.escort_results.rejected == []`
- L409: `landed = db.list_dossier_escort_outcomes(grant)`
- L434: `result = _declare(db, state, {"escort_results": [`
- L437: `assert result.escort_results.applied == []`
- L438: `assert [r.category for r in result.escort_results.rejected] == ["invalid_state"]`
- L439: `assert db.list_dossier_escort_outcomes(grant) == []`
- L446: `_declare(db, state, {"escort_results": [`
- L449: `assert db.list_dossier_escort_outcomes(grant) == []`
- L462: `result = _declare(db, state, {"escort_results": [`
- L466: `assert result.escort_results.applied == []`
- L467: `assert [r.category for r in result.escort_results.rejected] == ["hallucinated_id"]`
- L468: `assert db.list_dossier_escort_outcomes(grant) == []`
- L594: `"escort_results": [{`
- L599: `assert result.escort_links.rejected == [] and result.escort_results.rejected == []`
- L600: `landed = db.list_dossier_escort_outcomes(grant)`
- L611: `_declare(db, state, {"escort_results": [`
- L614: `outcomes = db.list_dossier_escort_outcomes(grant)`
- L621: `assert reopened.list_dossier_escort_outcomes(grant) == outcomes`
- L638: `_declare(db, state, {"escort_results": [`
- L641: `keeper = db.list_dossier_escort_outcomes(grant)`
- L665: `_declare(db, state, {"escort_results": [`
- L670: `assert len(db.list_dossier_escort_outcomes(grant)) == 1`
- L671: `assert db.list_dossier_escort_outcomes(grant)[0]["note"] == "本轮改判失护"`
- L672: `assert db.list_dossier_escort_outcomes(new_grant)`
- L677: `assert db.list_dossier_escort_outcomes(grant) == keeper`
- L678: `assert db.list_dossier_escort_outcomes(new_grant) == []`
- L698: `"escort_pending_targets": targets,`
- L799: `# 本例是密令单独先提交：拨银仍暂存，后成案的拨银记 escort_sources。`
- L817: `assert "escort_sources" not in ordinary_payload`
- L819: `assert covert_snap["this_decree"]["payload"]["escort_sources"] == [{`
- L832: `assert "escort_sources" not in stored`
- L837: `declaration={"escort_results": [{`
- L844: `declaration={"escort_results": [{`
- L855: `assert db.escort_source_dossiers_of(covert_dossier) == [{`
- L859: `assert db.escort_source_dossiers_of(ordinary_dossier) == []`
- L862: `assert db.list_escort_link_pairs() == [{`
- L870: `assert settled[ordinary_snap["decree_ref"]].escort_results.rejected == []`
- L871: `assert settled[covert_snap["decree_ref"]].escort_results.rejected == []`
- L872: `ordinary_outcome = db.list_dossier_escort_outcomes(ordinary_dossier)`
- L873: `covert_outcome = db.list_dossier_escort_outcomes(covert_dossier)`
- L921: `assert db.list_escort_link_pairs() == [{`
- L1006: `assert escort["payload"].get("escort_pending_targets") == [{`
- L1012: `assert db.escort_source_dossiers_of(cased_dossier) == []`
- L1013: `assert db.list_escort_link_pairs() == []`
- L1016: `assert db.escort_source_dossiers_of(legal_dossier) == [{`
- L1021: `assert db.escort_source_dossiers_of(cased_dossier) == []`
- L1035: `assert db.escort_source_dossiers_of(cased_dossier) == []`
- L1150: `assert db.escort_source_dossiers_of(dossier_a) == []`
- L1151: `assert db.escort_source_dossiers_of(dossier_b) == []`
- L1165: `assert db.list_escort_link_pairs() == pairs`
- L1166: `lived = _declare(db, state, {"escort_results": [{`
- L1172: `assert lived.escort_results.rejected == []`
- L1174: `outcomes = db.list_dossier_escort_outcomes(dossier_a)`
- L1178: `assert reopened.list_escort_link_pairs() == pairs`
- L1179: `assert reopened.list_dossier_escort_outcomes(dossier_a) == outcomes`
- L1209: `"escort_results": [{`
- L1261: `db.record_dossier_escort_result(`
- L1293: `_declare(db, state, {"escort_results": [{`
- L1309: `assert [(row["escorted"], row["note"]) for row in db.list_dossier_escort_outcomes(plain)] == [`
- L1312: `db.record_dossier_escort_result(`
- L1316: `assert [(row["escorted"], row["note"]) for row in db.list_dossier_escort_outcomes(plain)] == [`
- L10: `- 转译声明 ``escort_links`` → ``GameDB.add_dossier_links``（关联真源，单向新指旧）`
- L68: `result = _declare(db, state, {"escort_links": [`
- L72: `assert result.escort_links.rejected == []`
- L84: `bad = _declare(db, state, {"escort_links": [`
- L92: `assert [r.category for r in bad.escort_links.rejected] == [`
- L95: `assert all(r.reason for r in bad.escort_links.rejected)`
- L115: `_declare(db, state, {"escort_links": [`
- L135: `"escort_links": [`
- L178: `"escort_links": [`
- L211: `"escort_links": [`
- L263: `_declare(db, state, {"escort_links": [`
- L293: `"escort_links": [`
- L307: `assert result.escort_links.applied == [{`
- L312: `assert [item.category for item in result.escort_links.rejected] == ["invalid_state"]`
- L313: `assert result.escort_links.rejected[0].reason`
- L334: `"escort_links": [{`
- L343: `assert result.escort_links.applied == [] and result.escort_results.applied == []`
- L344: `assert [r.category for r in result.escort_links.rejected] == ["hallucinated_id"]`
- L355: `"escort_links": [{`
- L590: `"escort_links": [{`
- L599: `assert result.escort_links.rejected == [] and result.escort_results.rejected == []`
- L633: `_declare(db, state, {"escort_links": [{`
- L1024: `linked = _declare(db, state, {"escort_links": [{`
- L1030: `assert linked.escort_links.rejected == []`
- L1205: `"escort_links": [{`

## tests/test_grant_reconciliation_567.py (1)
- L99: `db.record_dossier_escort_result(`
