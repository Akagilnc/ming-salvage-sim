"""CLI 终端层：input()/print() 驱动，调 GameSession 跑回合。L9。

play_turn 状态机搬入此处；GameSession 持游戏状态，terminal 只做 I/O。
拟旨候选先进 pending_actions 闸门；皇帝可在对话里准/驳，不回则颁诏 checkpoint 默认同意。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

from ming_sim.constants import (
    COURT_BREAK_COMMANDS,
    EXIT_COMMANDS,
    TURN_UNIT,
)
from ming_sim.assets import wrap
from ming_sim.exceptions import ExitGame, LLMContractError, LLMUnavailable, SettlementAbort
from ming_sim.models import API_DEFAULT_TIMEOUT_SECONDS, Character, GameState
from ming_sim.session import (
    GameSession,
    TurnPhase,
    _is_summonable_court_minister,
)

logger = logging.getLogger(__name__)

_STATUS_LABEL = {
    "active": "在朝",
    "dismissed": "已罢官",
    "imprisoned": "下狱",
    "exiled": "流戍",
    "retired": "致仕",
    "dead": "亡",
}

# 旧手拟确认/驳回词表已随手拟入口清退（#1902 S1）。


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
        and session.db.get_character_status(name)[0] != "offstage"
    ]
    print("\n可召见大臣：")
    for idx, name in enumerate(names, 1):
        c = characters[name]
        status, _ = session.db.get_character_status(name)
        tag = "" if status == "active" else f"  [{_STATUS_LABEL.get(status, status)}]"
        print(f"{idx}. {c.name}（{c.office}，{c.faction}）{tag}")
    while True:
        raw = input("召见谁？输入编号或姓名，quit 退朝审阅诏书，exit 退出游戏：").strip()
        if not raw:
            print("请输入编号或姓名。")
            continue
        lowered = raw.lower()
        if lowered in EXIT_COMMANDS:
            raise ExitGame
        if lowered in COURT_BREAK_COMMANDS:
            return None
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
                candidate = session.summon_character(raw)
            except ValueError:
                print("请输入有效编号或姓名。")
                continue
        # #1902：菜单只解析人选并生成口令加速器；准入／入殿账交共同场景生命周期，
        # 入口不另 consume_audience_admission 或改写源问话。
        return candidate


def _handle_court_command(text: str) -> Optional[str]:
    """CLI 导航口令：只认退朝／退出游戏。

    #1902：退人口令（退下/done 等）不在入口自持语义或落在场账；原样交共同
    begin_audience_chat_turn→scene_chat。返回 'court_break' | None。
    """
    raw = text.strip()
    lowered = raw.lower()
    if lowered in EXIT_COMMANDS:
        raise ExitGame
    if lowered in COURT_BREAK_COMMANDS or raw in COURT_BREAK_COMMANDS:
        return "court_break"
    return None


def _print_interrupted_reply_retry_hint(session: GameSession) -> None:
    """#505：CLI 系统层恢复提示——崩溃后问话保留，可输入「重试回话」重新生成。

    取数走会话层 ``pending_audience_reply_retries``（#1902 F2）：建轮归「殿上」，
    按大臣名反查中断轮永远查不到——入口不自己拼查询。
    """
    retries = session.pending_audience_reply_retries()
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

    #1902 T4：生命周期走 ``GameSession.execute_interrupted_reply_retry``（含收夜调度）；
    本入口只取待重试项与呈现回话。

    成功且 court_action 为 court_break 时返回 typed 'court_break'，供 minister_chat
    退出对话进入 play_turn 审阅；收夜失败仍返回 None，留在原对话。
    """
    from ming_sim.audience_night import SCENE_CHAT_SPEAKER

    retries = session.pending_audience_reply_retries()
    if not retries:
        print(f"{minister_name}没有待重试的中断回话。\n")
        return None
    target = retries[-1]
    chat_turn_id = int(target["chat_turn_id"])
    question = str(target["question"])
    # 回话挂回原问话的那位大臣（CLI 召对语义），不是建轮的殿上。
    message_speaker = str(target.get("message_speaker") or "") or minister_name
    try:
        retry_outcome = session.execute_interrupted_reply_retry(
            chat_turn_id=chat_turn_id,
            question=question,
            message_speaker=message_speaker,
            accepted_turn=int(target.get("turn") or session.state.turn),
            user_message_id=int(target.get("user_message_id") or 0),
            scene_minister_name=SCENE_CHAT_SPEAKER,
            schedule_translation=True,
            schedule_close_night=True,
            write_gate=_cli_write_gate(session),
            close_night_write_gate=_cli_write_gate(session),
        )
    except Exception as exc:
        print(f"重试回话失败：{exc}\n")
        return None
    if retry_outcome is None:
        print(f"{minister_name}上一轮回奏仍在进行，请稍候再问。\n")
        return None
    _turn, result, _mid = retry_outcome
    print(f"\n{message_speaker}：{wrap(str(getattr(result, 'answer', '') or ''))}\n")
    if str(getattr(result, "court_action", "") or "") == "court_break":
        return "court_break"
    return None


def _cli_write_gate(session: GameSession):
    """CLI 唯一 write gate：与 resolve_turn 收夜/过月屏障同穿（#1353 队列）。

    GameSession 构造已 eager 装队列；此处只解析既有 ledger，不二次安装、不宽吞重挂，
    禁第二锁名分叉（trail 与颁诏 auto_close 必须同闸）。
    """
    from ming_sim.session_write_queue import get_session_write_queue
    return get_session_write_queue(session).write_gate


def minister_chat(session: GameSession, character: Character, *, selected: bool = False) -> str:
    """与一位大臣对话。返回 'court_break'。

    #1902：召见／退人口令原样走共同建轮／scene_chat；入口不再自解析后缀召见、
    另准入、自持退人目标或直接落告退账。导航只留退朝／退出游戏。
    """
    other = next((n for n in session.content.characters if n != character.name), character.name)
    print(f"\n当前选择：{character.name}。可持续问话；“传{other}来”换人，quit 退朝审阅诏书，exit 退出游戏。")
    print("提示：陛下示意采纳后（如“准奏”），大臣会拟旨呈陛下核定。\n")
    # #505：入殿时显眼提示回话中断恢复入口（与 web ChatModal 同语义）。
    # #1353：欠账抽取无玩家手动补写面——过月内部 drain 唯一处理路。
    _print_interrupted_reply_retry_hint(session)
    from ming_sim.audience_night import get_open_night, present_names_at
    night = get_open_night(session.db) if selected else None
    # 菜单加速器：与 Web summonMinister 同形，只在目标尚未在场时生成「宣 X」交共核。
    pending_xuan = selected and (
        night is None or character.name not in present_names_at(session.db, int(night["id"]))
    )
    while True:
        question = f"宣{character.name}" if pending_xuan else input("朕问：").strip()
        pending_xuan = False
        if not question:
            print("可继续问话；quit 退朝审阅诏书。")
            continue
        # #505 系统层恢复命令（非皇帝内容选项）。禁抽取手动补写平行面（#1353）。
        low_q = question.lower().strip()
        if low_q in {"重试回话", "retry reply", "retry_reply"}:
            retry_action = _retry_interrupted_reply_cli(session, character.name)
            if retry_action == "court_break":
                return "court_break"
            continue
        cmd = _handle_court_command(question)
        if cmd == "court_break":
            # #526/#1842：高置信收夜口令 → 前台先返回；队列随后 FIFO 转译 join→封夜。
            # 后台失败留痕、夜可恢复；不假成功静默吞错（ADR 0005）。
            # #1902 N4：GameSession 恒有收夜调度；删 auto_close / 缺方法降级替身。
            session.schedule_close_night_after_chat_if_needed(
                "court_break", write_gate=_cli_write_gate(session),
            )
            return "court_break"
        # 非导航口令（含召见／退人原句）→ 场景对话，并持久记录对话轮。
        # #1902：建轮/快照/问话落库/回滚终态全走会话层同一生命周期（与 Web 共核），
        # 入口只留输入采集与呈现。薄替身分支已删：真 GameDB 恒有这套生命周期，
        # 为只替 LLM 缝的壳另留一条无轮路径，等于给测试维护第二套生产生命周期。
        chat_turn = GameSession.begin_audience_chat_turn(
            session, question,
            # 建轮归「殿上」（与 Web 同、殿上历史读得到）；问话/回话挂大臣名
            # （与修前 CLI 语义同）。模型会话身份／前像水位由会话核按真实夜提供。
            message_speaker=character.name,
        )
        result = None
        translation_dispatched = False
        try:
            # #1842：殿上走 scene_chat；显式密令仍走 session.chat（与 Web 同核）。
            # 殿上不派旧判官/尾随抽取——转译一次承接。
            result = session.scene_chat(
                question,
                chat_turn_id=int(chat_turn.chat_turn_id),
                minister_name="殿上",
            )
            GameSession.complete_audience_chat_turn(
                session, chat_turn, character.name, result.answer, result,
            )
            translation_dispatched = True
        except BaseException as original_error:
            try:
                GameSession.fail_audience_chat_turn(
                    session, chat_turn,
                    replied=result is not None, error=original_error,
                    translation_dispatched=translation_dispatched,
                    court_action=str(getattr(result, "court_action", "") or ""),
                )
            except BaseException as cleanup_error:
                raise original_error from cleanup_error
            raise
        print(wrap(result.answer))
        print()
        # #1902 T6：旧 result 字段（拟旨/铨选/密令 landing 等）无场景产者，死消费者已清。
        if result.court_action == "court_break":
            return "court_break"


def _cli_save(session: GameSession, name: str) -> None:
    """CLI 存档：经会话层共享核落 saves/<name>.db（与 Web 同一条），入口只呈现。

    名非法由共享核判（``paths.UnsafeSaveNameError``）；CLI 形态是打印一行提示，
    不像 Web 那样抛 400——玩家在这里只是输错了一个名字，留在菜单里改就是了。
    """
    from ming_sim.paths import UnsafeSaveNameError

    label = (name or "").strip()
    if not label:
        label = input("存档名> ").strip()
    if not label:
        print("未给存档名，已取消。\n")
        return
    try:
        saved = session.save_to(label)
    except UnsafeSaveNameError as err:
        print(f"{err}\n")
        return
    print(f"已存档：{saved['name']}\n")


class _CliRuntime:
    """CLI 换库运行时容器（#1902 F2）。

    共享核 ``save_slots.replace_database`` 认的是「持有 session / db_path 的宿主
    包装」——Web 侧是 ``WebGame``，CLI 侧是它。读档成功后本容器与内层会话都被换成
    读档后的新会话，故 :func:`_cli_load` 返回时要把新会话交还给调用方的持有变量。
    """

    def __init__(self, session: GameSession) -> None:
        self.session = session
        # GameSession 不自持 db_path 字段（换库目标就是它）；从主库连接反查真实路径。
        self.db_path = str(session.db.path)

    @property
    def db(self):
        """共享核读 ``runtime.db`` 做备份——活会话换了，主库连接也跟着换。"""
        return self.session.db


class _CliSaveSlotHost:
    """#1902 F2：CLI 侧换库宿主能力（与 Web 共用 ``save_slots`` 编排）。

    CLI 没有 Web 的结算准入在飞计数（召对/过月同步跑），故该计数恒 0；锁序与
    Web 相同（write_gate → entry_lock），换库同样经会话写队列的 seal/barrier。
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()

    def write_queue(self, runtime):
        from ming_sim.session_write_queue import get_session_write_queue

        return get_session_write_queue(runtime)

    def entry_lock(self, runtime):
        return self.lock

    def settlement_inflight(self, runtime) -> int:
        return 0

    def rebuild(self, runtime, llm_config) -> None:
        runtime.session = _cli_rebuild_session(runtime, llm_config)

    def dispose_residual(self, runtime, residual) -> bool:
        if residual is None:
            return True
        try:
            residual.close()
        except Exception:
            logger.exception("CLI dispose rebuild residual close failed")
            return False
        if getattr(runtime, "_rebuild_residual_runtime", None) is residual:
            runtime._rebuild_residual_runtime = None
        return True

    def busy_detail(self) -> str:
        return "本夜收夜/过月进行中，暂不能换档。"


def _cli_reconcile_crashed_turns(session: GameSession) -> None:
    """CLI 适配：转调会话共核启动恢复（对账 + 转译补跑，#1902 T4）。

    CLI 无 Web 票据／后台线程，同步跑共核即可；写闸取既有 CLI 队列闸。
    """
    session.reconcile_crashed_audience_turns()
    from ming_sim.session_write_queue import get_session_write_queue
    q = get_session_write_queue(session)
    session.run_startup_translation_catch_up(
        write_gate=q.write_gate, write_queue=q,
    )


def _cli_rebuild_session(runtime: "_CliRuntime", llm_config) -> GameSession:
    """发布换库候选：共同生命周期在 save_slots；此处只映射同步补跑与发布。

    候选完整初始化且 prepare 成功后才发布（#1902 J1）；活槽 ``runtime.session``
    在此期间仍指着已被共享核关闭的旧会话。失败关闭与 residual 交接走共核
    （见 ``open_candidate_session``），不得挂回正持 barrier 的旧队列。
    """
    from ming_sim.content import GameContent
    from ming_sim.save_slots import open_candidate_session
    from ming_sim.session_write_queue import get_session_write_queue

    def _prepare_cli_startup(candidate: GameSession) -> None:
        # 发布前同步补跑：仍在共核失败关闭保护区内。
        q = get_session_write_queue(candidate)
        candidate.run_startup_translation_catch_up(
            write_gate=q.write_gate, write_queue=q,
        )

    try:
        candidate, _ = open_candidate_session(
            runtime.db_path,
            llm_config,
            content=GameContent.load(),
            prepare=_prepare_cli_startup,
        )
    except Exception as exc:
        residual = getattr(exc, "residual_session", None)
        if residual is not None:
            runtime._rebuild_residual_runtime = residual
        raise
    runtime.session = candidate
    return candidate


def _cli_load(session: GameSession, name: str) -> Optional[GameSession]:
    """CLI 读档：热替换主库（共享核 ``save_slots.replace_database``，与 Web 同一条）。

    返回**调用方必须改持有的会话**：换库成功时是读档后的新会话；换库失败且共享核
    已关闭旧会话、用还原后的库重建出新会话时，也返回那份新会话（``#1902 J1``：
    玩家若继续持已关闭的旧菜单会话，下一次写库就是
    ``Cannot operate on a closed database``）。
    返回 None 只在活会话根本没被换掉时：空名、非法名、无此档，或换库在关闭旧会话
    之前失败。读档成败由本函数自己打印，入口只管换引用。
    """
    from ming_sim.paths import UnsafeSaveNameError, save_slot_path
    from ming_sim.save_slots import copy_sqlite_file, replace_database

    label = (name or "").strip()
    if not label:
        label = input("读档名> ").strip()
    if not label:
        print("未给读档名，已取消。\n")
        return None
    try:
        source = save_slot_path(label)
    except UnsafeSaveNameError as err:
        print(f"{err}\n")
        return None
    if not os.path.isfile(source):
        print(f"没有存档「{label}」。\n")
        return None

    runtime = _CliRuntime(session)

    # #1902：覆盖拷贝走共享核唯一实现（此前此处与 WebGame.load_save 各带一份
    # 逐行相同的 sqlite backup 闭包——两份已删）。
    try:
        replace_database(
            runtime, _CliSaveSlotHost(),
            lambda: copy_sqlite_file(source, runtime.db_path),
        )
    except Exception as err:
        # 失败诚实宪法：旧会话一旦被共享核关闭，就必须把还原后重建的新会话交还
        # 持有方（也不假装读档成功）。还原重建本身失败、没有活局可交时如实退出。
        # 换库在关闭旧会话之前失败时，runtime.session 仍是原来那个活会话——
        # 留在菜单里，不把它报成「已换档」。
        restored = runtime.session
        from ming_sim.save_slots import runtime_restorable

        if not runtime_restorable(restored):
            raise SystemExit(f"读档失败且原局无法恢复，请重启游戏：{err}") from err
        if restored is session:
            print(f"\n读档失败：{err}\n")
            return None
        print(f"\n读档失败，已恢复原局：{err}\n")
        return restored
    loaded = runtime.session
    print(f"\n已读档：{label}（第 {int(loaded.state.turn)}{TURN_UNIT}）\n")
    return loaded


def review_directives(session: GameSession):
    """诏书草案审阅界面。返回 'issue' | 'back' | 'skip'，或读档后的新 GameSession。

    #1902 M2：读档成功直接以返回值交还新会话，不经共核私有交接槽。
    旧回合的相位与候选全部作废。
    """
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
            print("（暂无指令。back 继续召见，或 issue 结束本回合。）")
        # #1902 / #1812 待拍第 6 项：拟诏台手写新旨入口退役，CLI 只审阅与颁布；
        # 旨意只从召对来（#1772）。旧草稿仍可见、可删（#1826 承接草稿去向）。
        # #1902 F2：存读档也接共享核（与 Web 同一条），入口只取名与呈现。
        print("\n操作：issue 结束回合 | back 继续召见 | del N 删 | save 名 存档 | load 名 读档 | exit 退出")
        raw = input("诏书草案> ").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered in EXIT_COMMANDS:
            raise ExitGame
        if lowered in {"save", "存档"} or lowered.startswith("save "):
            _cli_save(session, raw.split(maxsplit=1)[1] if " " in raw else "")
            continue
        if lowered in {"load", "读档"} or lowered.startswith("load "):
            label = raw.split(maxsplit=1)[1] if " " in raw else ""
            loaded = _cli_load(session, label)
            if loaded is not None:
                # 活会话换了：直接返回新会话，由 play_turn 交还 run_cli。
                return loaded
            continue
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
            parts = raw.split(maxsplit=1)
            verb = parts[0].lower()
            if len(parts) == 2 and parts[1].lstrip("#").isdigit():
                target_id = int(parts[1].lstrip("#"))
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


def _option_label(option: object) -> str:
    """案头 option → 一行可读标签（label + hint），非 dict 回字符串本身。"""
    if not isinstance(option, dict):
        return str(option or "")
    label = str(option.get("label") or "")
    hint = str(option.get("hint") or "").strip()
    return f"{label}（{hint}）" if hint else label


def _adjudicate_cli_decisions(session: GameSession, result) -> str:
    """#1902：CLI 批红等皇帝亲裁，不代选第一项（#1812 待拍第 9 项）。

    与 Web 同走 ``session.submit_hitl_choices`` 唯一编排（注入既有 `_cli_write_gate`）；
    choice 投影走 ``rescript_actions.project_hitl_option`` 唯一真源——CLI 只读案头、
    只接皇帝的输入，案头规则、键绑定与校验全在 session 核内，不在入口复制。
    """
    if result is None or not result.awaiting:
        return "" if result is None else result.report
    from ming_sim.rescript_actions import project_hitl_option

    print("\n【月末重大抉择】（逐案亲裁）")
    # result.decisions 已是合并 desk；若空则回读 session.pending_decisions
    decisions = list(result.decisions or []) or list(session.pending_decisions())
    choices = []
    for decision in decisions:
        title = str(decision.get("title") or "").strip() or "（无题）"
        context = str(decision.get("context") or "").strip()
        print(f"\n· {wrap(title)}")
        if context:
            print(f"  {wrap(context)}")
        raw_options = decision.get("options")
        options = list(raw_options) if isinstance(raw_options, (list, tuple)) else []
        for idx, option in enumerate(options, 1):
            print(f"  {idx}. {_option_label(option)}")
        key = str(decision.get("decision_key") or "").strip()
        # #1902 r2：回车留中只对核内真会机械 hold 的急务成立（validate_all 的
        # rescript_draft 缺 action → hold）。普通 decision 与 dossier 批红行核内
        # 要求实选项（"decision 选项不在当前 options" / "批红选择必须是本案提供的
        # 强颁、收回或留中选项"），入口不得代造一条核不认的留中路——那会让整批被拒。
        holdable = str(decision.get("kind") or "") == "rescript_draft"
        hint = "回车=不另批，此件留中" if holdable else "须择定本案一条，或朱笔批语"
        while True:
            raw = input(f"  亲裁：输入编号择定该条，或径书朱笔批语（{hint}）：").strip()
            if not raw:
                if holdable:
                    choices.append({"decision_key": key} if key else {})
                    break
                print("  此案须择定一条（不另批请择案上标注留中的那条）。")
                continue
            if raw.isdigit():
                if 1 <= int(raw) <= len(options):
                    choices.append(project_hitl_option(decision, int(raw) - 1))
                    break
                print("  请输入本案列出的编号。")
                continue
            # #1902：请旨允许只交亲笔批语（核内 rescript_actions.validate_all 同一条
            # note-only 通道，Web decisionModal 同样透传）。入口不判资格、不改写成
            # 某条票拟——收不收由共享核一句话判定，入口禁复制批红规则。
            choices.append({"decision_key": key, "note": raw} if key else {"note": raw})
            break
    return session.submit_hitl_choices(choices, write_gate=_cli_write_gate(session))


def play_turn(session: GameSession) -> Optional[GameSession]:
    """一回合 CLI 驱动：召见 → 审阅 → 颁诏推演。

    #1902 F2：读档成功时返回**读档后的新会话**（活会话已换，旧回合上下文作废），
    调用方 ``run_cli`` 据此换掉自己持有的会话；正常打完一回合返回 None。
    """
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

    while True:
        if session.current_phase() == TurnPhase.SUMMONING:
            character = choose_minister(session)
            if character is None:
                action = review_directives(session)
            else:
                minister_chat(session, character, selected=True)
                # court_break → 审阅（召见／退人已交共同场景生命周期）
                action = review_directives(session)
        else:
            action = review_directives(session)

        if action == "back":
            continue
        if isinstance(action, GameSession):
            # 读档已热替换主库并重建会话 → 本回合交互上下文全部作废，把新会话交还
            # run_cli 后退出（它会重印引导、进入新局的第一回合）。
            return action
        if action == "skip":
            turn_before = int(session.state.turn)
            try:
                # #1353 fold-in r8：颁诏/退朝前挂唯一 write_gate，使 resolve 收夜 drain 同流。
                _cli_write_gate(session)
                result = session.advance_without_decree()
                report = _adjudicate_cli_decisions(session, result)
            except (ValueError, SettlementAbort, LLMUnavailable, LLMContractError) as error:
                # 跳过与颁诏共享可恢复结算语义：失败后留在本回合循环，允许重试。
                # #1353 fold-in r8：统一重试耗尽的 LLMUnavailable 不退出 CLI。
                # #1700：空 simulator 的 LLMContractError 同形，不落到 run_cli「程序中止」。
                # #1853 J5：真异常经本 except 原样上抛呈现；终态业务拒收不再另造失败载荷。
                print(f"\n{error}")
                continue
            if result is not None:
                print(report)
                if getattr(session.state, "ended", False):
                    return
                if getattr(result, "advanced", False) or int(session.state.turn) > turn_before:
                    session.end_turn()
                    return
            else:
                return
            continue
        if action == "issue":
            turn_before = int(session.state.turn)
            try:
                # #1353 fold-in r8：颁诏/退朝前挂唯一 write_gate，使 resolve 收夜 drain 同流。
                _cli_write_gate(session)
                result = session.resolve_turn()
                report = _adjudicate_cli_decisions(session, result)
            except (ValueError, SettlementAbort, LLMUnavailable, LLMContractError) as error:
                # 恢复态守门 / 结算中止 / 欠账耗尽（#1353 r8）/ 契约失败（#1700）：打印指引后留在
                # 本回合交互循环——玩家重按 issue/skip 即重试整段，CLI 不退出。
                # #1853 J5：真异常经本 except 原样上抛呈现；终态业务拒收不再另造失败载荷。
                print(f"\n{error}")
                continue
            if result is not None:
                print(report)
                if getattr(session.state, "ended", False):
                    return
                if getattr(result, "advanced", False) or int(session.state.turn) > turn_before:
                    session.end_turn()
                    return
            else:
                return
            continue


def _printed_ending_summary(session: GameSession) -> str:
    """终局总评在机械尾写队列票落地后读取。"""
    from ming_sim.session_write_queue import get_session_write_queue

    get_session_write_queue(session).wait_idle()
    ending = session.db.get_ending_summary()
    if ending and ending.get("summary"):
        return str(ending["summary"])
    return ""


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
    from ming_sim.llm_config import (
        llm_config_from_runtime, load_runtime_llm, resolve_api_key,
    )
    from ming_sim.exceptions import LLMUnavailable, LLMContractError
    from ming_sim.token_stats import print_token_summary

    session: Optional[GameSession] = None
    try:
        # #1902：与 Web 建局同一条投影路（运行档 = 唯一运行配置），CLI 入口不再
        # 只认 API 通道——运行档选了 CLI 宿主就直接起局，不再索要 API key。
        # F1：入参在此只是**回落值**；地址/模型/key/超时/思考档一律先取运行档
        # （落差在 llm_config_from_runtime 一处决定），故同一份档经 Web 与 CLI
        # 建局得到同一执行事实，不再是「CLI 跑默认地址+默认模型+API 超时」。
        runtime = load_runtime_llm()
        entry_args = {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "timeout_seconds": timeout_seconds,
            "thinking_level": "",
            "advanced_model": advanced_model,
            "advanced_base_url": advanced_base_url,
            "advanced_api_key": advanced_api_key,
            "advanced_thinking_level": "",
        }
        llm_config = llm_config_from_runtime(runtime, **entry_args)
        if llm_config.channel != "cli" and not llm_config.api_key:
            # API 通道且确无真实 key：向人要一次（唯一索要缝 llm_config.resolve_api_key）。
            llm_config = llm_config_from_runtime(
                runtime, **{**entry_args, "api_key": resolve_api_key(api_key)},
            )
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        session = GameSession(db_path, llm_config, start_ym=start_ym)
        # #1353 fold-in r8：建 session 即挂唯一 write_gate，trail/收夜/颁诏同穿。
        _cli_write_gate(session)
        # #1902 J2：重开对账（起手一次；读档重建走 _cli_rebuild_session 同一句）。
        _cli_reconcile_crashed_turns(session)
        print("《明末力挽狂澜》文字 MVP")
        print(f"你是刚刚登基的崇祯。每回合一个{TURN_UNIT}：看奏报、召见大臣、下圣旨、听回奏。")
        print(f"手动玩法：quit/退朝 = 结束本{TURN_UNIT}进入下一{TURN_UNIT}；exit/退出游戏 = 退出程序。")
        # #1902：横幅报实际生效的通道（运行档投影结果），不再拿入参 base_url/model 冒充。
        if llm_config.channel == "cli":
            current_llm = f"CLI 宿主 {llm_config.cli_runner}（{llm_config.cli_model}）"
        else:
            current_llm = f"{llm_config.model} @ {llm_config.base_url}"
        if (llm_config.advanced_model or "").strip():
            adv_url = (llm_config.advanced_base_url or "").strip() or llm_config.base_url
            adv_hint = f"（推演/打分用 {llm_config.advanced_model} @ {adv_url}）"
        else:
            adv_hint = ""
        print(f"当前 LLM：{current_llm}{adv_hint}")
        print(f"数据库：{db_path}\n")
        while True:
            turn_start = int(session.state.turn)
            # #1902 F2：读档成功时 play_turn 交还读档后的新会话——活会话换了，
            # 换掉本循环持有的引用（旧的已由读档路径关闭），继续玩新局面。
            loaded = play_turn(session)
            if loaded is not None:
                session = loaded
                continue
            if session.state.ended:
                from ming_sim.context import ENDING_LABELS
                label = ENDING_LABELS.get(session.state.ending_status, "结局")
                print(f"\n══════════ 结局·{label} ══════════")
                summary = _printed_ending_summary(session)
                if summary:
                    print(summary)
                print("\n（本局已终结。）")
                input("\n按回车退出游戏：")
                break
            if int(session.state.turn) > turn_start:
                prompt = f"\n按回车继续下一{TURN_UNIT}，或输入 exit 退出游戏："
            else:
                prompt = f"\n按回车继续本{TURN_UNIT}，或输入 exit 退出游戏："
            raw = input(prompt).strip()
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
        if session is not None and int(getattr(session, "_close_epoch", 0) or 0) == 0:
            # #1842：正常 CLI 退出走共享 drain 核心——转译 worker 终态后才关原库；
            # 禁直接 session.close；禁伪装 Web runtime / 反向耦合 web_app。
            # 读档失败且共享核已经关掉旧会话时 epoch 已增，再 drain 会在已关闭的
            # 连接上二次 close。
            from ming_sim.session_write_queue import (
                drain_and_close_session,
                get_session_write_queue,
            )

            try:
                drain_and_close_session(session)
            except Exception:
                # Shared core does not auto-unseal; CLI always attempts unseal
                # so a failed exit path remains writable for diagnostics.
                try:
                    get_session_write_queue(session).unseal()
                except Exception:
                    logger.exception(
                        "CLI exit: unseal after drain failure also failed"
                    )
                raise
        print_token_summary()
