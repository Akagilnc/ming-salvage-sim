"""The save file's physical schema: every table, view and index, in one place.

#1889: 新档初始化的建表职责从 ``db.py`` 的大块里拆出。``init_schema`` used to be a
~1300-line inline script, so "which tables exist" was only answerable by reading
one method body. It is now a named module: the schema is one responsibility and
has one owner.

Tables whose lifecycle belongs to an entity store (person_logs, game_state,
metrics, the knowledge ledgers, dossiers, textual facts, affairs, staged
declarations) are **not** here — those stores carry their own DDL, so there is
exactly one definition of each. This module holds only what the engine itself
owns.

Two fragments are filled in from their owning modules so the dossier and
authority-privilege DDL each stay with the code that defines its shape.
"""

from __future__ import annotations

from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SQL_IN
from ming_sim.entities.dossier.store import DOSSIER_SCHEMA_SQL


CORE_SCHEMA_SQL = """
    -- game_state（朝局头）与 metrics（余额真源）的建表归
    -- ming_sim/entities/reign_state（#1889 按职责拆出）
    -- ；本文件不再持第二份定义。

    CREATE TABLE IF NOT EXISTS offices (
        office_type TEXT PRIMARY KEY,
        power INTEGER NOT NULL,
        responsibility INTEGER NOT NULL,
        corruption_risk INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS characters (
        name TEXT PRIMARY KEY,
        office TEXT NOT NULL,
        office_type TEXT NOT NULL,
        faction TEXT NOT NULL,
        personal_skills TEXT NOT NULL,
        loyalty INTEGER NOT NULL,
        ability INTEGER NOT NULL,
        integrity INTEGER NOT NULL,
        courage INTEGER NOT NULL,
        style TEXT NOT NULL,
        birth_year INTEGER NOT NULL DEFAULT 0,
        historical_death_year INTEGER NOT NULL DEFAULT 0,
        historical_death_month INTEGER NOT NULL DEFAULT 0,
        debut_year INTEGER NOT NULL DEFAULT 0,
        debut_month INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        status_reason TEXT NOT NULL DEFAULT '',
        reason_code TEXT NOT NULL DEFAULT '',
        status_changed_turn INTEGER NOT NULL DEFAULT 0,
        power_id TEXT NOT NULL DEFAULT 'ming',
        location TEXT NOT NULL DEFAULT '',
        transit_to TEXT NOT NULL DEFAULT '',
        transit_distance_remaining REAL,
        transit_speed_factor REAL,
        transit_start_turn INTEGER NOT NULL DEFAULT 0,
        identity INTEGER NOT NULL DEFAULT 50,
        seed_guilt TEXT NOT NULL DEFAULT '',
        portrait_id TEXT NOT NULL DEFAULT '',
        court_role TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        aliases TEXT NOT NULL DEFAULT '[]',
        affair_id INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_characters_affair ON characters(affair_id);

    -- #1889：官职类别（office_type）的唯一真源 = characters.office_type。
    -- 原 character_offices.office_type 是同一事实的第二个可写表示（旧代码还得靠
    -- _ensure_office_type_parents 每次把它镜像回 characters 才能对账），已删。
    -- office_title 保留：罢免后 characters.office 置空，而备档留最近实职供起复
    -- 品级读取（office_rank._is_substantive_office）——那是**历史**，不是重复。
    CREATE TABLE IF NOT EXISTS character_offices (
        character_name TEXT PRIMARY KEY,
        office_title TEXT NOT NULL,
        source TEXT NOT NULL,
        dossier_id INTEGER,
        appointment_tenure TEXT NOT NULL DEFAULT '真除',
        region_id TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(character_name) REFERENCES characters(name)
    );

    CREATE TABLE IF NOT EXISTS office_change_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        office_title TEXT NOT NULL,
        office_type TEXT NOT NULL,
        source TEXT NOT NULL,
        dossier_id INTEGER,
        appointment_tenure TEXT NOT NULL DEFAULT '真除',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id)
    );
    CREATE INDEX IF NOT EXISTS idx_office_change_records_dossier
        ON office_change_records(dossier_id, id);

    CREATE TABLE IF NOT EXISTS office_slots (
        office_title TEXT PRIMARY KEY,
        office_type TEXT NOT NULL,
        region_id TEXT NOT NULL DEFAULT '',
        jurisdiction TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0
    );

    -- Local appointment jurisdiction lives only on character_offices.region_id
    -- (一次任职). No parallel seat catalog.

    CREATE VIEW IF NOT EXISTS office_vacancies AS
    SELECT
        s.office_title,
        s.office_type,
        s.region_id,
        s.jurisdiction,
        s.sort_order,
        c.name AS holder_name,
        c.office AS holder_office,
        c.status AS holder_status
    FROM office_slots AS s
    LEFT JOIN characters AS c
      ON c.status = 'active'
     AND (
         replace(replace(c.office, '（署理）', ''), '署理', '') = s.office_title
     );

    -- person_logs 的建表与索引归 ming_sim/entities/person_log
    -- （#1889 按职责拆出）；本文件不再持第二份定义。

    CREATE TABLE IF NOT EXISTS factions (
        name TEXT PRIMARY KEY,
        satisfaction INTEGER NOT NULL,
        leverage INTEGER NOT NULL,
        agenda TEXT NOT NULL,
        edict_overdraw INTEGER NOT NULL DEFAULT 0 CHECK (edict_overdraw >= 0),
        leverage_offset REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS powers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        leader TEXT NOT NULL,
        stance TEXT NOT NULL,
        leverage INTEGER NOT NULL,
        satisfaction INTEGER NOT NULL,
        military_strength INTEGER NOT NULL,
        cohesion INTEGER NOT NULL,
        supply INTEGER NOT NULL,
        agenda TEXT NOT NULL,
        status TEXT NOT NULL,
        last_action TEXT NOT NULL DEFAULT '',
        aliases TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS power_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        power_id TEXT NOT NULL,
        field TEXT NOT NULL,
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        delta INTEGER,
        reason TEXT NOT NULL,
        origin_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(power_id) REFERENCES powers(id)
    );

    CREATE TABLE IF NOT EXISTS power_name_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        power_id TEXT NOT NULL,
        old_name TEXT NOT NULL,
        new_name TEXT NOT NULL,
        old_aliases TEXT NOT NULL DEFAULT '',
        new_aliases TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(power_id) REFERENCES powers(id)
    );

    CREATE TABLE IF NOT EXISTS regions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        population INTEGER NOT NULL,
        public_support INTEGER NOT NULL,
        unrest INTEGER NOT NULL,
        natural_disaster TEXT NOT NULL,
        human_disaster TEXT NOT NULL,
        registered_land INTEGER NOT NULL,
        hidden_land INTEGER NOT NULL,
        tax_per_turn INTEGER NOT NULL,
        grain_security INTEGER NOT NULL,
        gentry_resistance INTEGER NOT NULL,
        military_pressure INTEGER NOT NULL,
        status TEXT NOT NULL,
        controlled_by TEXT NOT NULL DEFAULT 'ming',
        city_level INTEGER NOT NULL DEFAULT 0,
        cannon INTEGER NOT NULL DEFAULT 0,
        fiscal TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(controlled_by) REFERENCES powers(id)
    );

    CREATE TABLE IF NOT EXISTS region_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        region_id TEXT NOT NULL,
        field TEXT NOT NULL,
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        delta INTEGER,
        reason TEXT NOT NULL,
        event_id TEXT,
        edict_id INTEGER,
        actor TEXT,
        origin_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(region_id) REFERENCES regions(id)
    );

    CREATE TABLE IF NOT EXISTS armies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        station TEXT NOT NULL,
        station_region TEXT NOT NULL DEFAULT '',
        theater TEXT NOT NULL,
        commander TEXT NOT NULL,
        controller TEXT NOT NULL,
        troop_type TEXT NOT NULL,
        manpower INTEGER NOT NULL,
        supply INTEGER NOT NULL,
        morale INTEGER NOT NULL,
        training INTEGER NOT NULL,
        equipment INTEGER NOT NULL,
        arrears REAL GENERATED ALWAYS AS (province_pay_arrears + central_pay_arrears) VIRTUAL,
        province_pay_arrears REAL NOT NULL DEFAULT 0,
        central_pay_arrears REAL NOT NULL DEFAULT 0,
        consecutive_pay_shortfall_months INTEGER NOT NULL DEFAULT 0,
        pay_source_region TEXT NOT NULL DEFAULT '',
        province_pay_share REAL NOT NULL DEFAULT 0,
        central_pay_share REAL NOT NULL DEFAULT 0,
        is_tusi INTEGER NOT NULL DEFAULT 0,
        self_funded_pay INTEGER NOT NULL DEFAULT 0,
        mutiny_status TEXT NOT NULL DEFAULT '',
        is_mutinied INTEGER NOT NULL DEFAULT 0 CHECK(is_mutinied IN (0, 1)),
        mutiny_count INTEGER NOT NULL DEFAULT 0,
        mutiny_probation INTEGER NOT NULL DEFAULT 0,
        full_pay_streak INTEGER NOT NULL DEFAULT 0,
        redemption_count INTEGER NOT NULL DEFAULT 0,
        mobility INTEGER NOT NULL,
        loyalty INTEGER NOT NULL,
        firearm_equipment INTEGER NOT NULL DEFAULT 0,
        cannon_equipment INTEGER NOT NULL DEFAULT 0,
        salary_rate REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        owner_power TEXT NOT NULL DEFAULT 'ming',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(owner_power) REFERENCES powers(id)
    );

    CREATE TABLE IF NOT EXISTS army_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        army_id TEXT NOT NULL,
        field TEXT NOT NULL,
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        delta INTEGER,
        reason TEXT NOT NULL,
        event_id TEXT,
        edict_id INTEGER,
        actor TEXT,
        origin_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(army_id) REFERENCES armies(id)
    );

    CREATE TABLE IF NOT EXISTS buildings (
        id TEXT PRIMARY KEY,
        region_id TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        level INTEGER NOT NULL,
        condition INTEGER NOT NULL,
        maintenance INTEGER NOT NULL,
        risk INTEGER NOT NULL,
        output_metric TEXT NOT NULL DEFAULT '',
        output_amount INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        origin TEXT NOT NULL DEFAULT 'preset',
        created_turn INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(region_id) REFERENCES regions(id)
    );

    CREATE TABLE IF NOT EXISTS building_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        building_id TEXT NOT NULL,
        field TEXT NOT NULL,
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        delta INTEGER,
        reason TEXT NOT NULL,
        event_id TEXT,
        edict_id INTEGER,
        actor TEXT,
        origin_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- #1889：国库活余额的事实真源 = metrics（key/value，见 save_state）。
    -- economy_accounts 降级为**派生视图**（读时算），不再是可独立漂移的第二本账：
    -- 旧实现是实体表 + sync_economy_accounts 双向同步，load_state 还用它盖回
    -- metrics —— 实测把 metrics.国库 改成 999 会被静默改回 320，且删掉 metrics
    -- 行后余额会从这张表「复活」。视图化后单一写口 = metrics，无同步代码。
    -- 列契约（account/metric_key/balance/note）保持不变，读侧零改动。
    CREATE VIEW IF NOT EXISTS economy_accounts AS
    SELECT
        m.key AS account,
        m.key AS metric_key,
        m.value AS balance,
        CASE m.key
            WHEN '国库' THEN '朝廷公开财政，用于军饷、赈济、官俸和工程。'
            WHEN '内库' THEN '皇帝可直接调度的钱物，用于救急、密支和政治缓冲。'
            ELSE ''
        END AS note
    FROM metrics m
    WHERE m.key IN ('国库', '内库');

    -- #1889：account ∈ ECONOMY_ACCOUNTS 的原 FK(account)→economy_accounts 已随
    -- 该表降级为 metrics 的派生视图移除（SQLite 不支持外键指向视图）；同一约束
    -- 改在真实写口 record_issue_economy_move 显式 fail-loud 校验，覆盖面不减。
    CREATE TABLE IF NOT EXISTS economy_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        account TEXT NOT NULL,
        delta INTEGER NOT NULL,
        balance_after INTEGER NOT NULL,
        category TEXT NOT NULL,
        reason TEXT NOT NULL,
        event_id TEXT,
        edict_id INTEGER,
        actor TEXT,
        purpose TEXT,
        target_kind TEXT,
        target_id TEXT,
        dossier_id INTEGER,
        origin_ref TEXT NOT NULL DEFAULT '',
        beyond_intent INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        urgency INTEGER NOT NULL,
        severity INTEGER NOT NULL,
        credibility INTEGER NOT NULL,
        interests TEXT NOT NULL,
        audiences TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS event_triggers (
        event_id TEXT PRIMARY KEY,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'simulation',
        terminal_state TEXT NOT NULL DEFAULT 'triggered',
        terminal_reason TEXT NOT NULL DEFAULT '',
        choice_json TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(event_id) REFERENCES events(id)
    );

    CREATE TABLE IF NOT EXISTS turn_reports (
        turn INTEGER PRIMARY KEY,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        report TEXT NOT NULL,
        attendant_message TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- HITL 重大决策点：世界段请旨机标产出的待皇帝亲裁抉择。每回合 ≤5 条。
    CREATE TABLE IF NOT EXISTS pending_decisions (
        turn INTEGER NOT NULL,
        idx INTEGER NOT NULL,
        event_id TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        context TEXT NOT NULL DEFAULT '',
        options_json TEXT NOT NULL DEFAULT '[]',
        choice_json TEXT NOT NULL DEFAULT '',
        rejection_reason TEXT NOT NULL DEFAULT '',
        opposition TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'decision',
        actor_name TEXT NOT NULL DEFAULT '',
        actor_office TEXT NOT NULL DEFAULT '',
        actor_faction TEXT NOT NULL DEFAULT '',
        revision_round INTEGER NOT NULL DEFAULT 0,
        prior_options_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (turn, idx)
    );

    -- 过月上下文：存阶段进度与原诏，供暂停后续跑。
    -- 每回合至多一行（turn 主键），phase2 跑完即删。
    CREATE TABLE IF NOT EXISTS pending_resolve_context (
        turn INTEGER PRIMARY KEY,
        decree_text TEXT NOT NULL DEFAULT '',
        simulator_payload_json TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT 'system_simulation',
        attendant_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- 动作闸门(ADR 0006)：结构化聊天交办(密令/任命/拟旨)召对期进此暂存表，
    -- 不动真实表；颁诏时 commit_pending_actions 在结算最前批量落库(不拒绝即允许)。
    -- 撤回 = 删本表对应行(任意一条、免快照)。restore 仍可无损接续(P1)。
    CREATE TABLE IF NOT EXISTS pending_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        kind TEXT NOT NULL,                       -- secret_order | office | directive
        action TEXT NOT NULL,                     -- 更新 | 催办 | 提交核议 | 记进展 | 创建 …
        target_id INTEGER,                        -- 操作既有实体时其 id；新建为 NULL
        minister_name TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',    -- pending | committed | failed | held_over
        committed_directive_id INTEGER NOT NULL DEFAULT 0,
        night_id INTEGER NOT NULL DEFAULT 0,
        night_approved INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS recommendation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        recommender TEXT NOT NULL,
        candidate TEXT NOT NULL,
        candidate_kind TEXT NOT NULL,
        target_office TEXT NOT NULL DEFAULT '',
        basis TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'adopted',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_recommendation_events_recommender
        ON recommendation_events(recommender, turn, id);

    -- 召对聊天记录持久化，每条消息一行，进程重启不丢。
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        minister_name TEXT NOT NULL,
        turn INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        -- #976: held|released|withheld|private (audience knowledge dual-track)
        knowledge_status TEXT NOT NULL DEFAULT 'held',
        -- #544 / ADR 0045：高亮判官短语清单（JSON 数组）；空=无高亮/降级
        highlights_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_minister
        ON chat_messages(minister_name, id);
    CREATE INDEX IF NOT EXISTS idx_chat_messages_turn
        ON chat_messages(turn);

    CREATE TABLE IF NOT EXISTS chat_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        minister_name TEXT NOT NULL,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        user_message_id INTEGER,
        minister_message_id INTEGER,
        agno_session_id TEXT NOT NULL DEFAULT '',
        agno_runs_before INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        -- #498：对话轮锚定夜容器；0=未挂夜
        night_id INTEGER NOT NULL DEFAULT 0,
        -- 与 story_ledger_entries.seq 共用夜内单调序（allocate_night_seq）
        night_seq INTEGER NOT NULL DEFAULT 0,
        -- #501 叙事抽取水位（确定性可判、补跑不重复/不漏）：
        --   ''=未抽 / 'done'=已抽落账 / 'pending'=待补（抽取失败，给玩家原地重试）
        extract_status TEXT NOT NULL DEFAULT '',
        error_pack_path TEXT NOT NULL DEFAULT '',
        post_reply_recovery TEXT NOT NULL DEFAULT '',
        post_reply_error_pack_path TEXT NOT NULL DEFAULT '',
        -- #1838：本轮转译声明的御前主角（按源轮；空=本轮未声明）
        protagonist_name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        undone_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_chat_turns_minister_turn
        ON chat_turns(minister_name, turn, status, id);
    CREATE INDEX IF NOT EXISTS idx_chat_turns_status_id
        ON chat_turns(status, id);
    CREATE INDEX IF NOT EXISTS idx_chat_turns_night
        ON chat_turns(night_id, id);

    -- #498 召对夜一等容器 + 故事账本（ADR 0035）
    CREATE TABLE IF NOT EXISTS audience_nights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        time_of_day TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        -- 收夜提交幂等游标：0=未开始；已完成步序号；见 audience_night.CLOSE_STEPS
        -- endorsement-bound 是 CLOSE_STEPS 中的一步，不另设平行列
        close_commit_cursor INTEGER NOT NULL DEFAULT 0,
        -- 夜内事件单调序源：账本 seq 与 chat night_seq 同桶递增
        next_event_seq INTEGER NOT NULL DEFAULT 0,
        -- #1838：本夜当前御前主角（转译判；宣 X 当场先切）
        protagonist_name TEXT NOT NULL DEFAULT '',
        opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_audience_nights_turn_status
        ON audience_nights(turn, status, id);

    CREATE TABLE IF NOT EXISTS story_ledger_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        night_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        person_names TEXT NOT NULL DEFAULT '[]',
        audibility TEXT NOT NULL DEFAULT '殿上公开',
        body TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        -- #501 抽取账溯源：0=口令/框架账；>0=由该对话轮叙事抽取而来
        source_chat_turn_id INTEGER NOT NULL DEFAULT 0,
        -- #506 轮级撤销绑定：口令账由某轮 attach 创建时绑该轮；0=框架账不随轮撤
        origin_chat_turn_id INTEGER NOT NULL DEFAULT 0,
        -- #501 机器可读在场效果（ADR 0035 线上 R2）：''=无 / 'enter'=进 / 'exit'=出
        presence_effect TEXT NOT NULL DEFAULT '',
        -- #501 时序键（ADR 0036 cmr R7）：口令账=自身 seq；抽取账=源对话轮原始时序，
        -- 使补跑落回原时间位、不因补跑时刻错位。NULL 时读取端 COALESCE 回退 seq。
        order_key REAL,
        origin_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(night_id, seq),
        FOREIGN KEY(night_id) REFERENCES audience_nights(id)
    );
    CREATE INDEX IF NOT EXISTS idx_story_ledger_night_seq
        ON story_ledger_entries(night_id, seq);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_origin_ref
        ON story_ledger_entries(origin_ref) WHERE origin_ref != '';

    CREATE TABLE IF NOT EXISTS chat_turn_rollback_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_turn_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        target_table TEXT NOT NULL,
        target_id TEXT NOT NULL,
        before_json TEXT NOT NULL DEFAULT '',
        after_json TEXT NOT NULL DEFAULT '',
        rollback_strategy TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(chat_turn_id) REFERENCES chat_turns(id)
    );
    CREATE INDEX IF NOT EXISTS idx_chat_turn_rollback_items_turn
        ON chat_turn_rollback_items(chat_turn_id, id);

    CREATE TABLE IF NOT EXISTS secret_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn_issued INTEGER NOT NULL,
        due_turn INTEGER NOT NULL DEFAULT 0,
        deadline_span INTEGER NOT NULL DEFAULT 0,
        year_issued INTEGER NOT NULL,
        period_issued INTEGER NOT NULL,
        minister_name TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        importance INTEGER NOT NULL DEFAULT 4,
        status TEXT NOT NULL DEFAULT 'active',
        result TEXT NOT NULL DEFAULT '',
        sim_note TEXT NOT NULL DEFAULT '',
        excluded_names TEXT NOT NULL DEFAULT '[]',
        dossier_progress_json TEXT NOT NULL DEFAULT '[]',
        excluded_targets TEXT NOT NULL DEFAULT '{}',
        turn_closed INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_secret_orders_minister
        ON secret_orders(minister_name, status);
    CREATE INDEX IF NOT EXISTS idx_secret_orders_turn
        ON secret_orders(turn_issued, status);
    CREATE INDEX IF NOT EXISTS idx_secret_orders_status
        ON secret_orders(status);

    __DOSSIER_SCHEMA__;

    -- ADR 0071：持有型/持续型特权的 durable 授权档。
    CREATE TABLE IF NOT EXISTS authority_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        holder_id TEXT NOT NULL,
        privilege TEXT NOT NULL CHECK(privilege IN (
            __AUTHORITY_PRIVILEGES__
        )),
        scope TEXT NOT NULL,
        effective_turn INTEGER NOT NULL,
        expires_turn INTEGER,
        revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
        revoked_turn INTEGER,
        dossier_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(holder_id) REFERENCES characters(name),
        FOREIGN KEY(dossier_id) REFERENCES decree_dossiers(id)
    );
    CREATE INDEX IF NOT EXISTS idx_authority_records_holder
        ON authority_records(holder_id, revoked, effective_turn);

    CREATE TABLE IF NOT EXISTS turn_directives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        event_id TEXT,
        actor TEXT,
        text TEXT NOT NULL,
        source TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        notes TEXT NOT NULL DEFAULT '',
        dossier_payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(event_id) REFERENCES events(id),
        FOREIGN KEY(actor) REFERENCES characters(name)
    );

    CREATE INDEX IF NOT EXISTS idx_economy_ledger_turn
    ON economy_ledger(turn, account);

    CREATE TABLE IF NOT EXISTS fiscal_config_tombstones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        removed_turn INTEGER NOT NULL DEFAULT 0,
        key TEXT NOT NULL,
        value INTEGER NOT NULL,
        kind TEXT NOT NULL,
        origin_ref TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        beyond_intent INTEGER NOT NULL DEFAULT 0,
        removed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_fiscal_config_tombstones_origin
    ON fiscal_config_tombstones(origin_ref, removed_turn);

    CREATE TABLE IF NOT EXISTS fiscal_config_creations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL DEFAULT 0,
        key TEXT NOT NULL,
        value INTEGER NOT NULL,
        kind TEXT NOT NULL,
        origin_ref TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        beyond_intent INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_fiscal_config_creations_origin
    ON fiscal_config_creations(origin_ref, turn, id);

    CREATE TABLE IF NOT EXISTS fiscal_config_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL DEFAULT 0,
        key TEXT NOT NULL,
        old_value INTEGER NOT NULL,
        new_value INTEGER NOT NULL,
        delta INTEGER NOT NULL,
        origin_ref TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        beyond_intent INTEGER NOT NULL DEFAULT 0,
        changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_fiscal_config_changes_origin
    ON fiscal_config_changes(origin_ref, turn, id);

    CREATE TABLE IF NOT EXISTS fiscal_config (
        key   TEXT PRIMARY KEY,
        value INTEGER NOT NULL,
        kind  TEXT NOT NULL,
        note  TEXT NOT NULL DEFAULT '',
        budget_role TEXT NOT NULL DEFAULT 'fixed',
        account TEXT NOT NULL DEFAULT '',
        direction TEXT NOT NULL DEFAULT '',
        display TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 9999,
        origin_ref TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS fiscal_containers (
        key   TEXT PRIMARY KEY,
        value REAL NOT NULL,
        note  TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_turn_directives_turn
    ON turn_directives(turn, status);

    CREATE INDEX IF NOT EXISTS idx_region_logs_turn
    ON region_logs(turn, region_id);

    CREATE INDEX IF NOT EXISTS idx_army_logs_turn
    ON army_logs(turn, army_id);

    CREATE INDEX IF NOT EXISTS idx_building_logs_turn
    ON building_logs(turn, building_id);

    CREATE INDEX IF NOT EXISTS idx_power_logs_turn
    ON power_logs(turn, power_id);

    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        origin_kind TEXT NOT NULL DEFAULT '',
        origin_ref TEXT NOT NULL DEFAULT '',
        origin_turn INTEGER NOT NULL,
        bar_value INTEGER NOT NULL DEFAULT 40,
        bar_good_meaning TEXT NOT NULL DEFAULT '已平',
        bar_bad_meaning TEXT NOT NULL DEFAULT '失控',
        inertia INTEGER NOT NULL DEFAULT 0,
        phase TEXT NOT NULL DEFAULT '起',
        stage_text TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        severity INTEGER NOT NULL DEFAULT 50,
        region_hint TEXT NOT NULL DEFAULT '',
        faction_hint TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        participants TEXT NOT NULL DEFAULT '[]',
        participant_roster TEXT NOT NULL DEFAULT '[]',
        target_roster TEXT NOT NULL DEFAULT '[]',
        ongoing_effects TEXT NOT NULL DEFAULT '{}',
        cancellable TEXT NOT NULL DEFAULT 'never',
        cancel_cost TEXT NOT NULL DEFAULT '{}',
        effect_on_resolve TEXT NOT NULL DEFAULT '{}',
        effect_on_fail TEXT NOT NULL DEFAULT '{}',
        resolve_condition TEXT NOT NULL DEFAULT '',
        fail_condition TEXT NOT NULL DEFAULT '',
        end_turn INTEGER NOT NULL DEFAULT 0,
        stop_condition TEXT NOT NULL DEFAULT '',
        commitment_kind TEXT NOT NULL DEFAULT '',
        stages_json TEXT NOT NULL DEFAULT '[]',
        resolution_summary TEXT NOT NULL DEFAULT '',
        last_advance_turn INTEGER NOT NULL DEFAULT 0,
        closed_turn INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        affair_id INTEGER NOT NULL DEFAULT 0
    );

    -- #620 / ADR 0074：次回合召对待办（分段到期等）；结算内确定性写入、不停轮。
    -- #624 / ADR 0078：payload_json 引擎侧列（真伪底）；玩家投影路径不读。
    -- #1783：commitment_ref 可为 0（案卷 due 直挂 todo，不另立 issue）；
    -- 有承诺时仍写 issues.id。禁 FK 以免 0 被拒。
    CREATE TABLE IF NOT EXISTS next_audience_todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commitment_ref INTEGER NOT NULL,
        stage_idx INTEGER NOT NULL,
        due_turn INTEGER NOT NULL,
        criterion_text TEXT NOT NULL DEFAULT '',
        origin_context TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        entry_kind TEXT NOT NULL DEFAULT 'staged_commitment',
        created_turn INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(commitment_ref, stage_idx, entry_kind)
    );
    CREATE INDEX IF NOT EXISTS idx_next_audience_todos_status
        ON next_audience_todos(status, due_turn);

    CREATE TABLE IF NOT EXISTS issue_advances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id INTEGER NOT NULL,
        turn INTEGER NOT NULL,
        trigger_kind TEXT NOT NULL,
        trigger_ref TEXT NOT NULL DEFAULT '',
        delta_bar INTEGER NOT NULL DEFAULT 0,
        from_value INTEGER NOT NULL DEFAULT 0,
        to_value INTEGER NOT NULL DEFAULT 0,
        from_stage_text TEXT NOT NULL DEFAULT '',
        to_stage_text TEXT NOT NULL DEFAULT '',
        narrative TEXT NOT NULL DEFAULT '',
        metric_delta TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(issue_id) REFERENCES issues(id)
    );

    CREATE TABLE IF NOT EXISTS legacies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        source_issue_id INTEGER,                    -- 产生它的 issue（可空）
        modifiers TEXT NOT NULL DEFAULT '{}',  -- 各维度带符号百分比修正符 {"国库":10,"regions":{...},"armies":{...}}
        narrative_hint TEXT NOT NULL DEFAULT '',    -- 一句话说明（仅展示用，不喂 simulator）
        start_month INTEGER NOT NULL,               -- 绝对月 = year*12+period
        duration_months INTEGER NOT NULL DEFAULT 24,-- 时长；-1=永久
        status TEXT NOT NULL DEFAULT 'active',      -- active / expired / cleared
        clear_gate TEXT NOT NULL DEFAULT '{}',      -- 机器消除条件（同 _gate_passed 语法）；非空=靠程序判定消除而非时长
        legacy_key TEXT NOT NULL DEFAULT '',        -- 开局负面修正对应 opening_legacies.key，去重用
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_legacies_active
    ON legacies(status);

    CREATE INDEX IF NOT EXISTS idx_issues_active
    ON issues(kind, status, severity DESC);

    CREATE INDEX IF NOT EXISTS idx_issue_advances_issue
    ON issue_advances(issue_id, turn);

    CREATE TABLE IF NOT EXISTS classes (
        name TEXT NOT NULL,
        region_id TEXT NOT NULL DEFAULT '',
        population INTEGER NOT NULL,
        satisfaction INTEGER NOT NULL,
        leverage INTEGER NOT NULL,
        agenda TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (name, region_id)
    );

    CREATE INDEX IF NOT EXISTS idx_classes_region
    ON classes(region_id, name);

    CREATE TABLE IF NOT EXISTS population_transfer_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        amount INTEGER NOT NULL,
        reason TEXT NOT NULL,
        origin_ref TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_population_transfer_turn
    ON population_transfer_ledger(turn);

    -- character_knowledge_events / character_knowledge_sources 的建表与
    -- 索引归 ming_sim/entities/character_knowledge（#1889 按职责拆出）。

    -- #1829 公开说法：独立记录，投影进公开层；不改人物实况。
    -- 排除名单与正文同表（#1829 reopen），不另抄见闻来源。
    CREATE TABLE IF NOT EXISTS public_sayings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        body TEXT NOT NULL,
        involved_characters TEXT NOT NULL DEFAULT '[]',
        affair_ref TEXT NOT NULL DEFAULT '',
        source_id TEXT NOT NULL UNIQUE,
        excluded_names TEXT NOT NULL DEFAULT '[]',
        excluded_targets TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_public_sayings_affair
        ON public_sayings(affair_ref, id);

    -- #883: secret orders never enter the shared knowledge ledger.
    -- origin_chat_message_ids: message-level oral-decree provenance (#976).
    CREATE TABLE IF NOT EXISTS secret_order_briefs (
        order_id INTEGER PRIMARY KEY,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        minister_name TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        origin_chat_message_ids TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(order_id) REFERENCES secret_orders(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS kv_store (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- #1234 / ADR 0148 路③：月初快照呈现投影（点击前四键 + 所属回合）。
    -- 当前回合未过期行存在 ⇔ 核账展示态；非结算/恢复权威，引擎控制流不读。
    CREATE TABLE IF NOT EXISTS month_open_snapshot (
        turn INTEGER PRIMARY KEY,
        treasury INTEGER NOT NULL,
        inner_treasury INTEGER NOT NULL,
        public_support INTEGER NOT NULL,
        imperial_prestige INTEGER NOT NULL
    );

    -- #632 关系账 S1：append-only 有向边事件流水。0079 信用事件只在读侧适配，
    -- 不迁移、不双写；evidence 仅允许结构化产出方置真。
    CREATE TABLE IF NOT EXISTS relation_edge_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        event_kind TEXT NOT NULL,
        context TEXT NOT NULL,
        origin TEXT NOT NULL,
        origin_round INTEGER NOT NULL,
        turn INTEGER NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        evidence INTEGER NOT NULL DEFAULT 0 CHECK (evidence IN (0, 1)),
        affair_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source, target, event_kind, context, origin)
    );

    CREATE INDEX IF NOT EXISTS idx_relation_edges_pair
    ON relation_edge_events(source, target, turn, id);

    CREATE INDEX IF NOT EXISTS idx_relation_edges_person
    ON relation_edge_events(source, target, event_kind, id);

    CREATE INDEX IF NOT EXISTS idx_relation_edge_events_affair
    ON relation_edge_events(affair_id, id);

    -- #636 关系摘要层 S5：两段式摘要（奠基段机械只增不改＋近况段整段重酿，ID-9）。
    -- 零数值强度字段（P4/ADR 0083）；结构字段首发集＝有向关系对、维度标记、
    -- 奠基段、近况段、最近事件回指（last_event_id 水位）、最后重酿回合。
    CREATE TABLE IF NOT EXISTS relation_summaries (
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        dimension TEXT NOT NULL CHECK (dimension IN ('君臣', '大臣')),
        founding_segment TEXT NOT NULL DEFAULT '',
        recent_segment TEXT NOT NULL DEFAULT '',
        last_event_id INTEGER NOT NULL DEFAULT 0,
        last_brewed_turn INTEGER NOT NULL DEFAULT 0,
        last_brewed_year INTEGER NOT NULL DEFAULT 0,
        last_brewed_period INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (source, target)
    );

    -- #636 S5（庭裁 r1 F1＋r2/r3 F1）：relation_brew_pending 双角色——
    -- ① settled 年月入选关系的 durable claim（认领先行，酿造前落盘提交，
    -- 与本月边事件同结算事务生死）；② 酿制失败月的持久 pending-backlog。
    -- 成功路径＝摘要写入与 pending 清除同一 DB 事务原子落定（庭裁 r2 F1，ADR 0008 一脉）。
    -- #637 S6（庭裁 r1 F2）：最小泛化既有 durable brew-claim 身份——item_kind
    -- 区分关系对与派系工作项，使两者共用同一 claim/watermark/apply+clear 所有者；
    -- 不旁建第二套 faction_pending 表。派系行＝item_kind='派系'、source=''、
    -- target=派系名（不把派系名伪装成关系对——身份由 item_kind 显式钉死）。
    CREATE TABLE IF NOT EXISTS relation_brew_pending (
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        item_kind TEXT NOT NULL DEFAULT '关系',
        PRIMARY KEY (source, target)
    );

    -- #637 S6（ADR 0084）：派系态势摘要——边流之上的派系级定性聚合视图。
    -- 三不碰：不写 factions 真源数值、不动满意度/影响力、不建认同度；
    -- 零数值强度字段（P4/ADR 0083 一脉）。粒度＝per-派系一份（内含对他派
    -- 与对帝的态势描述），派系对级细分不首发（ID-10）。水位语义与
    -- relation_summaries.last_event_id 同构（F2 稳定性判据共用接缝）。
    CREATE TABLE IF NOT EXISTS faction_stance_summaries (
        faction TEXT PRIMARY KEY,
        stance_segment TEXT NOT NULL DEFAULT '',
        last_event_id INTEGER NOT NULL DEFAULT 0,
        last_brewed_turn INTEGER NOT NULL DEFAULT 0,
        last_brewed_year INTEGER NOT NULL DEFAULT 0,
        last_brewed_period INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- #690 / ADR 0011-2：血债棘轮 substrate（log 真源 + sparse 缓存）
    CREATE TABLE IF NOT EXISTS faction_axis_debt (
        faction TEXT NOT NULL REFERENCES factions(name),
        axis TEXT NOT NULL CHECK (axis IN (
            '礼法名节','既得利益','实务事功','皇权依附','华夷战和','民本恤民'
        )),
        blood_debt INTEGER NOT NULL DEFAULT 0 CHECK (blood_debt >= 0),
        wariness INTEGER NOT NULL DEFAULT 0 CHECK (wariness >= 0),
        PRIMARY KEY (faction, axis)
    );

    CREATE TABLE IF NOT EXISTS centrifuge_log (
        id INTEGER PRIMARY KEY,
        turn INTEGER NOT NULL,
        faction TEXT NOT NULL REFERENCES factions(name),
        axis TEXT CHECK (
            axis IS NULL OR axis IN (
                '礼法名节','既得利益','实务事功','皇权依附','华夷战和','民本恤民'
            )
        ),
        kind TEXT NOT NULL CHECK (kind IN ('direct','kinship','overdraw')),
        base INTEGER,
        legitimacy_pct INTEGER,
        amount INTEGER NOT NULL CHECK (amount > 0),
        source_name TEXT,
        reason_code TEXT,
        source TEXT,
        idem_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (
            (kind = 'overdraw' AND axis IS NULL AND base IS NULL
             AND legitimacy_pct IS NULL)
            OR (kind IN ('direct','kinship') AND axis IS NOT NULL
                AND base IS NOT NULL AND legitimacy_pct IS NOT NULL)
        )
    );

    CREATE TABLE IF NOT EXISTS ending_summary (
        turn INTEGER PRIMARY KEY,
        year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        ending_status TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        timeline TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS save_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );"""


def ensure_core_schema(conn) -> None:
    """Create every engine-owned table, view and index (idempotent)."""
    conn.executescript(
        CORE_SCHEMA_SQL
        .replace("__AUTHORITY_PRIVILEGES__", AUTHORITY_PRIVILEGE_SQL_IN)
        .replace("__DOSSIER_SCHEMA__", DOSSIER_SCHEMA_SQL)
    )
