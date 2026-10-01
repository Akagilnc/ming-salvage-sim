"""经济条目（``economy_moves``）落库段。

逐项原子：一条脏项只回滚自己那条 savepoint，同批合法项照落（ADR 0015 逐项拒收）。
归属（``origin_ref``）非法是**窄**的授权失败——只接 ``UnauthorizedAffairOriginRef``；
``TypeError`` / ``ValueError`` / ``KeyError`` 是代码故障，响亮上抛不与脏项同流
（ADR 0005）。
"""

from __future__ import annotations

from typing import List

from ming_sim.applier import SectionResult, section_from_rows


def apply(run, moves: List[object] | None = None, *, index_base: int = 0) -> SectionResult:
    """落 ``economy_moves``。

    ``moves`` 缺省读当前笔的 ``economy_moves``；``index_base`` 让 effects 逐笔
    交错时 savepoint 名不撞（同名 savepoint 会互相覆盖回滚范围）。
    """
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef
    from ming_sim.issues import _apply_economy_list, _payload_owned_dossier_for_origin

    if moves is None:
        moves = list(run.current_extracted.get("economy_moves") or [])

    rows: List[object] = []
    for offset, raw_move in enumerate(moves):
        savepoint = f"economy_affair_{index_base + offset}"
        run.db.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            move = raw_move
            if isinstance(move, dict):
                origin_ref = run.origin_ref_from_result_item(move)
                if origin_ref and not str(
                    move.get("origin_ref") or move.get("来源引用") or ""
                ).strip():
                    move = {**move, "origin_ref": origin_ref}
                if origin_ref.startswith("dossier:"):
                    dossier = _payload_owned_dossier_for_origin(run.db, origin_ref)
                    if dossier is not None and str(
                        dossier.get("action_type") or ""
                    ) == "grant_allocation":
                        # 拨款单轨已有唯一承载（#1503），重复申报不认。
                        run.db.conn.execute(f"RELEASE {savepoint}")
                        continue
            results = _apply_economy_list(
                run.db, run.state, [move], commit=False, require_origin=True,
            )
            rejected = [row for row in results if row.get("rejected")]
            if rejected:
                run.db.conn.execute(f"ROLLBACK TO {savepoint}")
                rows.extend(rejected)
            else:
                rows.extend(results)
            run.db.conn.execute(f"RELEASE {savepoint}")
        except UnauthorizedAffairOriginRef as exc:
            run.db.conn.execute(f"ROLLBACK TO {savepoint}")
            run.db.conn.execute(f"RELEASE {savepoint}")
            rows.append({
                "rejected": True, "category": "invalid_enum",
                "reason": str(exc), "item": raw_move,
            })
        except Exception:
            run.db.conn.execute(f"ROLLBACK TO {savepoint}")
            run.db.conn.execute(f"RELEASE {savepoint}")
            raise
    return section_from_rows(rows, run.ctx.source, category="economy_moves")
