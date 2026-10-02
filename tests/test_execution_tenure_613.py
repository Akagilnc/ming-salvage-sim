"""#613 执行侧任别读端：执行格/月末推演号令力 + #611 授权投影共用。"""
from ming_sim.appointment_tenure import command_power_rank, execution_distortion_weight
import ming_sim.decree as decree_mod
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




def _live_exec_side(db, state, dossier):
    """执行侧读端真链：execution_side_read_fields（#613）。"""
    return decree_mod.execution_side_read_fields(db, state, dossier)


def test_td8_same_office_four_tenures_live_assembly_chain(game):
    db, state, _content = game
    holder = _ministers(db, 1)[0]
    office = str(db.conn.execute('SELECT office FROM characters WHERE name=?', (holder,)).fetchone()['office'])
    observed = []
    for tenure in VALID_TENURES:
        _set_tenure(db, holder, tenure, office=office)
        current_office = str(db.conn.execute('SELECT office FROM characters WHERE name=?', (holder,)).fetchone()['office'])
        assert current_office == office
        consumer = _executing_policy(db, state, holder, target_id=f'td8-same-office-{tenure}')
        hit = _live_exec_side(db, state, consumer)
        assert hit['appointment_tenure'] == tenure
        assert hit['command_power_rank'] == command_power_rank(tenure)
        assert hit['distortion_weight'] == execution_distortion_weight(tenure)
        assert 'payload-auth' not in hit['authorization_ids']
        assert 'payload-list' not in hit['authorization_ids']
        observed.append(hit)
    ranks = [row['command_power_rank'] for row in observed]
    assert ranks == sorted(ranks, reverse=True)
    weights = [row['distortion_weight'] for row in observed]
    assert weights == sorted(weights)
    by_tenure = {row['appointment_tenure']: row for row in observed}
    assert by_tenure['真除']['distortion_weight'] < by_tenure['兼署']['distortion_weight'] < by_tenure['署理']['distortion_weight']
    assert by_tenure['兼署']['command_power_rank'] != by_tenure['真除']['command_power_rank']
    assert by_tenure['兼署']['command_power_rank'] != by_tenure['署理']['command_power_rank']

def _clear_character_offices(db, name):
    """人物仍在 characters，但 character_offices 无行（缺档合法态）。"""
    db.conn.execute('DELETE FROM character_offices WHERE character_name=?', (name,))
    db.conn.commit()
    assert db.conn.execute('SELECT 1 FROM character_offices WHERE character_name=?', (name,)).fetchone() is None
    assert db.conn.execute('SELECT 1 FROM characters WHERE name=?', (name,)).fetchone() is not None
