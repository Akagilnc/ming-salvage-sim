import {
  isFaceReachable,
  isSettlementDisplay,
  settlementFaceAccess,
  wangSettlementSlipVisible,
  yearMonthLabel,
  SETTLEMENT_CLOSED_REASON,
  WANG_SETTLEMENT_SLIP,
} from "../settlementPresentation";
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
  onClosedFaceAttempt,
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
  /** 关闭组入口被点时的戏内提示（可选）。 */
  onClosedFaceAttempt?: (reason: string) => void;
}) {
  // #1236：全部门控唯一谓词 = 状态口 settlement_display（禁 busy/phase 充真源）。
  const settlementDisplay = isSettlementDisplay(state.turn);
  const noticeClosed = () => onClosedFaceAttempt?.(SETTLEMENT_CLOSED_REASON);

  const gatedNav = (faceKey: "court_roster" | "appointment_roster" | "harem_roster" | "region" | "army" | "economy" | "building", navKey: string) => {
    if (!isFaceReachable(faceKey, settlementDisplay)) {
      noticeClosed();
      return;
    }
    navHandlers[navKey]?.();
  };

  const gatedModal = (faceKey: "memorials" | "audience_archive" | "secret_orders" | "history" | "edict" | "menu", modal: ModalName) => {
    if (!isFaceReachable(faceKey, settlementDisplay)) {
      noticeClosed();
      return;
    }
    onOpenModal(modal);
  };

  const secretBadge = isFaceReachable("secret_orders", settlementDisplay) ? secretOrderActiveCount : 0;
  // situation（关闭）与 closed_issues（只读）分 key：核账期藏半程议题，保留上月已结入口。
  const showSituation = isFaceReachable("situation", settlementDisplay);
  const showClosedIssues = isFaceReachable("closed_issues", settlementDisplay);
  const showIssueQuad = showSituation || showClosedIssues;
  const mapSelectable = isFaceReachable("node_intel", settlementDisplay);
  const showWangSlip = wangSettlementSlipVisible(settlementDisplay);

  return (
    <div className="hud2-stage" ref={stageRef}>
      <img className="hud2-bg" src={HUD_BG} alt="" />

      {/* 地图：平面矩形，盖在底图中央素绢图框上。底图装饰可留；点选开详吃 node_intel 门。 */}
      {ready ? (
        <div className="hud2-map-quad" style={{
          position: "absolute",
          left: `${HUD_SLOTS.地图框.left}%`, top: `${HUD_SLOTS.地图框.top}%`,
          width: `${HUD_SLOTS.地图框.width}%`, height: `${HUD_SLOTS.地图框.height}%`,
        }}>
          <GrandMap
            nodes={mapNodes}
            selectedId={mapSelectedId}
            onSelect={(id) => {
              if (!mapSelectable) { noticeClosed(); return; }
              onSelectMapNode(id);
            }}
          />
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

      {/* 局势框：situation 关闭 ≠ closed_issues 关死。核账期只呈上月已结（零半程议题泄漏）。 */}
      {ready && showIssueQuad ? (
        <div className="hud2-issue-quad" style={{
          position: "absolute",
          left: `${HUD_SLOTS.局势框.left}%`, top: `${HUD_SLOTS.局势框.top}%`,
          width: `${HUD_SLOTS.局势框.width}%`, height: `${HUD_SLOTS.局势框.height}%`,
        }}
          data-settlement-face={showSituation
            ? settlementFaceAccess("situation", settlementDisplay)
            : settlementFaceAccess("closed_issues", settlementDisplay)}
        >
          <SituationPanel
            issues={showSituation ? state.issues : []}
            closedIssues={showClosedIssues ? (state.closed_this_turn || []) : []}
            hasLegacies={(state.legacies || []).length > 0}
          />
        </div>
      ) : null}

      {/* 顶栏：年月 + 国库/内库 + 民心/皇威，各按坑位绝对定位 */}
      <button className="hud2-slot hud2-year" style={HUD_SLOTS.顶栏.年月}
        onClick={() => gatedModal("memorials", "state")}>
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
      {/* 顶栏帝国修正：只读保留 */}
      <div className="hud2-slot hud2-legacy-slot" style={HUD_SLOTS.顶栏.皇威}
        data-settlement-face={settlementFaceAccess("legacies", settlementDisplay)}>
        <LegacyBar legacies={state.legacies} />
      </div>
      <button className="hud2-menu-btn"
        title="游戏菜单" aria-label="游戏菜单" onClick={() => gatedModal("menu", "menu")}>
        <span className="hud2-val">菜单</span>
      </button>

      {/* 右侧竖排部院导航 */}
      {([
        ["政", "court", "court_roster", "朝堂·召见大臣"],
        ["吏", "appointment", "appointment_roster", "官员任免"],
        ["省", "region", "region", "省份列表"],
        ["兵", "army", "army", "军队列表"],
        ["户", "economy", "economy", "经济面板"],
        ["工", "building", "building", "建筑列表"],
        ["礼", "court", "court_roster", "礼部"],
        ["后", "harem", "harem_roster", "后宫"],
      ] as const).map(([label, navKey, faceKey, title], idx) => {
        const slotKey = (["政","吏部","省份","兵部","户部","工部","礼部","后宫"] as const)[idx];
        const reachable = isFaceReachable(faceKey, settlementDisplay);
        return (
          <button key={slotKey}
            className={`hud2-slot hud2-nav${activeDrawerKey === navKey ? " active" : ""}${reachable ? "" : " settlement-closed"}`}
            style={HUD_SLOTS.导航[slotKey]}
            title={reachable ? title : SETTLEMENT_CLOSED_REASON}
            aria-label={title}
            aria-disabled={!reachable}
            data-settlement-face={settlementFaceAccess(faceKey, settlementDisplay)}
            onClick={() => gatedNav(faceKey, navKey)}>
            {label}
          </button>
        );
      })}

      {/* 底部 5 命令物件（扣图填进木牌） */}
      <CommandSlot slotKey="奏疏" img="奏疏" badge={state.events.length}
        caption="奏疏" sub={`${state.events.length} 件待览`}
        onClick={() => gatedModal("memorials", "state")} />
      <CommandSlot slotKey="邸报" img="邸报"
        caption="起居注" sub="历次召对记录"
        onClick={() => gatedModal("audience_archive", "audience_archive")} />
      <CommandSlot slotKey="密令" img="密令"
        badge={secretBadge}
        caption="密令" sub={isFaceReachable("secret_orders", settlementDisplay) ? "进行中密令" : SETTLEMENT_CLOSED_REASON}
        onClick={() => gatedModal("secret_orders", "secret_orders")} />
      <CommandSlot slotKey="史册" img="史册"
        caption="史册" sub="历代奏报/诏书"
        onClick={() => gatedModal("history", "history")} />
      <CommandSlot slotKey="拟诏" img="拟诏" badge={isFaceReachable("edict", settlementDisplay) ? state.directives.length : 0}
        caption="拟诏/结束回合"
        sub={isFaceReachable("edict", settlementDisplay)
          ? (state.directives.length ? `${state.directives.length} 道` : "本回合")
          : SETTLEMENT_CLOSED_REASON}
        onClick={() => gatedModal("edict", "edict")} />

      {/* #1236 P4：王承恩核账递话条——同谓词；一句正向奏疏口吻，无进度条/百分比/秒数 */}
      {showWangSlip ? (
        <div className="wang-settlement-slip" role="status" aria-live="polite" data-testid="wang-settlement-slip">
          <span className="wang-settlement-slip-speaker">王承恩</span>
          <span className="wang-settlement-slip-body">{WANG_SETTLEMENT_SLIP}</span>
        </div>
      ) : null}
    </div>
  );
}
