import React from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Menu, Upload, X } from "lucide-react";
import { api } from "../api";
import { formatLegacyEffect, formatMoney, formatSignedMoney, scoreTone } from "../format";
import type { BudgetAccount, BudgetItem, BudgetMovement, GameState, Legacy } from "../types";

export function MinisterPortrait({ primary, fallback, name }: { primary: string; fallback?: string; name: string }) {
  // 两级 fallback：primary（专属）→ fallback（pool 预设）→ 占位符
  const [stage, setStage] = React.useState<"primary" | "fallback" | "placeholder">(
    fallback ? "primary" : (primary ? "primary" : "placeholder")
  );
  const src = stage === "primary" ? primary : stage === "fallback" ? (fallback ?? "") : "";
  if (stage === "placeholder") {
    return <div className="minister-card-portrait-placeholder">臣</div>;
  }
  return (
    <img
      className="minister-card-portrait"
      src={src}
      alt={name}
      onError={() => {
        if (stage === "primary" && fallback) setStage("fallback");
        else setStage("placeholder");
      }}
    />
  );
}


// 朝班两条透视线（百分比锚点，由用户拖定）
// 左列：韩爌(外) → 黄立极(内)；右列：张瑞图(外) → 施凤来(内)
export const LEFT_ANCHOR  = { near: { px: 0.077, py: 0.532 }, far: { px: 0.377, py: 0.066 } };

export const RIGHT_ANCHOR = { near: { px: 0.862, py: 0.532 }, far: { px: 0.558, py: 0.045 } };


// 每列槽位数
export const COURT_SLOTS_PER_ROW = 10;


// 生成两列所有槽位坐标（百分比）
export function courtSlots(): { px: number; py: number; side: "left" | "right"; slot: number }[] {
  const slots = [];
  for (let i = 0; i < COURT_SLOTS_PER_ROW; i++) {
    const t = i / (COURT_SLOTS_PER_ROW - 1);
    slots.push({
      px: LEFT_ANCHOR.near.px + t * (LEFT_ANCHOR.far.px - LEFT_ANCHOR.near.px),
      py: LEFT_ANCHOR.near.py + t * (LEFT_ANCHOR.far.py - LEFT_ANCHOR.near.py),
      side: "left" as const, slot: i,
    });
    slots.push({
      px: RIGHT_ANCHOR.near.px + t * (RIGHT_ANCHOR.far.px - RIGHT_ANCHOR.near.px),
      py: RIGHT_ANCHOR.near.py + t * (RIGHT_ANCHOR.far.py - RIGHT_ANCHOR.near.py),
      side: "right" as const, slot: i,
    });
  }
  return slots;
}


// 找最近槽位（已被占用的跳过，但允许同名覆盖）
export function snapToSlot(px: number, py: number, occupied: Set<string>, selfKey: string): { px: number; py: number } {
  const slots = courtSlots();
  let best = null as { px: number; py: number } | null;
  let bestDist = Infinity;
  for (const s of slots) {
    const key = `${s.side}:${s.slot}`;
    if (occupied.has(key) && key !== selfKey) continue;
    const d = Math.hypot(s.px - px, s.py - py);
    if (d < bestDist) { bestDist = d; best = s; }
  }
  return best ?? { px, py };
}


// 默认坐标：从 near 开始，每人占一格，紧挨着排不留空
export const COURT_SLOT_STEP = 1 / (COURT_SLOTS_PER_ROW - 1);  // 相邻槽间距（百分比t）

export function defaultCourtPct(index: number, total: number): { px: number; py: number } {
  const leftCount = Math.ceil(total / 2);
  const isLeft = index < leftCount;
  const posInRow = isLeft ? index : index - leftCount;
  const anchor = isLeft ? LEFT_ANCHOR : RIGHT_ANCHOR;
  const t = posInRow * COURT_SLOT_STEP;  // 从槽0开始连续，不跳格
  return {
    px: anchor.near.px + t * (anchor.far.px - anchor.near.px),
    py: anchor.near.py + t * (anchor.far.py - anchor.near.py),
  };
}

// 坐标存百分比（0-1），持久化到服务端 db（按存档隔离）
export async function loadCourtPos(): Promise<Record<string, { px: number; py: number }>> {
  try {
    const r = await fetch("/api/court_layout");
    if (!r.ok) return {};
    const d = await r.json();
    return JSON.parse(d.layout || "{}");
  } catch { return {}; }
}

export function saveCourtPos(pos: Record<string, { px: number; py: number }>) {
  fetch("/api/court_layout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ layout: JSON.stringify(pos) }),
  }).catch(() => {});
}

// 自定义立绘文件名固定（一人一图），故按 portrait_id 之外另用上传时间戳刷缓存。
export const _portraitBust: Record<string, number> = {};

export function cacheBust(key: string): number {
  if (!_portraitBust[key]) _portraitBust[key] = Date.now();
  return _portraitBust[key];
}

export function PortraitUploadButton({
  ministerName,
  onUpload,
}: {
  ministerName: string;
  onUpload: (ministerName: string, file: File) => Promise<void>;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  return (
    <>
      <button
        type="button"
        className="portrait-upload-btn"
        title="上传立绘"
        disabled={busy}
        onClick={(e) => {
          e.stopPropagation();  // 别触发卡片的召见
          inputRef.current?.click();
        }}
      >
        <Upload size={13} />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: "none" }}
        onClick={(e) => e.stopPropagation()}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";  // 允许重选同一文件
          if (!file) return;
          setBusy(true);
          try {
            // 立即刷该人物缓存键，loadState 回来后新图不被旧缓存挡住。
            _portraitBust[`custom:${ministerName}`] = Date.now();
            await onUpload(ministerName, file);
          } catch (err) {
            window.alert(`上传失败：${(err as Error).message}`);
          } finally {
            setBusy(false);
          }
        }}
      />
    </>
  );
}

export function RightNavBar({
  onToggleCourt,
  onToggleHarem,
  onToggleArmy,
  onToggleRegion,
  onToggleBuilding,
  onToggleEconomy,
  onToggleAppointment,
  onOpenLongGoals,
  activeDrawer,
}: {
  onToggleCourt: () => void;
  onToggleHarem: () => void;
  onToggleArmy: () => void;
  onToggleRegion: () => void;
  onToggleBuilding: () => void;
  onToggleEconomy: () => void;
  onToggleAppointment: () => void;
  onOpenLongGoals: () => void;
  activeDrawer: string;
}) {
  const items = [
    { key: "court", label: "政", title: "朝堂·召见大臣", onClick: onToggleCourt },
    { key: "harem", label: "内", title: "后宫", onClick: onToggleHarem },
    { key: "army", label: "兵", title: "军队列表", onClick: onToggleArmy },
    { key: "region", label: "省", title: "省份列表", onClick: onToggleRegion },
    { key: "building", label: "工", title: "建筑列表", onClick: onToggleBuilding },
    { key: "economy", label: "户", title: "经济面板", onClick: onToggleEconomy },
    { key: "appointment", label: "吏", title: "官员任免", onClick: onToggleAppointment },
  ];
  return (
    <nav className="right-nav-bar" aria-label="六部入口">
      {items.map((item) => (
        <button
          key={item.key}
          className={`right-nav-btn${activeDrawer === item.key ? " active" : ""}`}
          title={item.title}
          aria-label={item.title}
          onClick={item.onClick}
        >
          {item.label}
        </button>
      ))}
      <button
        className="right-nav-btn right-nav-btn-goal"
        title="长期目标"
        aria-label="大明长期目标"
        onClick={onOpenLongGoals}
      >
        目
      </button>
    </nav>
  );
}

export function RightDrawer({
  open,
  onClose,
  title,
  icon,
  children,
  extraClass,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  extraClass?: string;
}) {
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="收起" onClick={onClose} />}
      <aside className={`right-drawer ${extraClass || ""} ${open ? "open" : ""}`}>
        <div className="right-drawer-brand">
          <div className="panel-title">
            {icon}
            <span>{title}</span>
          </div>
          <button className="icon-button" aria-label="收起" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="right-drawer-body">
          {children}
        </div>
      </aside>
    </>
  );
}

// ── 新 HUD 底图坑位坐标（相对底图百分比，见 web/public/ui/exact/hud-slots.json）──
export const HUD_BG = "/ui/exact/auto-code-image-11685.png";

export const HUD_SLOTS = {
  顶栏: {
    年月: { left: "9.6%", top: "6.31%" },
    国库: { left: "25.83%", top: "6.32%" },
    内库: { left: "42.33%", top: "6.35%" },
    民心: { left: "58.63%", top: "6.06%" },
    皇威: { left: "76.09%", top: "6.15%" },
    菜单: { left: "85.8%", top: "4.6%" },
  },
  导航: {
    政: { left: "93.36%", top: "19.46%" },
    吏部: { left: "93.38%", top: "23.85%" },
    省份: { left: "93.55%", top: "33.86%" },
    兵部: { left: "93.71%", top: "38.14%" },
    户部: { left: "94.12%", top: "48.09%" },
    工部: { left: "94.13%", top: "51.64%" },
    礼部: { left: "94.22%", top: "60.33%" },
    后宫: { left: "94.36%", top: "68.81%" },
    目标: { left: "94.56%", top: "76.32%" },
  },
  命令: {
    奏疏: { left: "12.02%", top: "75.57%", width: "11.8%", height: "11.13%" },
    邸报: { left: "28.34%", top: "75.45%", width: "11.61%", height: "12.46%" },
    密令: { left: "46.91%", top: "73.38%", width: "9.76%", height: "13.11%" },
    史册: { left: "63.92%", top: "73.4%", width: "9.4%", height: "13.21%" },
    拟诏: { left: "77.29%", top: "67.15%", width: "14.08%", height: "21.67%" },
  },
  命令文字: {
    奏疏: { left: "16.78%", top: "89.93%" },
    邸报: { left: "32.81%", top: "89.66%" },
    密令: { left: "51.02%", top: "88.99%" },
    史册: { left: "67.86%", top: "89.68%" },
    拟诏: { left: "83.9%", top: "89.76%" },
  },
  地图四角: { tl: [17.89, 14.9], tr: [86.95, 14.9], br: [92.13, 76.61], bl: [13.9, 76.61] },
  局势四角: { tl: [3.14, 24.09], tr: [15.06, 24.09], br: [14.36, 47.95], bl: [1.6, 47.95] },
} as const;


// 四角 [x%,y%] → matrix3d，把单位正方形(0..1)映射到任意四边形（透视）
export function quadToMatrix3d(
  w: number, h: number,
  tl: readonly number[], tr: readonly number[], br: readonly number[], bl: readonly number[]
): string {
  // 目标点用像素（相对容器 w×h）
  const px = (p: readonly number[]) => [(p[0] / 100) * w, (p[1] / 100) * h];
  const [x0, y0] = px(tl), [x1, y1] = px(tr), [x2, y2] = px(br), [x3, y3] = px(bl);
  // 源单位矩形角: (0,0)(w,0)(w,h)(0,h) → 解 8 参数透视变换
  const src = [[0, 0], [w, 0], [w, h], [0, h]];
  const dst = [[x0, y0], [x1, y1], [x2, y2], [x3, y3]];
  const A: number[][] = [], b: number[] = [];
  for (let i = 0; i < 4; i++) {
    const [sx, sy] = src[i], [dx, dy] = dst[i];
    A.push([sx, sy, 1, 0, 0, 0, -sx * dx, -sy * dx]); b.push(dx);
    A.push([0, 0, 0, sx, sy, 1, -sx * dy, -sy * dy]); b.push(dy);
  }
  const h8 = solve8(A, b);
  const [a, bb, c, d, e, f, g, i] = h8;
  // CSS matrix3d 列主序
  return `matrix3d(${a},${d},0,${g}, ${bb},${e},0,${i}, 0,0,1,0, ${c},${f},0,1)`;
}

export function solve8(A: number[][], b: number[]): number[] {
  // 高斯消元 8×8
  const n = 8, M = A.map((row, k) => [...row, b[k]]);
  for (let col = 0; col < n; col++) {
    let piv = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
    [M[col], M[piv]] = [M[piv], M[col]];
    const pv = M[col][col] || 1e-9;
    for (let c = col; c <= n; c++) M[col][c] /= pv;
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const factor = M[r][col];
      for (let c = col; c <= n; c++) M[r][c] -= factor * M[col][c];
    }
  }
  return M.map((row) => row[n]);
}


// 透视梯形容器：内部 stageW×stageH 的正放内容被 matrix3d 压成梯形
export function QuadFrame({
  quad, stageW, stageH, baseW, baseH, children, className, style,
}: {
  quad: { tl: readonly number[]; tr: readonly number[]; br: readonly number[]; bl: readonly number[] };
  stageW: number; stageH: number; baseW: number; baseH: number;
  children: React.ReactNode; className?: string; style?: React.CSSProperties;
}) {
  // 正放内容的逻辑尺寸＝四角包围盒像素
  const xs = [quad.tl[0], quad.tr[0], quad.br[0], quad.bl[0]];
  const ys = [quad.tl[1], quad.tr[1], quad.br[1], quad.bl[1]];
  const left = (Math.min(...xs) / 100) * stageW;
  const top = (Math.min(...ys) / 100) * stageH;
  const w = ((Math.max(...xs) - Math.min(...xs)) / 100) * stageW;
  const h = ((Math.max(...ys) - Math.min(...ys)) / 100) * stageH;
  // 四角相对包围盒左上的局部坐标（百分比，喂 matrix3d）
  const rel = (p: readonly number[]) => [
    ((p[0] / 100) * stageW - left) / w * 100,
    ((p[1] / 100) * stageH - top) / h * 100,
  ];
  const m = quadToMatrix3d(w, h, rel(quad.tl), rel(quad.tr), rel(quad.br), rel(quad.bl));
  return (
    <div
      className={className}
      style={{
        position: "absolute", left, top, width: w, height: h,
        transform: m, transformOrigin: "0 0", ...style,
      }}
    >
      {children}
    </div>
  );
}

export function TopStatusBar({
  state,
  onOpenState,
  onOpenMenu,
}: {
  state: GameState;
  onOpenState: () => void;
  onOpenMenu: () => void;
}) {
  const scoreKeys = ["民心", "皇威"];
  return (
    <>
    <header className="status-bar" aria-label="国势状态栏">
      <button className="status-emblem" onClick={onOpenState}>
        <img src="/icon_ming_emblem.png" alt="大明" className="emblem-art" />
        <span>{state.turn.year} 年 {state.turn.period} 月</span>
      </button>
      <i className="hud-divider" aria-hidden="true" />
      <div className="status-metrics">
        <BudgetHover accountName="国库" budget={state.budget["国库"]} />
        <BudgetHover accountName="内库" budget={state.budget["内库"]} />
        <i className="hud-divider" aria-hidden="true" />
        {scoreKeys.map((key) => (
          <span className={`status-pill ${scoreTone(state.metrics[key], false)}`} key={key}>
            {key} <b>{state.metrics[key]}</b>
          </span>
        ))}
        <i className="hud-divider" aria-hidden="true" />
        <button className="status-menu" onClick={onOpenMenu} aria-label="游戏菜单">
          <Menu size={16} />
          <span>菜单</span>
        </button>
      </div>
    </header>
    <LegacyBar legacies={state.legacies} />
    </>
  );
}

export const LONG_GOAL_POSTERS = [
  { src: "/long_goal_ming.jpg", alt: "长期目标：让大明再续二百年" },
  { src: "/long_goal_tech.jpg", alt: "长期目标：科技树与文明延续" },
  { src: "/long_goal_modernity.jpg", alt: "长期目标：从王朝危机到现代文明" },
];

export function LongGoalsModal({ onClose }: { onClose: () => void }) {
  const [index, setIndex] = React.useState(0);
  const goPrev = React.useCallback(() => {
    setIndex((current) => (current + LONG_GOAL_POSTERS.length - 1) % LONG_GOAL_POSTERS.length);
  }, []);
  const goNext = React.useCallback(() => {
    setIndex((current) => (current + 1) % LONG_GOAL_POSTERS.length);
  }, []);

  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") goPrev();
      if (event.key === "ArrowRight") goNext();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goPrev, goNext]);

  const poster = LONG_GOAL_POSTERS[index];
  return (
    <section className="long-goal-layer" role="dialog" aria-modal="true" aria-label="大明长期目标">
      <div className="long-goal-scrim" onClick={onClose} />
      <button className="long-goal-close" aria-label="关闭弹窗" onClick={onClose}>
        <X size={30} />
      </button>
      <button className="long-goal-nav long-goal-nav-prev" aria-label="上一张长期目标图" onClick={goPrev}>
        <ChevronLeft size={34} />
      </button>
      <figure className="long-goal-poster">
        <img src={poster.src} alt={poster.alt} />
      </figure>
      <button className="long-goal-nav long-goal-nav-next" aria-label="下一张长期目标图" onClick={goNext}>
        <ChevronRight size={34} />
      </button>
      <div className="long-goal-dots" aria-label="长期目标图切换">
        {LONG_GOAL_POSTERS.map((item, itemIndex) => (
          <button
            key={item.src}
            className={itemIndex === index ? "active" : ""}
            aria-label={`切换到第 ${itemIndex + 1} 张长期目标图`}
            onClick={() => setIndex(itemIndex)}
          />
        ))}
      </div>
    </section>
  );
}

export function LegacyBar({ legacies }: { legacies: Legacy[] }) {
  const [open, setOpen] = React.useState(false);
  if (!legacies || legacies.length === 0) return null;
  return (
    <>
      <button
        className="legacy-bar"
        aria-label="现行帝国修正"
        onClick={() => setOpen(true)}
      >
        <span className="legacy-bar-label">帝国修正</span>
        <span className="legacy-bar-count">{legacies.length}</span>
      </button>
      {open && createPortal(
        <div className="legacy-modal-backdrop" onClick={() => setOpen(false)}>
          <div className="legacy-modal" onClick={(e) => e.stopPropagation()}>
            <div className="legacy-modal-head">
              <h3>现行帝国修正</h3>
              <button className="legacy-modal-close" onClick={() => setOpen(false)} aria-label="关闭">×</button>
            </div>
            <ul className="legacy-list">
              {legacies.map((lg) => (
                <li key={lg.id} className="legacy-item">
                  <div className="legacy-item-top">
                    <b>{lg.name}</b>
                    <span className="legacy-item-meta">
                      <span className="legacy-item-dur">{lg.remaining_months < 0 ? "永久" : `余 ${lg.remaining_months} 月`}</span>
                    </span>
                  </div>
                  <p className="legacy-item-eff">{lg.effect_text || formatLegacyEffect(lg.modifiers)}</p>
                  {lg.clear_condition && <p className="legacy-item-clear">消除条件：{lg.clear_condition}</p>}
                  {lg.narrative_hint && <p className="legacy-item-hint">{lg.narrative_hint}</p>}
                </li>
              ))}
            </ul>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

export function BudgetHover({ accountName, budget }: { accountName: "国库" | "内库"; budget: BudgetAccount }) {
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const [pos, setPos] = React.useState<{ left: number; top: number } | null>(null);
  const show = () => {
    const r = triggerRef.current?.getBoundingClientRect();
    if (r) setPos({ left: r.left, top: r.bottom + 6 });
    setOpen(true);
  };
  const hide = () => setOpen(false);
  return (
    <span
      className={`budget-hover ${open ? "open" : ""}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      <button
        ref={triggerRef}
        className="status-money budget-trigger"
        type="button"
        aria-label={`查看${accountName}固定收支`}
        onClick={() => (open ? hide() : show())}
      >
        <span>{accountName} <b>{formatMoney(budget.balance)}</b></span>
        <small className={budget.net >= 0 ? "income" : "expense"}>月 {formatSignedMoney(budget.net)}</small>
      </button>
      {open && pos && createPortal(
        <span className="budget-popover budget-popover-portal" role="tooltip"
          style={{ left: pos.left, top: pos.top }}>
          <span className="budget-popover-head">
            <b>{accountName}月度定额</b>
            <span className="budget-summary">
              <span><small>入</small><strong className="income">{formatMoney(budget.income_total)}</strong></span>
              <span><small>出</small><strong className="expense">{formatMoney(budget.expense_total)}</strong></span>
              <span><small>净</small><strong className={budget.net >= 0 ? "income" : "expense"}>{formatSignedMoney(budget.net)}</strong></span>
            </span>
          </span>
          <BudgetList title="固定收入" items={budget.income} />
          <BudgetList title="固定支出" items={budget.expense} expense />
          <BudgetMovementsList movements={budget.movements} total={budget.movements_total} />
        </span>,
        document.body
      )}
    </span>
  );
}

export function BudgetMovementsList({ movements, total }: { movements: BudgetMovement[]; total: number }) {
  if (!movements.length) {
    return (
      <span className="budget-list">
        <span className="budget-list-title">本月一次性入账（上月末结算）</span>
        <span className="budget-row"><span><b>暂无</b><small>上月末未结算入出</small></span></span>
      </span>
    );
  }
  return (
    <span className="budget-list">
      <span className="budget-list-title">
        本月一次性入账（上月末结算）
        <small className={total >= 0 ? "income" : "expense"}>　合计 {formatSignedMoney(total)}</small>
      </span>
      {movements.map((m, idx) => {
        const sign = m.delta >= 0 ? "+" : "-";
        const cls = m.delta >= 0 ? "income" : "expense";
        return (
          <span className="budget-row" key={`mv-${idx}`}>
            <span>
              <b>{m.category || "—"}</b>
              <small>{m.reason}</small>
            </span>
            <strong className={cls}>{sign}{formatMoney(Math.abs(m.delta))}</strong>
          </span>
        );
      })}
    </span>
  );
}

export function BudgetList({ title, items, expense = false }: { title: string; items: BudgetItem[]; expense?: boolean }) {
  return (
    <span className="budget-list">
      <span className="budget-list-title">{title}</span>
      {items.map((item) => (
        <span className="budget-row" key={`${title}-${item.name}`}>
          <span>
            <b>{item.name}</b>
            <small>{item.note}</small>
          </span>
          <strong className={expense ? "expense" : "income"}>{expense ? "-" : "+"}{formatMoney(item.amount)}</strong>
        </span>
      ))}
    </span>
  );
}


// 底部命令物件：扣图按木牌坑定位，文字标签按独立文字坑定位（两者分离，各自调位）
export function CommandSlot({
  slotKey, img, badge, caption, sub, onClick,
}: {
  slotKey: keyof typeof HUD_SLOTS.命令;
  img: string; badge?: number; caption: string; sub: string; onClick: () => void;
}) {
  return (
    <>
      <button className="hud2-cmd" style={HUD_SLOTS.命令[slotKey]} onClick={onClick}
        aria-label={`${caption}：${sub}`}>
        <img className="hud2-cmd-img" src={`/ui/exact/cmd/${img}.png`} alt="" />
        {badge ? <span className="hud2-cmd-badge">{badge}</span> : null}
      </button>
      <button className="hud2-slot hud2-cmd-caption" style={HUD_SLOTS.命令文字[slotKey]}
        onClick={onClick} aria-label={`${caption}：${sub}`}>
        <b>{caption}</b><small>{sub}</small>
      </button>
    </>
  );
}

export function BottomCommandBar({
  eventsCount,
  directivesCount,
  secretOrdersCount,
  onOpenMemorials,
  onOpenEdict,
  onOpenExtraction,
  onOpenHistory,
  onOpenSecretOrders,
}: {
  eventsCount: number;
  directivesCount: number;
  secretOrdersCount: number;
  onOpenMemorials: () => void;
  onOpenEdict: () => void;
  onOpenExtraction: () => void;
  onOpenHistory: () => void;
  onOpenSecretOrders: () => void;
}) {
  return (
    <div className="ui-stage">
      {/* 案板 + 图标 + 玉玺一体 */}
      <div className="anban-wrap">
        {/* 图标行：底部贴基准线向上生长 */}
        <nav className="bottom-command-bar" aria-label="朝政辅助操作">
          <button className="command-icon" onClick={onOpenMemorials} aria-label={`奏疏 ${eventsCount} 件待览`}>
            <img src="/ui/exact/zoushu.png" alt="" className="command-art" />
            {eventsCount ? <span className="command-badge">{eventsCount}</span> : null}
          </button>
          <button className="command-icon" onClick={onOpenExtraction} aria-label="邸报详明">
            <img src="/ui/exact/mingxi.png" alt="" className="command-art" />
          </button>
          <button className="command-icon" onClick={onOpenSecretOrders} aria-label={`密令 ${secretOrdersCount} 条进行中`}>
            <img src="/ui/exact/miling.png" alt="" className="command-art command-art-secret" />
            {secretOrdersCount ? <span className="command-badge command-badge-secret">{secretOrdersCount}</span> : null}
          </button>
          <button className="command-icon" onClick={onOpenHistory} aria-label="历代奏报">
            <img src="/ui/exact/lishi.png" alt="" className="command-art" />
          </button>
          <button className="edict-turn-button" onClick={onOpenEdict} aria-label={`诏书草案 ${directivesCount} 道待发`}>
            <span className="edict-turn-art">
              <img src="/ui/exact/nizhao.png" alt="" />
              {directivesCount ? <span className="command-badge edict-turn-badge">{directivesCount}</span> : null}
            </span>
          </button>
        </nav>
        {/* 文字行：贴在 bar 下方 */}
        <div className="bottom-caption-bar">
          <span className="command-caption"><b>奏疏</b><small>{eventsCount} 件待览</small></span>
          <span className="command-caption"><b>邸报详明</b><small>数项加减/账目明细</small></span>
          <span className="command-caption"><b>密令</b><small>{secretOrdersCount ? `${secretOrdersCount} 条进行中` : "暂无密令"}</small></span>
          <span className="command-caption"><b>史册</b><small>历代奏报/诏书</small></span>
          <span className="command-caption"><b>拟诏/结束回合</b><small>{directivesCount ? `${directivesCount} 道` : "本回合"}</small></span>
        </div>
      </div>
    </div>
  );
}

export function FullscreenModal({
  title,
  subtitle,
  bgClass,
  onClose,
  children,
  headerExtra,
}: {
  title: string;
  subtitle: string;
  bgClass?: string;
  onClose: () => void;
  children: React.ReactNode;
  headerExtra?: React.ReactNode;
}) {
  return (
    <section className="fullscreen-layer" role="dialog" aria-modal="true" aria-label={title}>
      <div className="fullscreen-scrim" onClick={onClose} />
      <div className={`fullscreen-modal ${bgClass || ""}`}>
        <header className="modal-header">
          <div className="modal-title">
            <div>
              <h1>{title}</h1>
              <span>{subtitle}</span>
            </div>
          </div>
          <div className="modal-header-actions">
            {headerExtra}
            <button className="icon-button" aria-label="关闭弹窗" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </header>
        {children}
      </div>
    </section>
  );
}
