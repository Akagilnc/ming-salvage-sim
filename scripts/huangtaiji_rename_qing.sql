-- 皇太极称帝改国号大清：只改显示名/别名，不改稳定 power id。
-- 注意：此 SQL 给旧存档手动补一次；若库里已经有 powers.aliases 列再跑会报 duplicate column。
-- 正常程序启动会通过 GameDB.ensure_schema 幂等补列，不需要反复执行本脚本。
-- 用法：
--   sqlite3 data/your_save.db < scripts/huangtaiji_rename_qing.sql

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

ALTER TABLE powers ADD COLUMN aliases TEXT NOT NULL DEFAULT '';

INSERT INTO power_name_logs
(turn, year, period, power_id, old_name, new_name, old_aliases, new_aliases, reason)
SELECT
    COALESCE((SELECT turn FROM game_state LIMIT 1), 0),
    COALESCE((SELECT year FROM game_state LIMIT 1), 1636),
    COALESCE((SELECT quarter FROM game_state LIMIT 1), 4),
    id,
    name,
    '大清',
    aliases,
    '后金，清，大清',
    '皇太极称帝，改国号大清'
FROM powers
WHERE id='houjin'
  AND name <> '大清';

UPDATE powers
SET name='大清',
    aliases='后金，清，大清',
    status='皇太极称帝改国号大清，建元崇德，整合满蒙汉诸部南向争明',
    last_action='皇太极称帝改国号大清',
    updated_at=CURRENT_TIMESTAMP
WHERE id='houjin';
