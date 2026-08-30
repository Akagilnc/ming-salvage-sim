import React from "react";
import { createPortal } from "react-dom";
import { Upload, X } from "lucide-react";
import { formatLegacyEffect, formatMoney, formatSignedMoney } from "../format";
import type { BudgetAccount, BudgetItem, BudgetMovement, Legacy, SettledArmyPay } from "../types";

export function MinisterPortrait({ primary, fallback, name, className = "minister-card-portrait" }: { primary: string; fallback?: string; name: string; className?: string }) {
  // 两级 fallback：primary（专属）→ fallback（pool 预设）→ 占位符
  const [stage, setStage] = React.useState<"primary" | "fallback" | "placeholder">(
    fallback ? "primary" : (primary ? "primary" : "placeholder")
  );
  const src = stage === "primary" ? primary : stage === "fallback" ? (fallback ?? "") : "";
  if (stage === "placeholder") {
    return <div className={`${className} minister-card-portrait-placeholder`}>臣</div>;
  }
  return (
    <img
      className={className}
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


// 坐标存百分比（0-1），持久化到服务端 db（按存档隔离）。
// #1290：空 {} = 无玩家覆盖，合法；默认朝班由 drawers arrange(courtSlots) 生成，不 seed。
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
      <aside inert={!open} className={`right-drawer ${extraClass || ""} ${open ? "open" : ""}`}>
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

// ── 新 HUD 底图坑位坐标（正视角平面矩形，相对底图百分比，底图 bg_hud_night_concept2.png 2560×1440）──
export const HUD_BG = "/bg_hud_night_concept2.png";

export const HUD_SLOTS = {
  顶栏: {
    年月: { left: "25.0%", top: "8.1%" },
    国库: { left: "38.1%", top: "8.1%" },
    内库: { left: "50.9%", top: "8.1%" },
    民心: { left: "63.6%", top: "8.1%" },
    皇威: { left: "76.5%", top: "8.1%" },
    菜单: { left: "85.8%", top: "4.6%" },
  },
  导航: {
    政: { left: "90.4%", top: "19.3%" },
    吏部: { left: "90.4%", top: "27.5%" },
    省份: { left: "90.4%", top: "35.4%" },
    兵部: { left: "90.4%", top: "43.4%" },
    户部: { left: "90.4%", top: "51.5%" },
    工部: { left: "90.4%", top: "59.6%" },
    礼部: { left: "90.4%", top: "67.7%" },
    后宫: { left: "90.4%", top: "75.7%" },
  },
  命令: {
    奏疏: { left: "8.0%", top: "74.0%", width: "14%", height: "20%" },
    邸报: { left: "26.2%", top: "74.5%", width: "14%", height: "20%" },
    密令: { left: "43.0%", top: "74.0%", width: "14%", height: "20%" },
    史册: { left: "57.5%", top: "74.5%", width: "14%", height: "20%" },
    拟诏: { left: "76.5%", top: "76.5%", width: "11.5%", height: "18%" },
  },
  命令文字: {
    奏疏: { left: "15.0%", top: "94.6%" },
    邸报: { left: "33.2%", top: "94.6%" },
    密令: { left: "50.0%", top: "94.6%" },
    史册: { left: "64.5%", top: "94.6%" },
    拟诏: { left: "85.0%", top: "94.6%" },
  },
  地图框: { left: 22.0, top: 16.8, width: 59.2, height: 53.4 },
  局势框: { left: 8.8, top: 17.0, width: 7.6, height: 46.0 },
} as const;

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

/** #1366：军饷玩家可见时间线——结算前只呈现全军名义应发合计（事实，不预演分配/损耗）；
 * 结算后呈现已执行的国库实拨/实际到达/途中损耗（同一 settled_turn，只读既有 ledger/容器投影）。 */
export function ArmyPaySection({
  armyPayDueTotal, settledArmyPay,
}: {
  armyPayDueTotal?: number;
  settledArmyPay?: SettledArmyPay | null;
}) {
  if (armyPayDueTotal === undefined && !settledArmyPay) return null;
  return (
    <span className="budget-list budget-army-pay">
      <span className="budget-list-title">军饷</span>
      {armyPayDueTotal !== undefined && (
        <span className="budget-row">
          <span><b>全军名义应发</b><small>结算前事实，不含转运损耗</small></span>
          <strong className="expense">{formatMoney(armyPayDueTotal)}</strong>
        </span>
      )}
      {settledArmyPay && (
        <>
          <span className="budget-row">
            <span><b>国库实拨</b><small>第 {settledArmyPay.settled_turn} 月边饷 hub 结算</small></span>
            <strong className="expense">{formatMoney(settledArmyPay.treasury_disbursed)}</strong>
          </span>
          <span className="budget-row">
            <span><b>实际到达</b></span>
            <strong className="income">{formatMoney(settledArmyPay.actual_arrived)}</strong>
          </span>
          <span className="budget-row">
            <span><b>途中损耗</b></span>
            <strong className="expense">{formatMoney(settledArmyPay.transit_loss)}</strong>
          </span>
        </>
      )}
    </span>
  );
}

export function BudgetHover({ accountName, budget, armyPayDueTotal, settledArmyPay }: {
  accountName: "国库" | "内库";
  budget: BudgetAccount;
  armyPayDueTotal?: number;
  settledArmyPay?: SettledArmyPay | null;
}) {
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const hideTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pos, setPos] = React.useState<{ left: number; top: number } | null>(null);
  const cancelHide = () => {
    if (hideTimer.current) { clearTimeout(hideTimer.current); hideTimer.current = null; }
  };
  const show = () => {
    cancelHide();
    const r = triggerRef.current?.getBoundingClientRect();
    if (r) setPos({ left: r.left, top: r.bottom + 6 });
    setOpen(true);
  };
  // 宽限延迟：鼠标从触发器挪向浮层（portal 到 body，非 DOM 子级）时给 300ms 缓冲
  const scheduleHide = () => {
    cancelHide();
    hideTimer.current = setTimeout(() => setOpen(false), 300);
  };
  React.useEffect(() => cancelHide, []);
  return (
    <span
      className={`budget-hover ${open ? "open" : ""}`}
      onMouseEnter={show}
      onMouseLeave={scheduleHide}
      onFocus={show}
      onBlur={scheduleHide}
    >
      <button
        ref={triggerRef}
        className="status-money budget-trigger"
        type="button"
        aria-label={`查看${accountName}固定收支`}
        onClick={() => (open ? setOpen(false) : show())}
      >
        <span className="hud2-lab">{accountName}</span>
        <span className="hud2-val"><b>{formatMoney(budget.balance)}</b></span>
        <small className={budget.net >= 0 ? "income" : "expense"}>月 {formatSignedMoney(budget.net)}</small>
      </button>
      {open && pos && createPortal(
        <span className="budget-popover budget-popover-portal" role="tooltip"
          style={{ left: pos.left, top: pos.top, maxHeight: `calc(100vh - ${pos.top + 12}px)` }}
          onMouseEnter={cancelHide}
          onMouseLeave={scheduleHide}>
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
          {accountName === "国库" && (
            <ArmyPaySection armyPayDueTotal={armyPayDueTotal} settledArmyPay={settledArmyPay} />
          )}
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
  // #1471：定额条目只显示 display 名+金额；工程 note 不进玩家 HUD。
  return (
    <span className="budget-list">
      <span className="budget-list-title">{title}</span>
      {items.map((item) => (
        <span className="budget-row" key={`${title}-${item.name}`}>
          <span>
            <b>{item.name}</b>
          </span>
          <strong className={expense ? "expense" : "income"}>{expense ? "-" : "+"}{formatMoney(item.amount)}</strong>
        </span>
      ))}
    </span>
  );
}


// 底部命令物件：扣图按木牌坑定位，文字标签按独立文字坑定位（两者分离，各自调位）
export function CommandSlot({
  slotKey, img, badge, caption, sub, onClick, className, blocked = false,
}: {
  slotKey: keyof typeof HUD_SLOTS.命令;
  img: string; badge?: number; caption: string; sub: string; onClick: () => void;
  /** 可选修饰类（如 #1454 台开收起态）。 */
  className?: string;
  /** #1458：拟诏台开着时其余底栏命令禁用——安全区整条开洞不得把 activeModal 切走。 */
  blocked?: boolean;
}) {
  const extra = `${className ? ` ${className}` : ""}${blocked ? " hud-cmd-blocked-by-edict" : ""}`;
  const handleClick = blocked ? undefined : onClick;
  return (
    <>
      <button className={`hud2-cmd${extra}`} style={HUD_SLOTS.命令[slotKey]} onClick={handleClick}
        aria-label={`${caption}：${sub}`} aria-disabled={blocked || undefined}>
        <img className="hud2-cmd-img" src={`/ui/exact/cmd/${img}.png`} alt="" />
        {badge ? <span className="hud2-cmd-badge">{badge}</span> : null}
      </button>
      <button className={`hud2-slot hud2-cmd-caption${extra}`} style={HUD_SLOTS.命令文字[slotKey]}
        onClick={handleClick} aria-label={`${caption}：${sub}`} aria-disabled={blocked || undefined}>
        <b>{caption}</b><small>{sub}</small>
      </button>
    </>
  );
}

export function FullscreenModal({
  title,
  subtitle,
  bgClass,
  layerClassName,
  onClose,
  children,
  headerExtra,
  hideTitle,
}: {
  title: string;
  subtitle: string;
  bgClass?: string;
  /** 叠在 fullscreen-layer 上的修饰类（如 #1454 拟诏台底栏安全区）。 */
  layerClassName?: string;
  onClose: () => void;
  children: React.ReactNode;
  headerExtra?: React.ReactNode;
  hideTitle?: boolean;
}) {
  return (
    <section
      className={layerClassName ? `fullscreen-layer ${layerClassName}` : "fullscreen-layer"}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="fullscreen-scrim" onClick={onClose} />
      <div className={["fullscreen-modal", bgClass, hideTitle ? "modal-layout-bare" : ""].filter(Boolean).join(" ")}>
        <header className={`modal-header ${hideTitle ? "modal-header-bare" : ""}`}>
          {!hideTitle && (
            <div className="modal-title">
              <div>
                <h1>{title}</h1>
                <span>{subtitle}</span>
              </div>
            </div>
          )}
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
