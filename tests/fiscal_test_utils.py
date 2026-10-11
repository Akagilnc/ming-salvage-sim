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


def settle_province_via_batch(db, region_id, actions=None):
    """经现役批量桥推进（一次推进全部明控 settle 省）并取该省结果；outcome.error 原样上抛。"""
    outcomes = db.settle_ming_province_substrate_ticks({region_id: list(actions or [])})
    mine = [o for o in outcomes if o.region_id == region_id]
    if not mine:
        raise ValueError(f"region {region_id!r} 非明控 settle 省，批量桥不出列")
    outcome = mine[0]
    if outcome.error is not None:
        raise outcome.error
    return outcome.result
