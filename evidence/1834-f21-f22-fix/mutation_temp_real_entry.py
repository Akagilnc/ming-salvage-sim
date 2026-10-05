"""Temporary mutation: restore old production strip logic at real entries; no permanent tests."""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5")
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB
from ming_sim import rescript_actions as ra

content = GameContent.load(); ctx_bind(content); issues_mod.bind_content(content)
tmpdir = Path(tempfile.mkdtemp(prefix="f21m-", dir="/tmp/1834-f21-f22-probe"))
db_path = str(tmpdir / "probe.db")
db0 = GameDB(db_path, content); db0.seed_static_data(); state = db0.load_state()
issues_mod.sync_opening_legacies(db0, state); db0.close()
db = GameDB(db_path, content); state = db.load_state()
aid = (db.conn.execute("SELECT id FROM armies WHERE id='denglai'").fetchone() or db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone())["id"]
raw_station = "  山海关  "; raw_hl = "  辽饷  "

# CURRENT side
payload = ra.map_rescript_option_or_choice({
    "action_type":"military_order","label":"调驻","hint":"h","assignee_name":"祖大寿",
    "target_kind":"army","target_id":aid,"locality_scope":"none","station":raw_station,
}, db=db, content=content, state=state)
cur_mapper = payload.get("station")==raw_station
parsed_cur = GameDB._parse_highlights_json(json.dumps([raw_hl], ensure_ascii=False))
cur_hl = parsed_cur==[raw_hl]

# OLD logic restored at real functions (monkeypatch), not post-hoc truncation
_orig_map = ra.map_rescript_option_or_choice
_orig_parse = GameDB._parse_highlights_json
_orig_apply = GameDB._apply_military_order_station_effect

def old_map(src, **kw):
    out = _orig_map(src, **kw)
    if isinstance(out, dict) and "station" in out:
        # restore old rewrite: strip before payload keep
        out = dict(out)
        out["station"] = str(src.get("station") or "").strip()
    return out

@staticmethod
def old_parse(raw):
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out=[]
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out

def old_apply(self, state, *, army_id, station, actor, reason, origin_ref, station_region=""):
    # call through with pre-stripped station to simulate old dest=strip(station)
    return _orig_apply(self, state, army_id=army_id, station=str(station or "").strip(), actor=actor, reason=reason, origin_ref=origin_ref, station_region=station_region)

ra.map_rescript_option_or_choice = old_map
GameDB._parse_highlights_json = old_parse
GameDB._apply_military_order_station_effect = old_apply

payload_old = ra.map_rescript_option_or_choice({
    "action_type":"military_order","label":"调驻","hint":"h","assignee_name":"祖大寿",
    "target_kind":"army","target_id":aid,"locality_scope":"none","station":raw_station,
}, db=db, content=content, state=state)
old_mapper = payload_old.get("station")==raw_station
parsed_old = GameDB._parse_highlights_json(json.dumps([raw_hl], ensure_ascii=False))
old_hl = parsed_old==[raw_hl]

# materialize via dossier with old apply patched
payload_raw=dict(payload_old); payload_raw["station"]=raw_station
# unpatch map for create; keep apply patched
ra.map_rescript_option_or_choice = _orig_map
dossier_id = db.create_decree_dossier(state, action_type="military_order", decree_text="调驻", target_kind="army", target_id=aid, payload=payload_raw)
db.apply_dossier_verdicts(state, [{"dossier_id": dossier_id, "decision":"promulgated"}])
after = db.conn.execute("SELECT station FROM armies WHERE id=?", (aid,)).fetchone()["station"]
old_mat = after==raw_station

# restore
GameDB._parse_highlights_json = _orig_parse
GameDB._apply_military_order_station_effect = _orig_apply

print(json.dumps({
  "verdict_old_logic_restored": True,
  "current_mapper_preserved": cur_mapper,
  "current_hl_preserved": cur_hl,
  "old_mapper_preserved": old_mapper,
  "old_hl_preserved": old_hl,
  "old_materialize_preserved": old_mat,
  "old_mapper_station": payload_old.get("station"),
  "old_hl_read": parsed_old,
  "old_materialize_station": after,
}, ensure_ascii=False, indent=2))
assert cur_mapper and cur_hl
assert (not old_mapper) and (not old_hl) and (not old_mat)
print("MUTATION_OK current_green_old_red")
