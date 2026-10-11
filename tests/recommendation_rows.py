"""推荐事件落库行读取（测试侧直查；生产单读口 list_recommendation_events 已退休）。"""

from __future__ import annotations


def recommendation_events(db, state, recommender=None):
    sql = "SELECT * FROM recommendation_events WHERE turn <= ?"
    params: list[object] = [int(state.turn)]
    if recommender:
        sql += " AND recommender=?"
        params.append(recommender)
    sql += " ORDER BY turn, id"
    return [dict(row) for row in db.conn.execute(sql, params).fetchall()]
