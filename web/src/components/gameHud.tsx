import { yearMonthLabel } from "../settlementPresentation";
import { BudgetHover, CommandSlot, HUD_BG, HUD_SLOTS, LegacyBar } from "./hud";
import { GrandMap } from "./map";
import { SituationPanel } from "./situation";
import { scoreTone } from "../format";
import type { GameState, MapNode, ModalName } from "../types";

// 主界面 HUD：整图底图 + 地图/局势/顶栏五匾/右侧部院导航/底部五命令，全部按坑位绝对定位。
export function GameHud({
  stageRef,
  ready,
  state,
  mapNodes,
  mapSelectedId,
  onSelectMapNode,
  activeDrawerKey,
  navHandlers,
  secretOrderActiveCount,
  onOpenModal,
}: {
  stageRef: (el: HTMLDivElement | null) => void;
  ready: boolean;
  state: GameState;
  mapNodes: MapNode[];
  mapSelectedId: string;
  onSelectMapNode: (nodeId: string) => void;
  activeDrawerKey: string;
  navHandlers: Record<string, () => void>;
  secretOrderActiveCount: number;
  onOpenModal: (modal: ModalName) => void;
}) {
  return (
    <div className="hud2-stage" ref={stageRef}>
      <img className="hud2-bg" src={HUD_BG} alt="" />

      {/* 地图：平面矩形，盖在底图中央素绢图框上 */}
      {ready ? (
        <div className="hud2-map-quad" style={{
          position: "absolute",
          left: `${HUD_SLOTS.地图框.left}%`, top: `${HUD_SLOTS.地图框.top}%`,
          width: `${HUD_SLOTS.地图框.width}%`, height: `${HUD_SLOTS.地图框.height}%`,
        }}>
          <GrandMap nodes={mapNodes} selectedId={mapSelectedId} onSelect={onSelectMapNode} />
        </div>
      ) : null}

      {/* 地图暖黄昏调+暗角：盖在交互地图上的纯装饰层（夜·烛基调），不吃点击 */}
      {ready ? (
        <div className="hud2-map-grade-frame" style={{
          position: "absolute",
          left: `${HUD_SLOTS.地图框.left}%`, top: `${HUD_SLOTS.地图框.top}%`,
          width: `${HUD_SLOTS.地图框.width}%`, height: `${HUD_SLOTS.地图框.height}%`,
        }}>
          <div className="hud2-map-grade" />
        </div>
      ) : null}

      {/* 局势进度：左挂轴平面矩形 */}
      {ready ? (
        <div className="hud2-issue-quad" style={{
          position: "absolute",
          left: `${HUD_SLOTS.局势框.left}%`, top: `${HUD_SLOTS.局势框.top}%`,
          width: `${HUD_SLOTS.局势框.width}%`, height: `${HUD_SLOTS.局势框.height}%`,
        }}>
          <SituationPanel
            issues={state.issues}
            closedIssues={state.closed_this_turn || []}
            hasLegacies={(state.legacies || []).length > 0}
          />
        </div>
      ) : null}

      {/* 顶栏：年月 + 国库/内库 + 民心/皇威，各按坑位绝对定位 */}
      <button className="hud2-slot hud2-year" style={HUD_SLOTS.顶栏.年月}
        onClick={() => onOpenModal("state")}>
        <span className="hud2-block">
          <span className="hud2-lab">大明</span>
          <span className="hud2-val">{yearMonthLabel(state.turn)}</span>
        </span>
      </button>
      <div className="hud2-slot" style={HUD_SLOTS.顶栏.国库}>
        <BudgetHover accountName="国库" budget={state.budget["国库"]} />
      </div>
      <div className="hud2-slot" style={HUD_SLOTS.顶栏.内库}>
        <BudgetHover accountName="内库" budget={state.budget["内库"]} />
      </div>
      <div className="hud2-slot hud2-metric-pair" style={HUD_SLOTS.顶栏.民心}>
        <span className={`hud2-metric-one ${scoreTone(state.metrics["民心"], false)}`}>
          <span className="hud2-lab">民心</span><span className="hud2-val">{state.metrics["民心"]}</span>
        </span>
        <span className={`hud2-metric-one ${scoreTone(state.metrics["皇威"], false)}`}>
          <span className="hud2-lab">皇威</span><span className="hud2-val">{state.metrics["皇威"]}</span>
        </span>
      </div>
      <div className="hud2-slot hud2-legacy-slot" style={HUD_SLOTS.顶栏.皇威}>
        <LegacyBar legacies={state.legacies} />
      </div>
      <button className="hud2-menu-btn"
        title="游戏菜单" aria-label="游戏菜单" onClick={() => onOpenModal("menu")}>
        <span className="hud2-val">菜单</span>
      </button>

      {/* 右侧竖排部院导航 */}
      {([
        ["政", "court", "朝堂·召见大臣"],
        ["吏", "appointment", "官员任免"],
        ["省", "region", "省份列表"],
        ["兵", "army", "军队列表"],
        ["户", "economy", "经济面板"],
        ["工", "building", "建筑列表"],
        ["礼", "court", "礼部"],
        ["后", "harem", "后宫"],
      ] as const).map(([label, key, title], idx) => {
        const slotKey = (["政","吏部","省份","兵部","户部","工部","礼部","后宫"] as const)[idx];
        return (
          <button key={slotKey} className={`hud2-slot hud2-nav${activeDrawerKey === key ? " active" : ""}`}
            style={HUD_SLOTS.导航[slotKey]} title={title} aria-label={title}
            onClick={navHandlers[key]}>
            {label}
          </button>
        );
      })}

      {/* 底部 5 命令物件（扣图填进木牌） */}
      <CommandSlot slotKey="奏疏" img="奏疏" badge={state.events.length}
        caption="奏疏" sub={`${state.events.length} 件待览`} onClick={() => onOpenModal("state")} />
      <CommandSlot slotKey="邸报" img="邸报"
        caption="起居注" sub="历次召对记录" onClick={() => onOpenModal("audience_archive")} />
      <CommandSlot slotKey="密令" img="密令"
        badge={secretOrderActiveCount}
        caption="密令" sub="进行中密令" onClick={() => onOpenModal("secret_orders")} />
      <CommandSlot slotKey="史册" img="史册"
        caption="史册" sub="历代奏报/诏书" onClick={() => onOpenModal("history")} />
      <CommandSlot slotKey="拟诏" img="拟诏" badge={state.directives.length}
        caption="拟诏/结束回合" sub={state.directives.length ? `${state.directives.length} 道` : "本回合"}
        onClick={() => onOpenModal("edict")} />
    </div>
  );
}
