"""#613 执行侧任别读端：执行格/月末推演号令力 + #611 授权投影共用。"""
import pytest
from ming_sim.appointment_tenure import AUTHORITY_COMMAND_RELIEF, COMMAND_POWER_RANK, DEFAULT_APPOINTMENT_TENURE, command_power_rank, execution_distortion_weight
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGES, AUTHORITY_PRIVILEGE_SET
from ming_sim.db import GameDB
import ming_sim.decree as decree_mod
from tests.test_authority_ledger_611 import _eligible_dossier, _grant, _revoke
VALID_TENURES = ('真除', '兼署', '署理', '加衔')

def _ministers(db, n=4):
    rows = db.conn.execute("SELECT name FROM characters WHERE status='active' AND power_id='ming' AND office_type NOT IN ('后宫','宗藩') ORDER BY name LIMIT ?", (n,)).fetchall()
    return [str(row['name']) for row in rows]

def _set_tenure(db, name, tenure, office=None):
    """Write character_offices.appointment_tenure via the production scope helper."""
    from ming_sim.issues import _appointment_tenure_scope
    row = db.conn.execute('SELECT office, office_type FROM characters WHERE name=?', (name,)).fetchone()
    target_office = office or str(row['office'] or name)
    with _appointment_tenure_scope(db, tenure):
        db.set_character_office(name, target_office, office_type='', source='test-613')
    archived = db.conn.execute('SELECT appointment_tenure FROM character_offices WHERE character_name=?', (name,)).fetchone()
    assert archived is not None
    assert str(archived['appointment_tenure']) == tenure

def _executing_policy(db, state, holder, *, target_id='清丈田亩-613', roster=None):
    participants = roster or [{'character_id': holder, 'tier': '主办', 'role': '承办'}]
    dossier_id = db.create_decree_dossier(state, action_type='policy', decree_text='清丈畿辅田亩', target_kind='issue', target_id=target_id, executor_kind='character', executor_id=holder, participants=participants, payload={'authorization_id': 'payload-auth', 'authorization_ids': ['payload-list'], '任别': '加衔'})
    db.apply_dossier_promulgation(state, dossier_id, 'promulgated')
    row = db.get_decree_dossier(dossier_id)
    assert row['status'] == 'executing'
    return row

def test_command_power_four_tier_strict_order_and_jianshu_not_collapsed():
    """TD-8 纯函数：真除＞兼署＞署理＞加衔；兼署不得与相邻档混同；无双逆表。"""
    ranks = {tenure: command_power_rank(tenure) for tenure in VALID_TENURES}
    assert ranks['真除'] > ranks['兼署'] > ranks['署理'] > ranks['加衔']
    assert ranks['兼署'] != ranks['真除']
    assert ranks['兼署'] != ranks['署理']
    assert set(COMMAND_POWER_RANK) == set(VALID_TENURES)
    weights = {tenure: execution_distortion_weight(tenure) for tenure in VALID_TENURES}
    assert weights['真除'] < weights['兼署'] < weights['署理'] < weights['加衔']
    assert weights['兼署'] != weights['真除']
    assert weights['兼署'] != weights['署理']
    max_rank = max(COMMAND_POWER_RANK.values())
    for tenure in VALID_TENURES:
        assert weights[tenure] == max_rank - ranks[tenure]

def test_authority_command_relief_single_source_from_privileges():
    """特权名唯一来自 authority_privileges，不在任别模块第二份拼写。"""
    assert tuple(AUTHORITY_COMMAND_RELIEF.keys()) == AUTHORITY_PRIVILEGES
    assert set(AUTHORITY_COMMAND_RELIEF) == AUTHORITY_PRIVILEGE_SET
    assert AUTHORITY_COMMAND_RELIEF['尚方剑密授'] > AUTHORITY_COMMAND_RELIEF['便宜行事']

def test_held_authority_privileges_reduce_distortion_weight():
    base = execution_distortion_weight('署理', [])
    for privilege in AUTHORITY_PRIVILEGES:
        eased = execution_distortion_weight('署理', [{'privilege': privilege}])
        assert eased < base, privilege
    assert execution_distortion_weight('署理', [{'privilege': '尚方剑密授'}]) < execution_distortion_weight('署理', [{'privilege': '便宜行事'}])


def _clear_character_offices(db, name):
    """人物仍在 characters，但 character_offices 无行（缺档合法态）。"""
    db.conn.execute('DELETE FROM character_offices WHERE character_name=?', (name,))
    db.conn.commit()
    assert db.conn.execute('SELECT 1 FROM character_offices WHERE character_name=?', (name,)).fetchone() is None
    assert db.conn.execute('SELECT 1 FROM characters WHERE name=?', (name,)).fetchone() is not None
