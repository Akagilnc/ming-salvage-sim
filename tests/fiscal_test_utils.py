def zero_non_meta_fiscal_config(db):
    db.conn.execute(
        """
        UPDATE fiscal_config
        SET value = CASE
            WHEN key IN (
                'central_taicang_sink_loss_rate',
                'central_jingyun_sink_loss_rate'
            ) THEN 1
            ELSE 0
        END
        WHERE kind != 'meta'
        """
    )


def class_population(db, name: str, region_id: str) -> int:
    """某阶层在某地区的人口读数（classes 表），无行则 0。"""
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0

