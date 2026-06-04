import React from "react";
import { Crown, Landmark, MapPinned, ScrollText, Star, Swords, X } from "lucide-react";
import { MinisterPortrait, PortraitUploadButton, RightDrawer, cacheBust, courtSlots, loadCourtPos, saveCourtPos, snapToSlot } from "./hud";
import { formatMoney, formatSignedMoney } from "../format";
import type { Army, Building, GameState, MapNode, Minister, Region } from "../types";

export function MinisterCardList({
  list,
  portraitPrefix,
  selectedMinister,
  emptyNote,
  onOpenChat,
  onUploadPortrait,
  courtMode = false,
}: {
  list: Minister[];
  portraitPrefix: string;
  selectedMinister: string;
  emptyNote: string;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait?: (ministerName: string, file: File) => Promise<void>;
  courtMode?: boolean;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [positions, setPositions] = React.useState<Record<string, { px: number; py: number }>>({});
  const savedPosRef = React.useRef<Record<string, { px: number; py: number }> | null>(null);
  const dragging = React.useRef<{ name: string; startMX: number; startMY: number; startPX: number; startPY: number } | null>(null);
  const didDrag = React.useRef(false);

  // 固定职位 → 固定槽位（由 office 文字推导：office 逗号分项里命中即占该槽）
  const FIXED_SLOTS: { role: string; side: "left" | "right"; slot: number }[] = [
    { role: "首辅",    side: "left",  slot: 0 },
    { role: "次辅",    side: "right", slot: 0 },
    { role: "吏部尚书", side: "left",  slot: 1 },
    { role: "户部尚书", side: "right", slot: 1 },
    { role: "礼部尚书", side: "left",  slot: 2 },
    { role: "兵部尚书", side: "right", slot: 2 },
    { role: "刑部尚书", side: "left",  slot: 3 },
    { role: "工部尚书", side: "right", slot: 3 },
  ];

  // 从 office 字符串推导固定席位：逗号切分，任一分项精确等于某固定职名即占该槽。
  // 南京XX尚书是留都缺，不占京职槽——精确匹配自然排除（分项是「南京兵部尚书」≠「兵部尚书」）。
  function roleFromOffice(office: string): string {
    const parts = (office || "").split(",").map((s) => s.trim());
    const fs = FIXED_SLOTS.find((f) => parts.includes(f.role));
    return fs ? fs.role : "";
  }

  function fixedSlotFor(role: string): { px: number; py: number } | null {
    if (!role) return null;
    const allSlots = courtSlots();
    const fs = FIXED_SLOTS.find((f) => f.role === role);
    if (!fs) return null;
    const s = allSlots.find((sl) => sl.side === fs.side && sl.slot === fs.slot);
    return s ? { px: s.px, py: s.py } : null;
  }

  // 拖动覆盖坐标只加载一次。list 变化只重排，不重 fetch。
  const listKey = list.map((m) => m.name).join("|");
  React.useEffect(() => {
    let cancelled = false;
    const arrange = (saved: Record<string, { px: number; py: number }>) => {
      if (cancelled) return;
      const allSlots = courtSlots();
      const next: Record<string, { px: number; py: number }> = {};
      const usedSlots = new Set<string>();

      list.forEach((m) => {
        const role = roleFromOffice(m.office || "");
        const fixed = fixedSlotFor(role);
        if (fixed) {
          next[m.name] = fixed;
          const fs = FIXED_SLOTS.find((f) => f.role === role);
          if (fs) usedSlots.add(`${fs.side}:${fs.slot}`);
        }
      });

      list.forEach((m) => {
        if (next[m.name]) return;
        if (saved[m.name]) {
          const cur = saved[m.name];
          let best = allSlots.find((s) => !usedSlots.has(`${s.side}:${s.slot}`)) ?? allSlots[0];
          let bestD = Infinity;
          for (const s of allSlots) {
            if (usedSlots.has(`${s.side}:${s.slot}`)) continue;
            const d = Math.hypot(s.px - cur.px, s.py - cur.py);
            if (d < bestD) { bestD = d; best = s; }
          }
          usedSlots.add(`${best.side}:${best.slot}`);
          next[m.name] = { px: best.px, py: best.py };
        } else {
          const slot = allSlots.find((s) => !usedSlots.has(`${s.side}:${s.slot}`));
          if (slot) {
            usedSlots.add(`${slot.side}:${slot.slot}`);
            next[m.name] = { px: slot.px, py: slot.py };
          } else {
            next[m.name] = { px: 0.5, py: 0.532 };
          }
        }
      });
      setPositions(next);
    };

    if (savedPosRef.current !== null) {
      arrange(savedPosRef.current);
    } else {
      loadCourtPos().then((saved) => {
        savedPosRef.current = saved;
        arrange(saved);
      });
    }
    return () => { cancelled = true; };
  }, [listKey]);

  const onMouseDown = (e: React.MouseEvent, name: string) => {
    if ((e.target as HTMLElement).closest(".portrait-upload-btn")) return;
    e.preventDefault();
    const pos = positions[name] || { px: 0.5, py: 0.8 };
    dragging.current = { name, startMX: e.clientX, startMY: e.clientY, startPX: pos.px, startPY: pos.py };
    didDrag.current = false;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const dx = ev.clientX - dragging.current.startMX;
      const dy = ev.clientY - dragging.current.startMY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) didDrag.current = true;
      const el = containerRef.current;
      if (!el) return;
      const { width, height } = el.getBoundingClientRect();
      // 拖动增量转百分比
      const npx = Math.max(0, Math.min(1, dragging.current.startPX + dx / width));
      const npy = Math.max(0, Math.min(1, dragging.current.startPY + dy / height));
      setPositions((prev) => {
        const next = { ...prev, [dragging.current!.name]: { px: npx, py: npy } };
        savedPosRef.current = next;
        saveCourtPos(next);
        return next;
      });
    };
    const onUp = () => {
      if (dragging.current && didDrag.current) {
        // 松手时吸附到最近槽位
        const dragName = dragging.current.name;
        setPositions((prev) => {
          const cur = prev[dragName];
          if (!cur) return prev;
          // 已占槽位（其他大臣）
          const occupied = new Set<string>();
          // 找吸附目标
          const snapped = snapToSlot(cur.px, cur.py, occupied, "");
          const next = { ...prev, [dragName]: snapped };
          savedPosRef.current = next;
          saveCourtPos(next);
          return next;
        });
      }
      dragging.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  if (!list.length) return <div className={courtMode ? "minister-list minister-list-court" : "minister-list"}><div className="empty-note">{emptyNote}</div></div>;

  // 非朝班模式（全部tab）：普通网格
  if (!courtMode) {
    return (
      <div className="minister-list">
        {list.map((minister) => {
          const isCustom = minister.portrait_id?.startsWith("custom:");
          const dedicated = isCustom
            ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
            : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`;
          const poolFallback = !isCustom && minister.portrait_id ? `/portraits/${minister.portrait_id}.png` : undefined;
          const ousted = minister.status !== "active";
          return (
            <button key={minister.name}
              className={`minister-card ${selectedMinister === minister.name ? "selected" : ""} ${ousted ? "ousted" : ""}`}
              onClick={() => onOpenChat(minister)}>
              <div className="minister-card-portrait-wrap">
                <MinisterPortrait primary={dedicated} fallback={poolFallback} name={minister.name} />
                {onUploadPortrait && <PortraitUploadButton ministerName={minister.name} onUpload={onUploadPortrait} />}
              </div>
              <div className="minister-card-info">
                <div className="minister-card-top">
                  <span className="minister-name">{minister.name}</span>
                  {ousted && <span className={`minister-status status-${minister.status}`}>{minister.status_label}</span>}
                  {minister.office && <span className="minister-office">{minister.office}</span>}
                </div>
                <span className="minister-bio">{minister.summary}</span>
              </div>
              {minister.favorite && <Star className="favorite-mark" size={13} />}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="minister-list minister-list-court" ref={containerRef}>
      {list.map((minister) => {
        const isCustom = minister.portrait_id?.startsWith("custom:");
        const dedicated = isCustom
          ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
          : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`;
        const poolFallback = !isCustom && minister.portrait_id
          ? `/portraits/${minister.portrait_id}.png`
          : undefined;
        const ousted = minister.status !== "active";
        const pct = positions[minister.name];
        // 透视缩放：py=0最远最小，py=1最近最大
        const perspScale = pct ? 0.38 + 0.62 * pct.py : 1;
        // 卡片宽用 vh 单位（CSS），这里只控制 scale
        return (
          <button
            key={minister.name}
            className={`minister-card ${selectedMinister === minister.name ? "selected" : ""} ${ousted ? "ousted" : ""}`}
            style={pct ? {
              position: "absolute",
              left: `${pct.px * 100}%`,
              top: `${pct.py * 100}%`,
              cursor: "grab",
              transform: `scale(${perspScale.toFixed(3)})`,
              transformOrigin: "bottom center",
              zIndex: Math.round(pct.py * 1000),
            } : { visibility: "hidden" }}
            onMouseDown={(e) => onMouseDown(e, minister.name)}
            onClick={(e) => { if (didDrag.current) { e.preventDefault(); return; } onOpenChat(minister); }}
          >
            <div className="minister-card-portrait-wrap">
              <MinisterPortrait primary={dedicated} fallback={poolFallback} name={minister.name} />
              {onUploadPortrait && (
                <PortraitUploadButton ministerName={minister.name} onUpload={onUploadPortrait} />
              )}
            </div>
            <div className="minister-card-info">
              <div className="minister-card-top">
                <span className="minister-name">{minister.name}</span>
                {ousted && <span className={`minister-status status-${minister.status}`}>{minister.status_label}</span>}
                {minister.office && <span className="minister-office">{minister.office}</span>}
              </div>
              <span className="minister-bio">{minister.summary}</span>
            </div>
            {minister.favorite && <Star className="favorite-mark" size={13} />}
          </button>
        );
      })}
    </div>
  );
}


export function ArmyDrawer({
  armies,
  open,
  selectedArmyId,
  onSelectArmy,
  onClose,
}: {
  armies: Army[];
  open: boolean;
  selectedArmyId: string;
  onSelectArmy: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const mingArmies = armies.filter((a) => (a.owner_power || "ming") === "ming");
  const filtered = q ? mingArmies.filter((a) => a.name.includes(q) || a.station.includes(q) || a.commander.includes(q)) : mingArmies;
  const selected = mingArmies.find((a) => a.id === selectedArmyId) || null;
  const arrearsTone = (army: Army) => {
    const maint = army.maintenance_per_turn || 1;
    const months = army.arrears / maint;
    if (months >= 3) return "danger";
    if (months >= 1) return "warn";
    return "";
  };
  return (
    <RightDrawer open={open} onClose={onClose} title="军队" icon={<Swords size={17} />} extraClass="right-drawer-army">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索番号/驻地/统帅…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {filtered.map((army) => (
          <button
            key={army.id}
            className={`right-drawer-row${selectedArmyId === army.id ? " selected" : ""} ${arrearsTone(army)}`}
            onClick={() => onSelectArmy(army.id === selectedArmyId ? "" : army.id)}
          >
            <span className="right-drawer-row-name">{army.name}</span>
            <span className="right-drawer-row-meta">
              {army.manpower}兵 · {army.station}
            </span>
          </button>
        ))}
        {!filtered.length && <div className="empty-note">{q ? "无匹配结果。" : "暂无大明军队记录。"}</div>}
      </div>
      {selected && (
        <div className="right-drawer-detail">
          <div className="right-drawer-detail-title">
            {selected.name}
            <button className="right-drawer-detail-close" onClick={() => onSelectArmy("")} aria-label="关闭详情"><X size={14} /></button>
          </div>
          <table className="intel-table">
            <tbody>
              <tr><th>驻地</th><td>{selected.station}</td><th>战区</th><td>{selected.theater}</td></tr>
              <tr><th>统帅</th><td>{selected.commander || "—"}</td><th>兵种</th><td>{selected.troop_type}</td></tr>
              <tr><th>兵力</th><td>{selected.manpower}</td><th>月饷</th><td>{selected.maintenance_per_turn}万</td></tr>
              <tr><th>士气</th><td>{selected.morale}</td><th>操练</th><td>{selected.training}</td></tr>
              <tr><th>军械</th><td>{selected.equipment}</td><th>补给</th><td>{selected.supply}</td></tr>
              <tr><th>机动</th><td>{selected.mobility}</td><th>忠诚</th><td>{selected.loyalty}</td></tr>
              <tr><th>欠饷</th><td colSpan={3}>
                {selected.arrears > 0
                  ? `${selected.arrears}万两（≈${(selected.arrears / (selected.maintenance_per_turn || 1)).toFixed(1)}月）`
                  : "无欠饷"}
              </td></tr>
              <tr><th>状态</th><td colSpan={3}>{selected.status}</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </RightDrawer>
  );
}

export function RegionDrawer({
  regions,
  open,
  selectedRegionId,
  onSelectRegion,
  onClose,
}: {
  regions: Region[];
  open: boolean;
  selectedRegionId: string;
  onSelectRegion: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const mingRegions = regions.filter((r) => (r.controlled_by || "ming") === "ming");
  const filtered = q ? mingRegions.filter((r) => r.name.includes(q)) : mingRegions;
  const selected = mingRegions.find((r) => r.id === selectedRegionId) || null;
  const regionTone = (r: Region) => {
    if (r.unrest >= 70) return "danger";
    if (r.unrest >= 45) return "warn";
    return "";
  };
  return (
    <RightDrawer open={open} onClose={onClose} title="省份" icon={<MapPinned size={17} />} extraClass="right-drawer-region">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索省份名…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {filtered.map((r) => (
          <button
            key={r.id}
            className={`right-drawer-row${selectedRegionId === r.id ? " selected" : ""} ${regionTone(r)}`}
            onClick={() => onSelectRegion(r.id === selectedRegionId ? "" : r.id)}
          >
            <span className="right-drawer-row-name">{r.name}</span>
            <span className="right-drawer-row-meta">
              动乱{r.unrest} · 月税{r.tax_per_turn}万
            </span>
          </button>
        ))}
        {!filtered.length && <div className="empty-note">{q ? "无匹配结果。" : "暂无大明省份记录。"}</div>}
      </div>
      {selected && (
        <div className="right-drawer-detail">
          <div className="right-drawer-detail-title">
            {selected.name}
            <button className="right-drawer-detail-close" onClick={() => onSelectRegion("")} aria-label="关闭详情"><X size={14} /></button>
          </div>
          <table className="intel-table">
            <tbody>
              <tr><th>人口</th><td>{selected.population}万</td><th>田亩</th><td>{selected.registered_land}万亩</td></tr>
              <tr><th>民心</th><td>{selected.public_support}</td><th>动乱</th><td>{selected.unrest}</td></tr>
              <tr><th>粮食</th><td>{selected.grain_security}</td><th>月税</th><td>{selected.tax_per_turn}万</td></tr>
              <tr><th>士绅阻力</th><td>{selected.gentry_resistance}</td><th>边防压力</th><td>{selected.military_pressure}</td></tr>
              <tr><th>天灾</th><td colSpan={3}>{selected.natural_disaster}</td></tr>
              <tr><th>人祸</th><td colSpan={3}>{selected.human_disaster}</td></tr>
              <tr><th>状况</th><td colSpan={3}>{selected.status}</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </RightDrawer>
  );
}

export function BuildingDrawer({
  regions,
  mapNodes,
  open,
  onClose,
}: {
  regions: Region[];
  mapNodes: MapNode[];
  open: boolean;
  onClose: () => void;
}) {
  const allBuildings: (Building & { regionName: string })[] = [];
  for (const node of mapNodes) {
    if (!node.buildings) continue;
    const regionName = node.region?.name || node.label || node.id;
    for (const b of node.buildings) {
      allBuildings.push({ ...b, regionName });
    }
  }
  const [filterRegion, setFilterRegion] = React.useState("");
  const [q, setQ] = React.useState("");
  const regionNames = Array.from(new Set(allBuildings.map((b) => b.regionName)));
  const filtered = allBuildings
    .filter((b) => !filterRegion || b.regionName === filterRegion)
    .filter((b) => !q || b.name.includes(q) || b.category.includes(q));
  return (
    <RightDrawer open={open} onClose={onClose} title="建筑" icon={<Landmark size={17} />} extraClass="right-drawer-building">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索建筑名/类别…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-filter">
        <select
          value={filterRegion}
          onChange={(e) => setFilterRegion(e.target.value)}
          className="right-drawer-select"
        >
          <option value="">全部省份</option>
          {regionNames.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <div className="right-drawer-list">
        {filtered.map((b) => (
          <div key={b.id} className="right-drawer-row right-drawer-row-building">
            <span className="right-drawer-row-name">{b.name}</span>
            <span className="right-drawer-row-meta">{b.regionName} · {b.category} Lv{b.level}</span>
            <span className="right-drawer-row-sub">
              完好{b.condition} · 维护{b.maintenance}万/月
              {b.output_metric ? ` · ${b.output_metric}+${b.output_amount}` : ""}
            </span>
          </div>
        ))}
        {!filtered.length && <div className="empty-note">{q || filterRegion ? "无匹配结果。" : "暂无建筑记录。"}</div>}
      </div>
    </RightDrawer>
  );
}

export function EconomyDrawer({
  state,
  open,
  onClose,
}: {
  state: GameState;
  open: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = React.useState<"国库" | "内库">("国库");
  const [q, setQ] = React.useState("");
  const budget = state.budget[tab];
  const matchItem = (name: string) => !q || name.includes(q);
  return (
    <RightDrawer open={open} onClose={onClose} title="经济" icon={<ScrollText size={17} />} extraClass="right-drawer-economy">
      <div className="segmented right-drawer-segmented">
        {(["国库", "内库"] as const).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索收支项…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-economy-summary">
        <span>余额 <b>{formatMoney(budget.balance)}</b></span>
        <span className={budget.net >= 0 ? "income" : "expense"}>
          月净 <b>{formatSignedMoney(budget.net)}</b>
        </span>
      </div>
      <div className="right-drawer-list">
        <div className="right-drawer-section-title">固定收入</div>
        {budget.income.filter((item) => matchItem(item.name)).map((item) => (
          <div key={`in-${item.name}`} className="right-drawer-budget-row">
            <span>{item.name}</span>
            <b className="income">+{formatMoney(item.amount)}</b>
          </div>
        ))}
        <div className="right-drawer-section-title">固定支出</div>
        {budget.expense.filter((item) => matchItem(item.name)).map((item) => (
          <div key={`ex-${item.name}`} className="right-drawer-budget-row">
            <span>{item.name}</span>
            <b className="expense">-{formatMoney(item.amount)}</b>
          </div>
        ))}
        {budget.movements.filter((m) => matchItem(m.category || m.reason)).length > 0 && (
          <>
            <div className="right-drawer-section-title">本月一次性入账</div>
            {budget.movements.filter((m) => matchItem(m.category || m.reason)).map((m, i) => (
              <div key={`mv-${i}`} className="right-drawer-budget-row">
                <span>{m.category || m.reason}</span>
                <b className={m.delta >= 0 ? "income" : "expense"}>{formatSignedMoney(m.delta)}</b>
              </div>
            ))}
          </>
        )}
      </div>
    </RightDrawer>
  );
}

export function AppointmentDrawer({
  ministers,
  open,
  onOpenChat,
  onClose,
}: {
  ministers: Minister[];
  open: boolean;
  onOpenChat: (minister: Minister) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const offices = ["内阁", "吏部", "户部", "礼部", "兵部", "刑部", "工部"];
  const byOffice = new Map<string, Minister[]>();
  for (const office of offices) byOffice.set(office, []);
  byOffice.set("其他", []);
  for (const m of ministers) {
    if ((m.power_id || "ming") !== "ming") continue;
    if (m.status !== "active") continue;
    if (q && !m.name.includes(q) && !(m.office || "").includes(q) && !(m.office_type || "").includes(q)) continue;
    const matched = offices.find((o) => (m.office_type || "").includes(o));
    const key = matched || "其他";
    byOffice.get(key)!.push(m);
  }
  return (
    <RightDrawer open={open} onClose={onClose} title="官员任免" icon={<Star size={17} />} extraClass="right-drawer-appointment">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索姓名/职位…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {[...offices, "其他"].map((office) => {
          const group = byOffice.get(office) || [];
          if (!group.length) return null;
          return (
            <div key={office}>
              <div className="right-drawer-section-title">{office}</div>
              {group.map((m) => (
                <button
                  key={m.name}
                  className="right-drawer-row right-drawer-row-minister"
                  onClick={() => onOpenChat(m)}
                >
                  <div className="right-drawer-minister-row">
                    <span className="right-drawer-row-name">{m.name}</span>
                    <span className="right-drawer-minister-office">{m.office || m.office_type}</span>
                  </div>
                </button>
              ))}
            </div>
          );
        })}
        {[...offices, "其他"].every((o) => !(byOffice.get(o) || []).length) && (
          <div className="empty-note">{q ? "无匹配结果。" : "暂无在职官员。"}</div>
        )}
      </div>
    </RightDrawer>
  );
}

export function CourtDrawer({
  state: _state,
  ministers,
  ministerGroup,
  selectedMinister,
  open,
  onGroupChange,
  onClose,
  onOpenChat,
  onUploadPortrait,
}: {
  state: GameState;
  ministers: Minister[];
  ministerGroup: string;
  selectedMinister: string;
  open: boolean;
  onGroupChange: (group: string) => void;
  onClose: () => void;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait: (ministerName: string, file: File) => Promise<void>;
}) {
  const [q, setQ] = React.useState("");
  const filtered = q ? ministers.filter((m) => m.name.includes(q) || (m.office || "").includes(q)) : ministers;
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="收起" onClick={onClose} />}
      <aside className={`court-drawer ${open ? "open" : ""}`}>
        <div className="drawer-brand">
          <div className="panel-title">
            <Landmark size={17} />
            <span>朝堂</span>
          </div>
          <button className="icon-button" aria-label="收起" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="segmented">
          {["内阁+六部", "收藏", "在职", "全部"].map((group) => (
            <button
              className={ministerGroup === group ? "active" : ""}
              key={group}
              onClick={() => onGroupChange(group)}
            >
              {group}
            </button>
          ))}
        </div>
        <div className="right-drawer-search court-search">
          <input className="right-drawer-search-input" placeholder="搜索姓名/职位…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <MinisterCardList
          list={filtered}
          portraitPrefix="minister_"
          selectedMinister={selectedMinister}
          emptyNote={q ? "无匹配大臣。" : "此栏暂无可召见大臣。"}
          onOpenChat={onOpenChat}
          courtMode={ministerGroup === "内阁+六部" || ministerGroup === "收藏"}
          onUploadPortrait={onUploadPortrait}
        />
      </aside>
    </>
  );
}

export function HaremDrawer({
  consorts,
  haremGroup,
  selectedMinister,
  open,
  onGroupChange,
  onClose,
  onOpenChat,
  onUploadPortrait,
}: {
  consorts: Minister[];
  haremGroup: string;
  selectedMinister: string;
  open: boolean;
  onGroupChange: (group: string) => void;
  onClose: () => void;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait: (ministerName: string, file: File) => Promise<void>;
}) {
  const [q, setQ] = React.useState("");
  const filtered = q ? consorts.filter((c) => c.name.includes(q)) : consorts;
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="收起" onClick={onClose} />}
      <aside className={`court-drawer harem-drawer overlay-panel ${open ? "open" : ""}`}>
        <div className="drawer-brand">
          <div className="panel-title">
            <Crown size={17} />
            <span>后宫</span>
          </div>
          <button className="icon-button" aria-label="收起" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="segmented">
          {["全部", "收藏"].map((group) => (
            <button
              className={haremGroup === group ? "active" : ""}
              key={group}
              onClick={() => onGroupChange(group)}
            >
              {group}
            </button>
          ))}
        </div>
        <div className="right-drawer-search court-search">
          <input className="right-drawer-search-input" placeholder="搜索姓名…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <MinisterCardList
          list={filtered}
          portraitPrefix="consort_"
          selectedMinister={selectedMinister}
          emptyNote={q ? "无匹配结果。" : "后宫暂无可召见之人。"}
          onOpenChat={onOpenChat}
          onUploadPortrait={onUploadPortrait}
        />
      </aside>
    </>
  );
}

