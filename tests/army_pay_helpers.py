"""Shared army-pay test helpers (#1503)."""
from __future__ import annotations


def _set_guanning_arrears(db, arrears: float, *, central: float | None = None,
                          province: float | None = None) -> None:
    if central is None and province is None:
        central = float(arrears)
        province = 0.0
    elif central is None:
        central = max(0.0, float(arrears) - float(province or 0))
    elif province is None:
        province = max(0.0, float(arrears) - float(central or 0))
    db.conn.execute(
        "\n        UPDATE armies\n        SET  province_pay_arrears=?, central_pay_arrears=?\n        WHERE id='guanning'\n        ",
        (float(province), float(central),),
    )
    db.conn.commit()
