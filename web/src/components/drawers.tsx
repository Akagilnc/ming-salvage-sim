import React from "react";
import { Crown, Landmark, MapPinned, ScrollText, Star, Swords, X } from "lucide-react";
import { MinisterPortrait, PortraitUploadButton, RightDrawer, cacheBust, courtSlots, loadCourtPos, saveCourtPos, snapToSlot } from "./hud";
import { formatMoney, formatSignedMoney, qualitativeArmyStat } from "../format";
import { settlementClosedReason } from "../settlementPresentation";
import type { Army, Building, GameState, MapNode, Minister, Region } from "../types";

export function MinisterCardList({
  list,
  portraitPrefix,
  selectedMinister,
  emptyNote,
  onOpenChat,
  onUploadPortrait,
  courtMode = false,
  chatEntryEnabled = true,
  phase,
}: {
  list: Minister[];
  portraitPrefix: string;
  selectedMinister: string;
  emptyNote: string;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait?: (ministerName: string, file: File) => Promise<void>;
  courtMode?: boolean;
  /** #1236：核账期拔召对写入口，名册仍只读保留。 */
  chatEntryEnabled?: boolean;
  /** #1323：关闭理由按 phase 分口吻（awaiting≠核账）。 */
  phase?: string;
}) {
  const closedTitle = chatEntryEnabled ? undefined : settlementClosedReason(phase);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [positions, setPositions] = React.useState<Record<string, { px: number; py: number }>>({});
  /** #1463：已提交基线（null=GET 未回）；脏键与 pending 是其上的本地增量，合并/保存只走这一真源。 */
  const baselineRef = React.useRef<Record<string, { px: number; py: number }> | null>(null);
  const dirtyRef = React.useRef<Record<string, { px: number; py: number }>>({});
  const pendingSaveRef = React.useRef(false);
  const positionsRef = React.useRef(positions);
  positionsRef.current = positions;
  const listRef = React.useRef(list);
  listRef.current = list;
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

  // 视位 = 已提交基线 ∪ 脏键（GET 前基线当 {}）。
  const viewLayout = React.useCallback(
    () => ({ ...(baselineRef.current || {}), ...dirtyRef.current }),
    [],
  );

  const arrange = React.useCallback((saved: Record<string, { px: number; py: number }>) => {
    const curList = listRef.current;
    const allSlots = courtSlots();
    const next: Record<string, { px: number; py: number }> = {};
    const usedSlots = new Set<string>();

    // 固定槽：同 role 仅首名占座，次名起留给下方自由槽分配（ADR 0064 同衔并存合法，呈现层去叠）
    curList.forEach((m) => {
      const role = roleFromOffice(m.office || "");
      const fixed = fixedSlotFor(role);
      if (!fixed) return;
      const fs = FIXED_SLOTS.find((f) => f.role === role);
      if (!fs) return;
      const key = `${fs.side}:${fs.slot}`;
      if (usedSlots.has(key)) return; // 次名起降级自由槽
      next[m.name] = fixed;
      usedSlots.add(key);
    });

    curList.forEach((m) => {
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
  }, []);

  // 合并脏键入基线并 POST 一次——唯一保存真源。
  const commitSave = React.useCallback(() => {
    const merged = viewLayout();
    baselineRef.current = merged;
    dirtyRef.current = {};
    saveCourtPos(merged);
  }, [viewLayout]);

  // #1463：布局加载只随挂载/卸载，不被 list 重排 cancel。
  // #1499：loadCourtPos 已捕获 fetch/HTTP/parse 异常并 resolve {}，
  // 无需平行 reject 分支（重复护栏）；GET 空 {} 合法，回包即基线。
  React.useEffect(() => {
    let cancelled = false;
    // #1290/#1332：先默认落座不堵首屏，回包再合并脏键。
    loadCourtPos().then((saved) => {
      if (cancelled) return;
      baselineRef.current = saved;
      arrange(viewLayout());
      if (pendingSaveRef.current) {
        pendingSaveRef.current = false;
        commitSave();
      }
    });
    return () => { cancelled = true; };
  }, [arrange, viewLayout, commitSave]);

  // list 变化只重排，不重 fetch。
  const listKey = list.map((m) => m.name).join("|");
  React.useEffect(() => {
    arrange(viewLayout());
  }, [listKey, arrange, viewLayout]);

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
        // 拖动中只更新视图与脏键，不写库——一次拖动数十个 mousemove，
        // fire-and-forget POST 乱序到达会让旧坐标覆盖新坐标；持久化只在松手时做一次。
        const name = dragging.current!.name;
        const pos = { px: npx, py: npy };
        dirtyRef.current = { ...dirtyRef.current, [name]: pos };
        return { ...prev, [name]: pos };
      });
    };
    const onUp = () => {
      if (dragging.current && didDrag.current) {
        // 松手时吸附到最近槽位。
        // #1499-F1：updater 纯函数——吸附/脏键/commit 均在 setState 外计算，
        // 避免 StrictMode 双调 updater 导致 POST 两发或 ref/视图失同步。
        const dragName = dragging.current.name;
        const prev = positionsRef.current;
        const cur = prev[dragName] ?? dirtyRef.current[dragName];
        if (cur) {
          // 固定官职：固定槽空着才弹回；已被他人占用则降级自由吸附（避免拖完与同衔复叠）
          const dragMinister = list.find((m) => m.name === dragName);
          const role = dragMinister ? roleFromOffice(dragMinister.office || "") : "";
          const fs = role ? FIXED_SLOTS.find((f) => f.role === role) : undefined;
          const fixedKey = fs ? `${fs.side}:${fs.slot}` : "";
          // 已占槽位（其他大臣按各自当前位置归入最近槽）
          const allSlots = courtSlots();
          const occupied = new Set<string>();
          Object.entries(prev).forEach(([name, p]) => {
            if (name === dragName) return;
            let bestKey = "";
            let bestD = Infinity;
            for (const s of allSlots) {
              const d = Math.hypot(s.px - p.px, s.py - p.py);
              if (d < bestD) { bestD = d; bestKey = `${s.side}:${s.slot}`; }
            }
            if (bestKey) occupied.add(bestKey);
          });
          const fixed = fixedKey && !occupied.has(fixedKey) ? fixedSlotFor(role) : null;
          const snapped = fixed ?? snapToSlot(cur.px, cur.py, occupied, "");
          const next = { ...prev, [dragName]: snapped };
          dirtyRef.current = { ...dirtyRef.current, [dragName]: snapped };
          positionsRef.current = next;
          setPositions(next);
          // #1463：基线未就绪则挂 pending，合并后再走唯一 commitSave；就绪则立即提交。
          if (baselineRef.current === null) {
            pendingSaveRef.current = true;
          } else {
            commitSave();
          }
        }
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
              type="button"
              className={`minister-card ${selectedMinister === minister.name ? "selected" : ""} ${ousted ? "ousted" : ""}`}
              disabled={!chatEntryEnabled}
              aria-disabled={!chatEntryEnabled}
              title={closedTitle}
              onClick={() => { if (chatEntryEnabled) onOpenChat(minister); }}>
              <div className="minister-card-portrait-wrap">
                <MinisterPortrait primary={dedicated} fallback={poolFallback} name={minister.name} />
                {onUploadPortrait && chatEntryEnabled && <PortraitUploadButton ministerName={minister.name} onUpload={onUploadPortrait} />}
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
            type="button"
            className={`minister-card ${selectedMinister === minister.name ? "selected" : ""} ${ousted ? "ousted" : ""}`}
            style={pct ? {
              position: "absolute",
              left: `${pct.px * 100}%`,
              top: `${pct.py * 100}%`,
              cursor: chatEntryEnabled ? "grab" : "default",
              transform: `scale(${perspScale.toFixed(3)})`,
              transformOrigin: "bottom center",
              zIndex: Math.round(pct.py * 1000),
            } : { visibility: "hidden" }}
            onMouseDown={(e) => { if (chatEntryEnabled) onMouseDown(e, minister.name); }}
            disabled={!chatEntryEnabled}
            aria-disabled={!chatEntryEnabled}
            title={closedTitle}
            onClick={(e) => {
              if (!chatEntryEnabled) return;
              if (didDrag.current) { e.preventDefault(); return; }
              onOpenChat(minister);
            }}
          >
            <div className="minister-card-portrait-wrap">
              <MinisterPortrait primary={dedicated} fallback={poolFallback} name={minister.name} />
              {onUploadPortrait && chatEntryEnabled && (
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
  return (
    <RightDrawer open={open} onClose={onClose} title="军队" icon={<Swords size={17} />} extraClass="right-drawer-army">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索番号/驻地/统帅…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {filtered.map((army) => (
          <button
            key={army.id}
            className={`right-drawer-row${selectedArmyId === army.id ? " selected" : ""}`}
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
              <tr><th>兵力</th><td>{selected.manpower}</td><th>月饷</th><td>{selected.army_needed}万</td></tr>
              {/* #321 P7：mutiny_tier/morale_text/arrears_text 不直显；走 LLM 输入链 */}
              <tr><th>操练</th><td>{qualitativeArmyStat("training", selected.training)}</td><th>军械</th><td>{qualitativeArmyStat("equipment", selected.equipment)}</td></tr>
              <tr><th>补给</th><td>{qualitativeArmyStat("supply", selected.supply)}</td><th>机动</th><td>{qualitativeArmyStat("mobility", selected.mobility)}</td></tr>
              {/* #1501：军牌不渲染静态 status 句 */}
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
              <tr><th>田亩</th><td colSpan={3}>{selected.registered_land}万亩</td></tr>
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
  chatEntryEnabled = true,
  phase,
}: {
  ministers: Minister[];
  open: boolean;
  onOpenChat: (minister: Minister) => void;
  onClose: () => void;
  /** #1236：核账期拔任免行召对写入口。 */
  chatEntryEnabled?: boolean;
  /** #1323：关闭理由按 phase 分口吻（awaiting≠核账）。 */
  phase?: string;
}) {
  const [q, setQ] = React.useState("");
  const closedTitle = chatEntryEnabled ? undefined : settlementClosedReason(phase);
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
                  type="button"
                  className="right-drawer-row right-drawer-row-minister"
                  disabled={!chatEntryEnabled}
                  aria-disabled={!chatEntryEnabled}
                  title={closedTitle}
                  onClick={() => { if (chatEntryEnabled) onOpenChat(m); }}
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
  state,
  ministers,
  ministerGroup,
  selectedMinister,
  open,
  onGroupChange,
  onClose,
  onOpenChat,
  onUploadPortrait,
  chatEntryEnabled = true,
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
  /** #1236：核账期拔召对写入口，名册只读。 */
  chatEntryEnabled?: boolean;
}) {
  const [q, setQ] = React.useState("");
  const filtered = q ? ministers.filter((m) => m.name.includes(q) || (m.office || "").includes(q)) : ministers;
  const phase = state.turn.phase;
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
          {["内阁+六部", "收藏", "在职", "全部", "在野"].map((group) => (
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
          emptyNote={q ? "无匹配大臣。" : (ministerGroup === "在野" ? "暂无在野前臣可起复。" : "此栏暂无可召见大臣。")}
          onOpenChat={onOpenChat}
          courtMode={ministerGroup === "内阁+六部" || ministerGroup === "收藏"}
          onUploadPortrait={onUploadPortrait}
          chatEntryEnabled={chatEntryEnabled}
          phase={phase}
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
  chatEntryEnabled = true,
  phase,
}: {
  consorts: Minister[];
  haremGroup: string;
  selectedMinister: string;
  open: boolean;
  onGroupChange: (group: string) => void;
  onClose: () => void;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait: (ministerName: string, file: File) => Promise<void>;
  /** #1236：核账期拔召对写入口，名册只读。 */
  chatEntryEnabled?: boolean;
  /** #1323：关闭理由按 phase 分口吻（awaiting≠核账）。 */
  phase?: string;
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
          chatEntryEnabled={chatEntryEnabled}
          phase={phase}
        />
      </aside>
    </>
  );
}
