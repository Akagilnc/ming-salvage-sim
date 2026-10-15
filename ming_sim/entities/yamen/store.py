"""Yamen (新设衙门) ledger entity: identity, chief, monthly fee (#1915).

Monthly progress lives on textual_facts with subject_kind='yamen' (ADR 0156).
Monthly fee is a fiscal_config fixed expense keyed from this row.

No lifecycle status: presence on the ledger is the only existence signal.
Withdraw removes the row (undo); this ticket has no suspend/dissolve protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ming_sim.applier import connection_owns_transaction
from ming_sim.constants import ECONOMY_ACCOUNTS
from ming_sim.entities.column_write import RowStore
from ming_sim.exceptions import DeclarationDataError, DeclarationReferenceError


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS yamens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    chief_name TEXT NOT NULL DEFAULT '',
    monthly_fee INTEGER NOT NULL DEFAULT 0,
    fee_account TEXT NOT NULL DEFAULT '国库',
    fiscal_key TEXT NOT NULL DEFAULT '',
    origin_ref TEXT NOT NULL DEFAULT '',
    created_turn INTEGER NOT NULL,
    created_year INTEGER NOT NULL,
    created_period INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_yamens_chief ON yamens(chief_name, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_yamens_name ON yamens(name);
"""


@dataclass(frozen=True)
class Yamen:
    """One emperor-founded office on the world ledger."""

    id: int
    name: str
    chief_name: str
    monthly_fee: int
    fee_account: str
    fiscal_key: str
    origin_ref: str
    created_turn: int
    created_year: int
    created_period: int


_YAMEN_COLS = (
    "id, name, chief_name, monthly_fee, fee_account, fiscal_key, "
    "origin_ref, created_turn, created_year, created_period"
)


class YamenStore(RowStore):
    """World-record home for yamens. Live writes go through create/set_fiscal_key."""

    TABLE = "yamens"
    PK = "id"
    TABLES = {"yamens": "id"}

    @staticmethod
    def ensure_schema(conn: Any) -> None:
        conn.executescript(_SCHEMA_SQL)

    def get(self, yamen_id: int) -> Optional[Yamen]:
        row = self._conn.execute(
            f"SELECT {_YAMEN_COLS} FROM yamens WHERE id=?",
            (int(yamen_id),),
        ).fetchone()
        return _row_to_yamen(row) if row is not None else None

    def list_active(self) -> tuple[Yamen, ...]:
        """All on-ledger yamens (existence = active; no status column)."""
        rows = self._conn.execute(
            f"SELECT {_YAMEN_COLS} FROM yamens ORDER BY id ASC",
        ).fetchall()
        return tuple(_row_to_yamen(row) for row in rows)

    def list_for_chief(self, chief_name: str) -> tuple[Yamen, ...]:
        name = str(chief_name or "").strip()
        if not name:
            return ()
        rows = self._conn.execute(
            f"SELECT {_YAMEN_COLS} FROM yamens WHERE chief_name=? ORDER BY id ASC",
            (name,),
        ).fetchall()
        return tuple(_row_to_yamen(row) for row in rows)

    def create(
        self,
        *,
        name: str,
        chief_name: str,
        monthly_fee: int,
        fee_account: str,
        year: int,
        period: int,
        turn: int,
        origin_ref: str = "",
    ) -> Yamen:
        yamen_name = str(name or "").strip()
        if not yamen_name:
            raise DeclarationDataError("衙门名称不能为空")
        chief = str(chief_name or "").strip()
        if not chief:
            raise DeclarationDataError("衙门主官不能为空")
        account = str(fee_account or "").strip()
        if not account:
            raise DeclarationDataError("衙门月费账户不能为空")
        if account not in ECONOMY_ACCOUNTS:
            raise DeclarationDataError(f"衙门月费账户非法：{account!r}")
        from ming_sim.strict_types import SQLITE_INT_MAX, SQLITE_INT_MIN, strict_int

        try:
            fee = strict_int(monthly_fee)
        except (TypeError, ValueError) as exc:
            raise DeclarationDataError("衙门月费须为整数") from exc
        if fee < 0:
            raise DeclarationDataError(f"衙门月费不得为负：{fee}")
        if not (SQLITE_INT_MIN <= fee <= SQLITE_INT_MAX):
            raise DeclarationDataError("衙门月费超出 SQLite 64-bit 范围")
        existing = self._conn.execute(
            "SELECT id FROM yamens WHERE name=?",
            (yamen_name,),
        ).fetchone()
        if existing is not None:
            raise DeclarationDataError(f"同名在职衙门已存在：{yamen_name}")
        owns = connection_owns_transaction(self._conn)
        cur = self._conn.execute(
            "INSERT INTO yamens "
            "(name, chief_name, monthly_fee, fee_account, fiscal_key, "
            " origin_ref, created_turn, created_year, created_period) "
            "VALUES (?, ?, ?, ?, '', ?, ?, ?, ?)",
            (
                yamen_name,
                chief,
                fee,
                account,
                str(origin_ref or "").strip(),
                int(turn),
                int(year),
                int(period),
            ),
        )
        if owns:
            self._conn.commit()
        created = self.get(int(cur.lastrowid))
        if created is None:
            raise RuntimeError("衙门落库后读回失败")
        return created

    def set_fiscal_key(self, yamen_id: int, fiscal_key: str) -> None:
        key = str(fiscal_key or "").strip()
        if not key:
            raise DeclarationDataError("fiscal_key 不能为空")
        owns = connection_owns_transaction(self._conn)
        self._conn.execute(
            "UPDATE yamens SET fiscal_key=? WHERE id=?",
            (key, int(yamen_id)),
        )
        if owns:
            self._conn.commit()


def _row_to_yamen(row: Any) -> Yamen:
    return Yamen(
        id=int(row["id"]),
        name=str(row["name"]),
        chief_name=str(row["chief_name"] or ""),
        monthly_fee=int(row["monthly_fee"] or 0),
        fee_account=str(row["fee_account"] or "国库"),
        fiscal_key=str(row["fiscal_key"] or ""),
        origin_ref=str(row["origin_ref"] or ""),
        created_turn=int(row["created_turn"] or 0),
        created_year=int(row["created_year"] or 0),
        created_period=int(row["created_period"] or 0),
    )


def assert_chief_exists(db: Any, chief_name: str) -> str:
    """主官须为在事名册人物（ADR 0009：任职须在事）；返回规范化人名。

    只读落账时 status，不在衙门层起复或改状态；起复/昭雪走既有人事管线。
    """
    name = str(chief_name or "").strip()
    if not name:
        raise DeclarationDataError("衙门主官不能为空")
    row = db.characters.row(name, fields="name, status")
    if row is None:
        raise DeclarationReferenceError(f"主官不存在：{name}")
    status = str(row["status"] or "").strip() or "active"
    if status != "active":
        raise DeclarationDataError(f"主官不在事：{row['name']}（{status}）")
    return str(row["name"])
