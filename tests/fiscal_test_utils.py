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
