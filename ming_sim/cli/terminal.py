"""CLI 终端层：input()/print() 驱动，调 GameSession 跑回合。L9。

play_turn 状态机搬入此处；GameSession 持游戏状态，terminal 只做 I/O。
拟旨候选先进 pending_actions 闸门；皇帝可在对话里准/驳，不回则颁诏 checkpoint 默认同意。
"""

from __future__ import annotations

import logging
import re
import threading
from typing import List, Optional

from ming_sim.applier import atomic
from ming_sim.constants import (
    COURT_BREAK_COMMANDS,
    EXIT_COMMANDS,
    STAY_ATTEND_COMMANDS,
    TURN_UNIT,
)
from ming_sim.assets import wrap
from ming_sim.context import match_minister_from_text
from ming_sim.exceptions import ExitGame, LLMContractError, LLMUnavailable, SettlementAbort
from ming_sim.models import API_DEFAULT_TIMEOUT_SECONDS, Character, GameState
from ming_sim.session import (
    FRONT_HALF_DONE_PHASES,
    GameSession,
    TurnPhase,
    _is_summonable_court_minister,
    _pending_action_failure_payload,
)
from ming_sim.skills import print_all_skill_cards, print_skill_card, skill_display_name

logger = logging.getLogger(__name__)

_STATUS_LABEL = {
    "active": "在朝",
    "dismissed": "已罢官",
    "imprisoned": "下狱",
    "exiled": "流戍",
    "retired": "致仕",
    "dead": "亡",
}

# 皇帝当场对拟旨草稿的回应
_CONFIRM_WORDS = {"", "可", "准", "准奏", "yes", "y", "确认", "入档"}
_REJECT_WORDS = {"驳", "不准", "驳回", "no", "n"}


def _retry_failed_pending_action(session: GameSession, action_id: int) -> None:
    """Retry a failed secret-order pending action from the CLI audience loop."""
    if getattr(session.state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
        print("上月结算未完成，暂不能重试密令；请先到诏书界面输入 issue 续跑结算。\n")
        return
    try:
        with atomic(session.db):
            result = session.db.retry_failed_pending_action(
                session.state,
                int(action_id),
                content=getattr(session, "content", None),
                registry=getattr(session, "registry", None),
            )
            if result.get("committed"):
                session.db.retire_chat_turn_for_pending_action_retry(int(action_id))
    except KeyError as exc:
        print(f"未找到可重试的密令：{exc}\n")
        return
    except ValueError as exc:
        print(f"此密令暂不能重试：{exc}\n")
        return
    if result.get("committed"):
        print(f"密令 #{int(action_id)} 已重试落库。\n")
    else:
        print(f"密令 #{int(action_id)} 重试仍未落库；可稍后再试，不阻断继续召对。\n")


def _failed_secret_order_ids(session: GameSession, turn: int) -> set[int]:
    db = getattr(session, "db", None)
    if db is None or not hasattr(db, "list_pending_actions"):
        return set()
    return {
        int(action.get("id") or 0)
        for action in db.list_pending_actions(int(turn), status="failed")
        if action.get("kind") == "secret_order"
    }


def _new_secret_order_failure_payloads(
    session: GameSession, turn: int, before_ids: set[int],
) -> List[dict]:
    db = getattr(session, "db", None)
    if db is None or not hasattr(db, "list_pending_actions"):
        return []
    failures: List[dict] = []
    for action in db.list_pending_actions(int(turn), status="failed"):
        if action.get("kind") != "secret_order":
            continue
        action_id = int(action.get("id") or 0)
        if action_id in before_ids:
            continue
        failures.append(_pending_action_failure_payload(action, session.state))
    return failures


def _print_pending_action_failures(failures: List[dict]) -> None:
    for failure in failures:
        message = str(failure.get("message") or "密令落库失败。")
        raw_failure_id = failure.get("id")
        try:
            failure_id = int(raw_failure_id) if raw_failure_id is not None else None
        except (TypeError, ValueError):
            failure_id = None
        suffix = f" #{failure_id}" if failure_id is not None else ""
        print(f"【密令落库失败{suffix}】{wrap(message)}")
        if failure.get("retryable"):
            command = f"retry {failure_id}" if failure_id is not None else "retry <id>"
            print(f"可输入 {command} 重试；本次失败不会阻断继续召对。\n")


def _print_header(session: GameSession) -> None:
    from ming_sim.report import print_header
    print_header(session.state, session.db)


def choose_minister(session: GameSession) -> Optional[Character]:
    """列大臣，皇帝选一位。返回 None 表示退朝去审阅诏书。"""
    characters = session.content.characters
    # 可召名册资格单真源 _is_summonable_court_minister（#1317 r2 DRY：与 can_summon/
    # list_ministers/visible_in_court/事实块同口径）。offstage 未登场另滤——到 debut 年月现身。
    # 后宫不经朝臣可召谓词、走 can_summon 专路，CLI 大臣单亦不列后宫（与 web consorts 分栏同形）。
    resolve = session.db.resolve_power_id
    names = [
        name for name in characters
        if _is_summonable_court_minister(characters[name], resolve_power_id=resolve)
        and session.db.get_character_status(name)[0] not in ("offstage", "candidate")
    ]
    print("\n可召见大臣：")
    for idx, name in enumerate(names, 1):
        c = characters[name]
        status, _ = session.db.get_character_status(name)
        tag = "" if status == "active" else f"  [{_STATUS_LABEL.get(status, status)}]"
        print(f"{idx}. {c.name}（{c.office}，{c.faction}）{tag}")
    while True:
        raw = input("召见谁？输入编号或姓名，skills 查看技能卡，quit 退朝审阅诏书，exit 退出游戏：").strip()
        if not raw:
            print("请输入编号或姓名。")
            continue
        lowered = raw.lower()
        if lowered in EXIT_COMMANDS:
            raise ExitGame
        if lowered in COURT_BREAK_COMMANDS:
            return None
        if lowered in {"skills", "skill", "技能", "技能卡", "查看技能"}:
            print_all_skill_cards(session.db)
            continue
        candidate: Optional[Character] = None
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            candidate = characters[names[int(raw) - 1]]
        elif raw in characters:
            candidate = characters[raw]
        else:
            matches = [
                c for c in characters.values()
                if raw in c.name or raw in c.office or raw in c.office_type
                or raw in c.faction or raw in c.aliases
            ]
            if len(matches) == 1:
                candidate = matches[0]
            elif len(matches) > 1:
                print("这句话能对应多位大臣，请再说具体一点，或直接输编号。")
                continue
        if candidate is None:
            # #670：未知/未注册人物不得临时旁路入殿；须 ADR 0038 持久入册后再走 admission。
            try:
                candidate, _is_temporary = session.summon_character(
                    raw, None, allow_temporary=False,
                )
            except ValueError:
                print("请输入有效编号或姓名。")
                continue
        # 召对总闸 can_summon（含宗藩拒 + 非 active 拒）——按名/编号/模糊任一路解析到的人都过此闸，
        # 与 web /chat、LLM summon 工具同口径集中守（cmr R6：CLI 选臣菜单原先只查 status、漏宗藩）。
        decision = session.consume_audience_admission(
            candidate,
            origin_id=f"cli:initial:{session.state.turn}:{candidate.name}",
        )
        if not decision.allowed:
            # 资格失败仍见 reason；成功记召 reason 为空，不喷固定承旨句。
            if decision.reason:
                print(decision.reason)
            continue
        return candidate


def _skill_ids_from_text(session: GameSession, text: str) -> List[str]:
    matched: List[str] = []
    for keyword, skill_ids in session.content.grant_keywords.items():
        if keyword in text:
            matched.extend(skill_ids)
    for skill_id, definition in session.content.skill_catalog.items():
        name = str(definition.get("name", ""))
        if skill_id in text or (name and name in text):
            matched.append(skill_id)
    unique: List[str] = []
    seen: set = set()
    for skill_id in matched:
        if skill_id not in seen:
            seen.add(skill_id)
            unique.append(skill_id)
    return unique


def _fail_cli_chat_turn_scene(
    session: GameSession,
    chat_turn_id: int,
    *,
    before_snapshot=None,
    scaffold_owned: bool = False,
    entry_id: int = 0,
) -> None:
    """CLI chat-turn scene 失败清理——与 minister_chat 中断同族（abandon + fail/回滚）。

    cleanup 自身失败由调用方链到原 scene 异常（不得 `except: pass` 吞掉）。
    """
    session.abandon_chat_turn_scene(int(chat_turn_id))
    if scaffold_owned:
        if before_snapshot is not None and hasattr(
            session.db, "record_chat_turn_rollback_diffs",
        ):
            session.db.record_chat_turn_rollback_diffs(
                int(chat_turn_id),
                before_snapshot,
                session.db.capture_chat_rollback_snapshot(),
            )
        # Delete scaffold exit placeholder in the same cleanup path before fail.
        # fail_chat_turn also drops origin-bound rows; explicit entry_id covers
        # doubles whose fail path is thinner than production GameDB.
        if entry_id and hasattr(session.db, "conn") and getattr(session.db, "conn", None):
            session.db.conn.execute(
                "DELETE FROM story_ledger_entries WHERE id = ?",
                (int(entry_id),),
            )
            session.db.conn.commit()
        session.db.fail_chat_turn(int(chat_turn_id))
        return
    if entry_id:
        # Prior Q&A turn must stay intact; only drop the failed exit placeholder.
        session.db.conn.execute(
            "DELETE FROM story_ledger_entries WHERE id = ?",
            (int(entry_id),),
        )
        session.db.conn.commit()


def _record_audience_exit(session: GameSession, name: str) -> None:
    """CLI「退下」控制口令：垫位告退 + 唯一 scene registry 生成 exit 旁白。

    此路不经 session.chat，须自落；tool dismiss 由 session.chat 单缝处理。
    禁止同步 beat_generator（#542）：失败走 abandon + fail/回滚，与回话中断同族。
    无开夜/不在场时既有 no-op；缺 conn 的轻量 session double 跳过。
    """
    if not hasattr(session.db, "conn"):
        return
    from ming_sim.applier import atomic
    from ming_sim.audience_night import dismiss_from_audience, get_open_night

    open_n = get_open_night(session.db)
    if open_n is None:
        dismiss_from_audience(session.db, name, state=session.state)
        return
    night_id = int(open_n["id"])

    can_scene = all(
        hasattr(session, attr)
        for attr in (
            "start_chat_turn_exit_scene",
            "join_chat_turn_scene",
            "persist_chat_turn_scene",
            "abandon_chat_turn_scene",
        )
    )
    can_turn = hasattr(session.db, "create_chat_turn") and hasattr(session.db, "fail_chat_turn")

    chat_turn_id = 0
    scaffold_owned = False
    before_snapshot = None
    if can_scene and can_turn:
        row = session.db.conn.execute(
            "SELECT id FROM chat_turns WHERE night_id = ? AND minister_name = ? "
            "AND status IN ('active', 'generating') ORDER BY id DESC LIMIT 1",
            (night_id, name),
        ).fetchone()
        if row is not None:
            chat_turn_id = int(row["id"])
        else:
            if hasattr(session.db, "capture_chat_rollback_snapshot"):
                before_snapshot = session.db.capture_chat_rollback_snapshot()
            chat_turn_id = int(session.db.create_chat_turn(
                session.state, name, f"cli-exit:{name}", 0, night_id=night_id,
            ))
            scaffold_owned = True
        if before_snapshot is None and hasattr(session.db, "capture_chat_rollback_snapshot"):
            before_snapshot = session.db.capture_chat_rollback_snapshot()

    entry_id = dismiss_from_audience(
        session.db, name, night_id=night_id,
        origin_chat_turn_id=int(chat_turn_id or 0),
        state=session.state,
    )
    if not entry_id:
        if scaffold_owned and chat_turn_id:
            session.db.fail_chat_turn(int(chat_turn_id))
        return
    if not (can_scene and chat_turn_id):
        return

    session.start_chat_turn_exit_scene(
        name, int(chat_turn_id), int(entry_id), night_id=night_id,
    )
    try:
        generated = session.join_chat_turn_scene(int(chat_turn_id))
        with atomic(session.db):
            session.persist_chat_turn_scene(generated)
        # Scaffold turn has no minister reply — retire so in-flight guards stay clear.
        # Exit ledger keeps origin binding; success path does not record rollback diffs.
        if scaffold_owned:
            session.db.mark_chat_turn_failed(int(chat_turn_id))
    except BaseException as exc:
        # 与 minister_chat 失败清理同族：abandon + rollback/fail；cleanup 失败链到原异常。
        try:
            _fail_cli_chat_turn_scene(
                session, int(chat_turn_id),
                before_snapshot=before_snapshot,
                scaffold_owned=scaffold_owned,
                entry_id=int(entry_id),
            )
        except BaseException as cleanup_error:
            raise exc from cleanup_error
        raise


def _handle_court_command(
    session: GameSession, text: str, current: Character
) -> Optional[str]:
    """CLI 控制指令识别。返回：'dismiss' | 'court_break' | 'summon:<name>' |
    'handled'（技能等已处理）| None（非控制指令，交给 chat）。"""
    raw = text.strip()
    lowered = raw.lower()
    if lowered in EXIT_COMMANDS:
        raise ExitGame
    if lowered in COURT_BREAK_COMMANDS or raw in COURT_BREAK_COMMANDS:
        return "court_break"

    # #526：留侍口令（确定性封闭集；落叙事账、在场不变）
    if raw in STAY_ATTEND_COMMANDS or lowered in STAY_ATTEND_COMMANDS:
        from ming_sim.audience_night import stay_attend_in_audience
        stay_attend_in_audience(session.db, current.name)
        print(f"{current.name}留下听着，殿侧侍立。\n")
        return "handled"

    retry_m = re.fullmatch(r"(?:retry|重试|重试密令)\s*#?(\d+)", raw, re.I)
    if retry_m:
        _retry_failed_pending_action(session, int(retry_m.group(1)))
        return "handled"

    # 技能卡查看
    if (lowered in {"skills", "skill", "技能", "技能卡", "查看技能", "查看skill"} or "技能" in raw) \
            and not any(w in raw for w in ("授权", "授予", "交给", "收回", "撤销", "取消授权", "命", "令", "着")):
        target = match_minister_from_text(raw, None) or current
        print_skill_card(target, session.db)
        print()
        return "handled"

    # 收回授权
    if "授权" in raw and any(w in raw for w in ("收回", "撤销", "取消", "停用", "夺回")):
        target = match_minister_from_text(raw, None) or current
        revoked = [
            skill_display_name(sid)
            for sid in _skill_ids_from_text(session, raw)
            if session.db.revoke_skill(target.name, sid)
        ]
        if revoked:
            print(f"已收回{target.name}：{'、'.join(revoked)}。\n")
            session.registry.refresh(target.name)
        else:
            print(f"{target.name}没有可收回的相关授权，或未识别要收回的 skill。\n")
        return "handled"

    # 退下（短句正则，不误伤长对话）
    if re.fullmatch(
        r"\s*(退下|退了|跪安|下去|done|dismiss|让[他其]退下|叫[他其]退下|让此人退下|叫此人退下)\s*",
        raw, re.I,
    ):
        return "dismiss"

    # 召见（传/召/宣/叫 开头）
    # 量词须写 `{1,12}`；`{1,12?}` 会被解析成字面 `{1,1` + 可选 `2` + `}`，永远匹配失败。
    summon_m = re.match(
        r"^(?:传召|传|召|宣|叫|带)(.{1,12})(?:来|到|入殿|上殿|面圣|见我)$",
        raw,
    )
    if summon_m:
        name_fragment = summon_m.group(1)
        # #670：未知/未注册人物不得临时旁路入殿；须 ADR 0038 持久入册后再走 admission。
        try:
            target, _is_temporary = session.summon_character(
                name_fragment, current, allow_temporary=False,
            )
        except ValueError:
            print("人物未建档，须先补档后方可召见。\n")
            return "handled"
        # #670：夜内换人与初选同吃 consume_audience_admission；场外/在途只落传召账，不返 summon:。
        decision = session.consume_audience_admission(
            target,
            origin_id=f"cli:midflow:{session.state.turn}:{target.name}",
        )
        if not decision.allowed:
            # 资格失败仍见 reason；成功记召 reason 为空，不喷固定承旨句。
            if decision.reason:
                print(decision.reason + "\n")
            return "handled"
        return f"summon:{target.name}"

    # 授予授权
    if any(w in raw for w in ("授权", "交给", "授予")):
        target = match_minister_from_text(raw, None) or current
        granted = [
            skill_display_name(sid)
            for sid in _skill_ids_from_text(session, raw)
            if session.db.grant_skill(session.state, target.name, sid)
        ]
        if granted:
            print(f"已授权{target.name}：{'、'.join(granted)}。\n")
            session.registry.refresh(target.name)
        else:
            print(f"{target.name}已有相关授权，或未识别要授权的 skill。\n")
        return "handled"

    return None


def _confirm_pending_directive(session: GameSession, draft, minister_name: str) -> None:
    """Legacy CLI display only; end-turn default approval owns submission."""
    print(f"\n{minister_name}拟旨如下：\n")
    print("─" * 50)
    print(draft.text)
    print("─" * 50)
    print(f"此旨已候结束本{TURN_UNIT}成案。\n")


def _print_interrupted_reply_retry_hint(session: GameSession, minister_name: str) -> None:
    """#505：CLI 系统层恢复提示——崩溃后问话保留，可输入「重试回话」重新生成。"""
    db = getattr(session, "db", None)
    if db is None or not hasattr(db, "get_interrupted_reply_retries"):
        return
    retries = db.get_interrupted_reply_retries(minister_name) or []
    if not retries:
        return
    last = retries[-1]
    question = str(last.get("question") or "").strip()
    print(
        "【回话中断】上回问话未得回话"
        f"{f'（「{question}」）' if question else ''}。"
        "输入「重试回话」重新生成回话（系统层恢复，不重复记问话）。\n"
    )



def _retry_interrupted_reply_cli(session: GameSession, minister_name: str) -> Optional[str]:
    """#505 CLI：复用已持久问话重新生成回话（与 web retry 同核语义：不重记问话）。

    成功且 court_action 为 court_break 时返回 typed 'court_break'，供 minister_chat
    退出对话进入 play_turn 审阅；收夜失败仍返回 None，留在原对话。
    """
    db = getattr(session, "db", None)
    if db is None or not hasattr(db, "get_interrupted_reply_retries"):
        print("当前会话不支持回话重试。\n")
        return
    retries = db.get_interrupted_reply_retries(minister_name) or []
    if not retries:
        print(f"{minister_name}没有待重试的中断回话。\n")
        return
    target = retries[-1]
    chat_turn_id = int(target["chat_turn_id"])
    question = str(target["question"])
    accepted_turn = int(target.get("turn") or session.state.turn)
    before_snapshot = (
        db.capture_chat_rollback_snapshot()
        if hasattr(db, "capture_chat_rollback_snapshot") else {}
    )
    if not db.reopen_interrupted_chat_turn_for_retry(chat_turn_id):
        print(f"{minister_name}上一轮回奏仍在进行，请稍候再问。\n")
        return
    # #1566：route 权威解码——与 Web retry 同核；场外密令不启殿上 scene。
    from ming_sim.audience_night import decode_chat_turn_route
    retry_route = decode_chat_turn_route(target.get("route"))
    # #634：重试回话同形——判官拍先于重新生成派发（与回话并行）。
    _dispatch_relation_judge_cli(session, chat_turn_id)
    try:
        if retry_route["start_hall_scene"]:
            session.start_chat_turn_scene(minister_name, chat_turn_id)
        result = session.chat(
            minister_name, question,
            chat_turn_id=chat_turn_id,
            explicit_secret_order=retry_route["explicit_secret_order"],
        )
        answer = str(getattr(result, "answer", "") or "")
        if hasattr(db, "persist_minister_reply"):
            scene_generated = session.join_chat_turn_scene(chat_turn_id)
            from ming_sim.applier import atomic
            with atomic(db):
                session.persist_chat_turn_scene(scene_generated)
                db.persist_minister_reply(minister_name, accepted_turn, answer, chat_turn_id)
        else:
            mid = db.append_chat_message(minister_name, accepted_turn, "minister", answer)
            db.update_chat_turn_messages(chat_turn_id, minister_message_id=int(mid))
        if hasattr(db, "record_chat_turn_rollback_diffs") and before_snapshot is not None:
            db.record_chat_turn_rollback_diffs(
                chat_turn_id, before_snapshot, db.capture_chat_rollback_snapshot(),
            )
        # #501：重试回话成功后与正常回话同路径尾随抽取。
        _trail_extraction_after_reply_cli(session, minister_name, answer, chat_turn_id)
        print(f"\n{minister_name}：{wrap(answer)}\n")
    except Exception as exc:
        # 失败翻回 interrupted 保持可再重试（与 web restore_interrupted_after_failed_retry 同语义）。
        try:
            if hasattr(db, "record_chat_turn_rollback_diffs") and before_snapshot is not None:
                db.record_chat_turn_rollback_diffs(
                    chat_turn_id, before_snapshot, db.capture_chat_rollback_snapshot(),
                )
            if hasattr(db, "restore_interrupted_after_failed_retry"):
                db.restore_interrupted_after_failed_retry(chat_turn_id)
        except Exception:
            pass
        session.abandon_chat_turn_scene(chat_turn_id)
        print(f"重试回话失败：{exc}\n")
        return None
    # #1716：与 Web retry 同缝——回话已落库后消费 court_action 收夜。
    # 收夜失败响亮可观察，不得回滚已成回话；夜可恢复，仍留原对话。
    # 成功收夜（court_action=court_break）传播 typed court_break → minister_chat → 审阅。
    court_action = str(getattr(result, "court_action", "") or "")
    close_after = getattr(session, "close_night_after_chat_if_needed", None)
    if close_after is not None:
        from ming_sim.audience_night import AudienceNightError
        try:
            close_after(
                court_action,
                write_gate=_cli_write_gate(session),
            )
        except (AudienceNightError, LLMUnavailable) as err:
            print(f"\n收夜未成：{err}\n")
            return None
    if court_action == "court_break":
        return "court_break"
    return None


def _cli_write_gate(session: GameSession):
    """CLI 唯一 write gate：与 resolve_turn 收夜/过月屏障同穿（#1353 队列）。

    GameSession 构造已 eager 装队列；此处只解析既有 ledger，不二次安装、不宽吞重挂，
    禁第二锁名分叉（trail 与颁诏 auto_close 必须同闸）。
    """
    from ming_sim.session_write_queue import get_session_write_queue
    return get_session_write_queue(session).write_gate


def _trail_extraction_after_reply_cli(
    session: GameSession,
    minister_name: str,
    minister_reply: str,
    chat_turn_id: int,
) -> None:
    """#501：CLI 回话落库后自动尾随抽取（与 Web `_trail_extraction_after_reply` 同核）。

    同步调用——CLI 无后台线程池；失败标待补、不抛、不回滚回话。
    #1353：起跑领 turn key 票，写经票据执行 seam（与 Web 生产同形）。
    """
    if not chat_turn_id:
        return
    ticket = None
    q = None
    try:
        from ming_sim.audience_extraction import trail_extraction_after_reply
        from ming_sim.session_write_queue import (
            TicketCancelled,
            get_session_write_queue,
        )
        q = get_session_write_queue(session)
        ticket = q.claim(key=("turn", int(chat_turn_id)))
        if ticket is None:
            return
        write_gate = q.ticketed_gate(ticket)
        try:
            trail_extraction_after_reply(
                db=session.db,
                minister_name=minister_name,
                minister_reply=str(minister_reply or ""),
                chat_turn_id=int(chat_turn_id),
                llm_config=getattr(session, "llm_config", None),
                write_gate=write_gate,
            )
        except TicketCancelled:
            pass
    except Exception:
        # 共享核从不抛；到此=import 等外围故障——不锁档、不打断对话。
        # #1353 fold-in r5：欠账唯一处理路=过月内部 drain；禁玩家可见技术提示。
        pass
    finally:
        # 局部 q 归票——禁二次 get_session_write_queue（重解析可叉 ledger 漏票挂死 CLI）。
        if ticket is not None and q is not None:
            q.complete(ticket)


def _dispatch_relation_judge_cli(session: GameSession, chat_turn_id: int) -> None:
    """#634 / ADR 0082：CLI 召对判官拍派发——与回话生成并行的 daemon 线程。

    派发先于回话（不依赖本轮回话输出，TD-9 零额外等待）；写经票据执行 seam
    （与 Web 生产同形）。LLM 失败降级留痕不抛——判官漏判不阻塞召对主链。
    """
    if not chat_turn_id:
        return
    q = None
    try:
        from ming_sim.session_write_queue import get_session_write_queue
        q = get_session_write_queue(session)
    except Exception:
        logger.exception("relation judge queue resolution degraded chat_turn_id=%s", chat_turn_id)
        return

    # Admission belongs to the dispatcher: a close barrier must see the worker
    # before Thread.start, exactly as the Web spawner does.
    ticket = q.claim(key=("turn", int(chat_turn_id)))
    if ticket is None:
        return

    def _run() -> None:
        try:
            from ming_sim.relation_judge import run_summon_relation_judge
            run_summon_relation_judge(
                session.db, session.state,
                llm_config=getattr(session, "llm_config", None),
                write_gate=q.ticketed_gate(ticket),
            )
        except Exception:
            # 核心 LLM 降级在 run_summon_relation_judge；到此是外围基础设施故障，
            # 仍不得打断对话，但必须响亮留痕。
            logger.exception("relation judge worker degraded chat_turn_id=%s", chat_turn_id)
        finally:
            q.complete(ticket)

    thread = threading.Thread(
        target=_run, daemon=True, name="cli-audience-relation-judge",
    )
    try:
        thread.start()
    except Exception:
        q.complete(ticket)
        logger.exception("relation judge thread start degraded chat_turn_id=%s", chat_turn_id)


def minister_chat(session: GameSession, character: Character) -> str:
    """与一位大臣对话。返回 'dismiss' | 'court_break' | 'summon:<name>'。"""
    other = next((n for n in session.content.characters if n != character.name), character.name)
    print(f"\n{character.name}入殿。可持续问话；done/退下 退下，“传{other}来”换人，quit 退朝审阅诏书，exit 退出游戏。")
    print("提示：陛下示意采纳后（如“准奏”），大臣会拟旨呈陛下核定。\n")
    # #505：入殿时显眼提示回话中断恢复入口（与 web ChatModal 同语义）。
    # #1353：欠账抽取无玩家手动补写面——过月内部 drain 唯一处理路。
    _print_interrupted_reply_retry_hint(session, character.name)
    while True:
        question = input("朕问：").strip()
        if not question:
            print("可继续问话；若要让其退下，请输入 done。")
            continue
        # #505 系统层恢复命令（非皇帝内容选项）。禁抽取手动补写平行面（#1353）。
        low_q = question.lower().strip()
        if low_q in {"重试回话", "retry reply", "retry_reply"}:
            retry_action = _retry_interrupted_reply_cli(session, character.name)
            if retry_action == "court_break":
                print(f"{character.name}退下。\n")
                return "court_break"
            continue
        cmd = _handle_court_command(session, question, character)
        if cmd == "handled":
            continue
        if cmd == "dismiss":
            _record_audience_exit(session, character.name)
            print(f"{character.name}退下。\n")
            return "dismiss"
        if cmd == "court_break":
            # #526：高置信收夜口令 → 收夜提交；失败响亮可观察，夜可恢复，不假成功退朝。
            from ming_sim.audience_night import AudienceNightError, auto_close_open_night
            close_fn = getattr(session, "close_night_after_chat_if_needed", None)
            try:
                if close_fn is not None:
                    close_fn("court_break", write_gate=_cli_write_gate(session))
                else:
                    auto_close_open_night(
                        session.db, session.state,
                        content=getattr(session, "content", None),
                        wait_timeout_s=0.0,
                        write_gate=_cli_write_gate(session),
                        llm_config=getattr(session, "llm_config", None),
                    )
            except (AudienceNightError, LLMUnavailable) as err:
                # #1353 fold-in r8：欠账耗尽/收夜失败留本回合，可重按退朝；CLI 不退出。
                print(f"\n收夜未成：{err}\n")
                continue
            print(f"{character.name}退下。\n")
            return "court_break"
        if cmd and cmd.startswith("summon:"):
            target_name = cmd.split(":", 1)[1]
            print(f"{character.name}退下。\n传{target_name}入殿。\n")
            return cmd
        # 非控制指令 → 与 agent 对话。CLI 也落 chat_messages，供 session.chat
        # 内部的密令短确认上下文读取（web 路已有同款持久化）。
        persistent_chat = character.name not in session.temporary_characters
        accepted_turn = int(session.state.turn)
        user_message_id: int | None = None
        chat_turn_id = 0
        rollback_snapshot = None
        result = None
        lifecycle_supported = all(hasattr(session.db, name) for name in (
            "capture_chat_rollback_snapshot", "create_chat_turn",
            "update_chat_turn_messages", "record_chat_turn_rollback_diffs", "fail_chat_turn",
        ))
        try:
            # #1566：CLI 前缀密令落 route=secret_order，供中断重试权威解码。
            from ming_sim.cli_backend import _SECRET_PREFIXES
            cli_explicit_secret = question.startswith(_SECRET_PREFIXES)
            from ming_sim.audience_night import encode_chat_turn_route
            cli_route = encode_chat_turn_route(explicit_secret_order=cli_explicit_secret)
            if persistent_chat:
                if lifecycle_supported:
                    rollback_snapshot = session.db.capture_chat_rollback_snapshot()
                    # #498：CLI 与 web 共用 attach_chat_turn_to_night，禁止 night_id=0 旁路
                    # #503/#542：生产路径与 Web/收夜共用真实 scene LLM adapter。
                    from ming_sim.audience_night import attach_chat_turn_to_night
                    _night_id, chat_turn_id = attach_chat_turn_to_night(
                        session.db,
                        session.state,
                        character.name,
                        agno_session_id=f"cli:{character.name}",
                        agno_runs_before=0,
                        beat_generator=None,
                        route=cli_route,
                    )
                    session.start_chat_turn_scene(character.name, chat_turn_id)
                user_message_id = session.db.append_chat_message(
                    character.name, accepted_turn, "user", question,
                )
                if chat_turn_id:
                    session.db.update_chat_turn_messages(
                        chat_turn_id, user_message_id=user_message_id,
                    )
            # #634：判官拍先于回话派发（与回话生成并行，TD-9）。
            _dispatch_relation_judge_cli(session, chat_turn_id)
            result = session.chat(
                character.name, question,
                chat_turn_id=chat_turn_id,
                explicit_secret_order=cli_explicit_secret,
            )
            if persistent_chat:
                if (chat_turn_id and hasattr(session.db, "persist_minister_reply")
                        and hasattr(session, "join_chat_turn_scene")):
                    scene_generated = session.join_chat_turn_scene(chat_turn_id)
                    from ming_sim.applier import atomic
                    with atomic(session.db):
                        session.persist_chat_turn_scene(scene_generated)
                        session.db.persist_minister_reply(
                            character.name, accepted_turn, result.answer, chat_turn_id,
                        )
                    minister_message_id = 0
                else:
                    minister_message_id = session.db.append_chat_message(
                        character.name, accepted_turn, "minister", result.answer,
                    )
                if chat_turn_id:
                    if minister_message_id:
                        session.db.update_chat_turn_messages(
                            chat_turn_id, minister_message_id=minister_message_id,
                        )
                    session.db.record_chat_turn_rollback_diffs(
                        chat_turn_id, rollback_snapshot or {},
                        session.db.capture_chat_rollback_snapshot(),
                    )
                    # #501：回话入档后自动尾随抽取（与 Web 同核；失败标待补不抛）。
                    _trail_extraction_after_reply_cli(
                        session, character.name, result.answer, chat_turn_id,
                    )
        except BaseException as original_error:
            try:
                if chat_turn_id:
                    session.abandon_chat_turn_scene(chat_turn_id)
                    session.db.record_chat_turn_rollback_diffs(
                        chat_turn_id, rollback_snapshot or {},
                        session.db.capture_chat_rollback_snapshot(),
                    )
                    session.db.fail_chat_turn(chat_turn_id)
                elif user_message_id is not None and result is None:
                    session.db.delete_chat_messages([user_message_id])
            except BaseException as cleanup_error:
                raise original_error from cleanup_error
            raise
        print(wrap(result.answer))
        print()
        _print_pending_action_failures(getattr(result, "pending_action_failures", []) or [])
        if result.proposed_directive is not None:
            _confirm_pending_directive(session, result.proposed_directive, character.name)
        if result.appointed_minister:
            print(f"【吏部铨选】{result.appointed_minister}已补入朝堂名册，本回合起可召见。\n")
        if result.registered_minister:
            print(f"【人物补档】{result.registered_minister}已补入人物档，本回合起可召见。\n")
        if result.displaced_minister:
            print(f"【腾缺去职】{result.displaced_minister}原任官缺由新任接掌，已罢黜出朝堂名册。\n")
        if result.court_action == "dismiss":
            # 告退账已由 session.chat（court_action=dismiss 单缝）落地，此处不重复写。
            print(f"{character.name}退下。\n")
            return "dismiss"
        if result.court_action == "summon" and result.next_minister:
            is_temporary = result.next_minister in session.temporary_characters
            print(f"{character.name}退下。\n{'临时传' if is_temporary else '传'}{result.next_minister}入殿。\n")
            return f"{'summon-temp' if is_temporary else 'summon'}:{result.next_minister}"


def review_directives(session: GameSession) -> str:
    """诏书草案审阅界面。返回 'issue' | 'back' | 'skip'。"""
    session.enter_review()
    while True:
        directives = session.list_directives(include_pending=True)
        pending = [d for d in directives if d.status == "pending"]
        drafts = [d for d in directives if d.status == "draft"]
        staged_directives = [
            p for p in session.db.list_pending_actions(session.state.turn)
            if p.get("kind") == "directive"
        ]
        print(f"\n本{TURN_UNIT}诏书草案：")
        if pending:
            print(f"  · {len(pending)} 道历史拟旨候结束回合成案：")
            for d in pending:
                print(f"  [待核定] #{d.id}  {wrap(d.text)}")
        if staged_directives:
            print(f"  · {len(staged_directives)} 道对话拟旨待颁诏默认同意。")
        if drafts:
            for idx, d in enumerate(drafts, 1):
                print(f"{idx}. #{d.id}")
                print(f"   {wrap(d.text)}")
        elif not pending and not staged_directives:
            print("（暂无指令。back 继续召见，或 add 新增。）")
        print("\n操作：issue 结束回合 | back 继续召见 | add 新增 | edit N 改 | del N 删 | "
              "skills 技能卡 | exit 退出")
        raw = input("诏书草案> ").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered in EXIT_COMMANDS:
            raise ExitGame
        if lowered in COURT_BREAK_COMMANDS:
            if drafts or pending or staged_directives:
                print(f"本{TURN_UNIT}尚有候选旨意；退朝将按结束回合规则成案。请输入 issue。")
                continue
            return "skip"
        if lowered in {"back", "b", "返回", "继续召见"}:
            from ming_sim.session import FRONT_HALF_DONE_PHASES
            if session.state.turn_phase in FRONT_HALF_DONE_PHASES:
                # 粘滞相位下 back 是静默 no-op，play_turn 会立刻把人弹回本菜单——
                # 给一行提示，别让玩家以为按键失灵（ship-pre r6）。
                print("\n上月结算未完成，无法继续召见；请输入 issue 续跑结算。")
                continue
            session.back_to_summoning()
            return "back"
        if lowered in {"skills", "skill", "技能", "技能卡", "查看技能"}:
            print_all_skill_cards(session.db)
            continue
        if lowered in {"issue", "颁布", "颁布诏书", "发布", "拟诏"}:
            from ming_sim.session import FRONT_HALF_DONE_PHASES
            if session.state.turn_phase in FRONT_HALF_DONE_PHASES:
                # 恢复态：上月结算未完成（崩溃/中止后），跳过拟诏直接续跑结算——
                # resolve_turn 的恢复分流自己决定重放/重新推演/回放决策点
                # （ship-pre r3：write_decree 在此态必拒，不开此口 CLI 永远够不到恢复入口）。
                print("\n检测到上月结算未完成，续跑结算……")
                return "issue"
            return "issue"
        # 变更器统一接 ValueError（FRONT_HALF_DONE 冻结期的指引消息）：打印后留在
        # 审阅循环，不崩出进程（ship-pre r2，与 write_decree 既有 try 同款）。
        try:
            if lowered == "add" or raw == "新增":
                text = input("指令内容：").strip()
                if text:
                    from ming_sim.cli_backend import capture_manual_directive_payload
                    dv = session.add_directive(
                        text,
                        dossier_payload=capture_manual_directive_payload(
                            text, session.llm_config,
                            **({"db": session.db, "content": session.content}
                               if getattr(session, "content", None) is not None else {}),
                        ),
                    )
                    print(f"已新增草案 #{dv.id}。")
                else:
                    print("指令为空，已取消。")
                continue
            parts = raw.split(maxsplit=1)
            verb = parts[0].lower()
            if len(parts) == 2 and parts[1].lstrip("#").isdigit():
                target_id = int(parts[1].lstrip("#"))
                if verb in {"edit", "改", "修改"}:
                    if not any(d.id == target_id for d in drafts):
                        print("没有这条草案。")
                        continue
                    new_text = input("新的指令内容：").strip()
                    if new_text:
                        from ming_sim.cli_backend import capture_manual_directive_payload
                        row = next(
                            r for r in session.db.list_directives(
                                session.state, statuses=("draft",),
                            ) if int(r["id"]) == target_id
                        )
                        existing_payload = session.db.read_directive_dossier_payload(row)
                        session.update_directive(
                            target_id,
                            new_text,
                            dossier_payload=capture_manual_directive_payload(
                                new_text, session.llm_config,
                                existing_mode=existing_payload.get("mode"),
                                **({"db": session.db, "content": session.content}
                                   if getattr(session, "content", None) is not None else {}),
                            ),
                        )
                        print("已修改。")
                    continue
                if verb in {"del", "delete", "删", "删除"}:
                    if any(d.id == target_id for d in drafts):
                        session.delete_directive(target_id)
                        print("已删除。")
                    elif any(d.id == target_id for d in pending):
                        print("对话拟旨不在此复审；请结束回合成案。")
                    else:
                        print("没有这条草案。")
                    continue
        except ValueError as error:
            print(f"\n{error}")
            continue
        print("未识别操作。")


def _submit_first_cli_decisions(session: GameSession, result) -> str:
    """CLI 暂无亲裁 UI：所有结算入口共用同一首选项续跑策略。

    #657：经 session.submit_hitl_choices 唯一编排；注入既有 `_cli_write_gate`。
    首选项投影走 ``project_preferred_hitl_choice`` 唯一真源（急务=follow_draft+capability）。
    """
    if result is None or not result.awaiting:
        return "" if result is None else result.report
    from ming_sim.rescript_actions import project_preferred_hitl_choice

    print("\n【月末重大抉择】（CLI 暂自动取首选项；交互式裁决见网页版）")
    # result.decisions 已是合并 desk；若空则回读 session.pending_decisions
    decisions = list(result.decisions or []) or list(session.pending_decisions())
    choices = []
    for decision in decisions:
        item = project_preferred_hitl_choice(decision)
        print(f"  · {decision.get('title')} → {item.get('label', '（无）')}")
        choices.append(item)
    return session.submit_hitl_choices(choices, write_gate=_cli_write_gate(session))


def play_turn(session: GameSession) -> None:
    """一回合 CLI 驱动：召见 → 审阅 → 颁诏推演。"""
    snap = session.begin_turn()
    _print_header(session)
    if session.previous_summary:
        print(session.previous_summary)
        print()
    if snap.deaths_this_turn:
        names = "、".join(f"{d['name']}（{d['office']}）" for d in snap.deaths_this_turn)
        print(f"【讣闻】本{TURN_UNIT}卒：{names}\n")
    from ming_sim.issues import show_active_issues
    show_active_issues(session.db)

    pending_character: Optional[Character] = None
    while True:
        if session.current_phase() == TurnPhase.SUMMONING:
            character = pending_character or choose_minister(session)
            pending_character = None
            if character is None:
                action = review_directives(session)
            else:
                chat_action = minister_chat(session, character)
                if chat_action == "dismiss":
                    continue
                if chat_action.startswith("summon:"):
                    pending_character = session.content.characters[chat_action.split(":", 1)[1]]
                    continue
                if chat_action.startswith("summon-temp:"):
                    pending_character = session.temporary_characters[chat_action.split(":", 1)[1]]
                    continue
                # court_break 或对话结束 → 审阅
                action = review_directives(session)
        else:
            action = review_directives(session)

        if action == "back":
            continue
        if action == "skip":
            turn_before = int(session.state.turn)
            failed_before = _failed_secret_order_ids(session, turn_before)
            try:
                # #1353 fold-in r8：颁诏/退朝前挂唯一 write_gate，使 resolve 收夜 drain 同流。
                _cli_write_gate(session)
                result = session.advance_without_decree()
                report = _submit_first_cli_decisions(session, result)
            except (ValueError, SettlementAbort, LLMUnavailable, LLMContractError) as error:
                # 跳过与颁诏共享可恢复结算语义：失败后留在本回合循环，允许重试。
                # #1353 fold-in r8：统一重试耗尽的 LLMUnavailable 不退出 CLI。
                # #1700：空 simulator 的 LLMContractError 同形，不落到 run_cli「程序中止」。
                print(f"\n{error}")
                _print_pending_action_failures(
                    _new_secret_order_failure_payloads(session, turn_before, failed_before)
                )
                continue
            _print_pending_action_failures(
                _new_secret_order_failure_payloads(session, turn_before, failed_before)
            )
            if result is not None:
                print(report)
                session.end_turn()
            return
        if action == "issue":
            turn_before = int(session.state.turn)
            failed_before = _failed_secret_order_ids(session, turn_before)
            try:
                # #1353 fold-in r8：颁诏/退朝前挂唯一 write_gate，使 resolve 收夜 drain 同流。
                _cli_write_gate(session)
                result = session.resolve_turn()
                report = _submit_first_cli_decisions(session, result)
            except (ValueError, SettlementAbort, LLMUnavailable, LLMContractError) as error:
                # 恢复态守门 / 结算中止 / 欠账耗尽（#1353 r8）/ 契约失败（#1700）：打印指引后留在
                # 本回合交互循环——玩家重按 issue/skip 即重试整段，CLI 不退出。
                print(f"\n{error}")
                _print_pending_action_failures(
                    _new_secret_order_failure_payloads(session, turn_before, failed_before)
                )
                continue
            _print_pending_action_failures(
                _new_secret_order_failure_payloads(session, turn_before, failed_before)
            )
            print(report)
            session.end_turn()
            return


def run_cli(
    base_url: str,
    model: str,
    db_path: str,
    api_key: str = "",
    start_ym: str = "",
    advanced_model: str = "",
    advanced_base_url: str = "",
    advanced_api_key: str = "",
    timeout_seconds: float = API_DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """CLI 主循环：建 GameSession，逐回合 play_turn。"""
    from ming_sim.llm_config import load_llm_config
    from ming_sim.exceptions import LLMUnavailable, LLMContractError
    from ming_sim.token_stats import print_token_summary

    session: Optional[GameSession] = None
    try:
        llm_config = load_llm_config(
            base_url,
            model,
            api_key=api_key,
            advanced_model=advanced_model,
            advanced_base_url=advanced_base_url,
            advanced_api_key=advanced_api_key,
            timeout_seconds=timeout_seconds,
        )
        import os
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        session = GameSession(db_path, llm_config, start_ym=start_ym)
        # #1353 fold-in r8：建 session 即挂唯一 write_gate，trail/收夜/颁诏同穿。
        _cli_write_gate(session)
        print("《明末力挽狂澜》文字 MVP")
        print(f"你是刚刚登基的崇祯。每回合一个{TURN_UNIT}：看奏报、召见大臣、下圣旨、听回奏。")
        print(f"手动玩法：quit/退朝 = 结束本{TURN_UNIT}进入下一{TURN_UNIT}；exit/退出游戏 = 退出程序。")
        if (llm_config.advanced_model or "").strip():
            adv_url = (llm_config.advanced_base_url or "").strip() or base_url
            adv_hint = f"（推演/打分用 {llm_config.advanced_model} @ {adv_url}）"
        else:
            adv_hint = ""
        print(f"当前 LLM：{model} @ {base_url}{adv_hint}")
        print(f"数据库：{db_path}\n")
        while True:
            play_turn(session)
            if session.state.ended:
                from ming_sim.context import ENDING_LABELS
                label = ENDING_LABELS.get(session.state.ending_status, "结局")
                print(f"\n══════════ 结局·{label} ══════════")
                ending = session.db.get_ending_summary()
                if ending and ending.get("summary"):
                    print(ending["summary"])
                print("\n（本局已终结。）")
                input("\n按回车退出游戏：")
                break
            raw = input(f"\n按回车继续下一{TURN_UNIT}，或输入 exit 退出游戏：").strip()
            if raw.lower() in EXIT_COMMANDS:
                break
    except ExitGame:
        print("\n退出游戏。")
    except LLMUnavailable as error:
        print(f"\n{error}")
    except LLMContractError as error:
        print(f"\n程序中止：{error}")
    except KeyboardInterrupt:
        print("\n退出游戏。")
    finally:
        if session is not None:
            session.close()
        print_token_summary()
