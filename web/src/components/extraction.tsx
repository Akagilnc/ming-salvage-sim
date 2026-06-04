import React from "react";
import { api } from "../api";
import { FullscreenModal } from "./hud";
import { SAT_LEV_CN, cnField, cnValue, fiscalKeyLabel, labelArmy, labelClass, labelIssue, labelPower, labelRegion } from "../format";
import type { ExtractionData } from "../types";

export function ExtractionModal({ onClose }: { onClose: () => void }) {
  const [extraction, setExtraction] = React.useState<ExtractionData | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch("/api/turn_extraction");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (alive) setExtraction(data);
      } catch (e: any) {
        if (alive) setError(e?.message || "加载失败");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  return (
    <FullscreenModal title="邸报详明" subtitle="数项加减/账目明细" bgClass="modal-bg-state" onClose={onClose}>
      <article className="state-document modal-scroll">
        <ExtractionView data={extraction} loading={loading} error={error} />
      </article>
    </FullscreenModal>
  );
}

export function ExtractionView({ data, loading, error }: { data: ExtractionData | null; loading: boolean; error: string }) {
  if (loading) return <div className="document-section"><p className="long-copy">加载中…</p></div>;
  if (error) return <div className="document-section"><p className="long-copy">加载失败：{error}</p></div>;
  if (!data || !data.exists) return <div className="document-section"><p className="long-copy">该回合无 extractor 数据。</p></div>;
  const rawOut = data.extractor_output;
  if (!rawOut || typeof rawOut !== "object") {
    return <div className="document-section"><pre className="memorial-text">{String(rawOut ?? "")}</pre></div>;
  }
  // modular 结构：数据在 merged（已合并扁平），顶层只有 mode/modules/merged/raw。老存档是扁平对象，直接用。
  const out = (rawOut as any).mode === "modular" && (rawOut as any).merged && typeof (rawOut as any).merged === "object"
    ? (rawOut as any).merged
    : rawOut;
  return (
    <div className="document-section extraction-view">
      <ExtractionSection title="国势变化">
        <MetricDeltaBlock data={pickField(out, "国势变化", "metric_delta")} />
      </ExtractionSection>
      <ExtractionSection title="钱粮收支">
        <EconomyBlock data={pickField(out, "钱粮收支", "economy_moves")} />
      </ExtractionSection>
      <ExtractionSection title="派系变化">
        <FactionBlock data={pickField(out, "派系变化", "faction_delta")} />
      </ExtractionSection>
      <ExtractionSection title="阶级变化">
        <ClassDeltaBlock data={pickField(out, "阶级变化", "class_delta")} />
      </ExtractionSection>
      <ExtractionSection title="官职任免">
        <OfficeChangesBlock data={pickField(out, "人事变更", "office_changes")} />
      </ExtractionSection>
      <ExtractionSection title="去职变更">
        <StatusChangesBlock data={pickField(out, "人物状态变化", "character_status_changes")} />
      </ExtractionSection>
      <ExtractionSection title="人物易主">
        <PowerChangesBlock data={pickField(out, "人物易主", "character_power_changes")} />
      </ExtractionSection>
      <ExtractionSection title="后宫纳妃">
        <AppointmentsBlock data={pickField(out, "后宫册封", "appointments")} />
      </ExtractionSection>
      <ExtractionSection title="局势推进">
        <IssueAdvancesBlock data={pickField(out, "局势推进", "issue_advances")} />
      </ExtractionSection>
      <ExtractionSection title="新立局势">
        <NewIssuesBlock data={pickField(out, "新立局势", "new_issues")} />
      </ExtractionSection>
      <ExtractionSection title="结案 / 失败">
        <CloseIssuesBlock data={pickField(out, "结案局势", "close_issues")} />
      </ExtractionSection>
      <ExtractionSection title="撤旨">
        <CancelsBlock data={pickField(out, "撤销局势", "cancels")} />
      </ExtractionSection>
      <ExtractionSection title="地区变化">
        <EntityDeltaBlock data={pickField(out, "地区变化", "region_delta")} labelFn={labelRegion} />
      </ExtractionSection>
      <ExtractionSection title="军队变化">
        <EntityDeltaBlock data={pickField(out, "军队变化", "army_delta")} labelFn={labelArmy} />
      </ExtractionSection>
      <ExtractionSection title="新建军队">
        <NewArmiesBlock data={pickField(out, "新建军队", "new_armies")} />
      </ExtractionSection>
      <ExtractionSection title="势力变化">
        <EntityDeltaBlock data={pickField(out, "势力变化", "power_updates")} labelFn={labelPower} />
      </ExtractionSection>
      <ExtractionSection title="财政系数">
        <FiscalBlock data={pickField(out, "财政制度变化", "fiscal_changes")} />
      </ExtractionSection>
      <ExtractionSection title="外交关系">
        <DiplomacyBlock data={pickField(out, "外交关系", "world_advance") ?? pickField(out, "外交", "world_advance") ?? pickField(out, "外交态度", "world_advance") ?? pickField(out, "四方动向", "world_advance")} />
      </ExtractionSection>
      <ExtractionSection title="密令副作用">
        <SecretSideBlock data={pickField(out, "密令副作用", "secret_order_updates")} />
      </ExtractionSection>
      <ExtractionSection title="密令核议">
        <SecretCloseBlock data={pickField(out, "密令结案", "secret_order_closes")} />
      </ExtractionSection>
    </div>
  );
}

export function pickField(obj: any, cn: string, en: string): any {
  if (!obj || typeof obj !== "object") return undefined;
  return obj[cn] ?? obj[en];
}

export function pickItem(obj: any, cn: string, en: string): any {
  if (!obj || typeof obj !== "object") return undefined;
  return obj[cn] ?? obj[en];
}

export function ExtractionSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="extraction-section">
      <h3 className="extraction-section-title">{title}</h3>
      <div className="extraction-section-body">{children}</div>
    </section>
  );
}

export function fmtDelta(n: any): string {
  // 缺失/非数（extractor 偶尔不带 delta_bar）按 0 处理，避免渲染出字面 "undefined"
  const num = Number(n);
  if (!Number.isFinite(num)) return "0";
  if (num > 0) return `+${num}`;
  return String(num);
}

export function isEmptyData(d: any): boolean {
  if (d == null) return true;
  if (Array.isArray(d)) return d.length === 0;
  if (typeof d === "object") return Object.keys(d).length === 0;
  return false;
}

export function MetricDeltaBlock({ data }: { data: any }) {
  if (isEmptyData(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([k, v]) => (
        <li key={k}><span>{k}</span><b className={Number(v) >= 0 ? "good" : "bad"}>{fmtDelta(v)}</b></li>
      ))}
    </ul>
  );
}

export function EconomyBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((item: any, i: number) => (
        <li key={i}>
          <b className={Number(pickItem(item, "增量", "delta")) >= 0 ? "good" : "bad"}>
            {pickItem(item, "账户", "account") || "?"} {fmtDelta(pickItem(item, "增量", "delta"))} 万
          </b>
          <span>{pickItem(item, "分类", "category") || ""}{pickItem(item, "原因", "reason") ? ` — ${pickItem(item, "原因", "reason")}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}

export function FactionBlock({ data }: { data: any }) {
  if (isEmptyData(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([k, v]: [string, any]) => {
        if (v && typeof v === "object") {
          return (
            <li key={k}>
              <span>{k}</span>
              <b>{Object.entries(v).map(([kk, vv]) => `${SAT_LEV_CN[kk] || cnField(kk)}${fmtDelta(vv)}`).join("  ")}</b>
            </li>
          );
        }
        return <li key={k}><span>{k}</span><b className={Number(v) >= 0 ? "good" : "bad"}>{fmtDelta(v)}</b></li>;
      })}
    </ul>
  );
}

export function IssueAdvancesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={Number(pickItem(it, "进度增量", "delta_bar")) >= 0 ? "good" : "bad"}>
            {labelIssue(pickItem(it, "局势编号", "issue_id"))} 进度 {fmtDelta(pickItem(it, "进度增量", "delta_bar"))}
            {pickItem(it, "惯性增量", "inertia_delta") ? `，惯性 ${fmtDelta(pickItem(it, "惯性增量", "inertia_delta"))}` : ""}
          </b>
          {pickItem(it, "阶段", "stage_text") ? <span>{pickItem(it, "阶段", "stage_text")}</span> : null}
          {pickItem(it, "叙述", "narrative") ? <span className="extraction-narr">{pickItem(it, "叙述", "narrative")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function NewIssuesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>{pickItem(it, "标题", "title") || pickItem(it, "编号", "id") || "新事项"}（{cnValue(pickItem(it, "类型", "kind") || pickItem(it, "来源类型", "origin_kind") || "")}）</b>
          {pickItem(it, "阶段", "stage_text") ? <span>{pickItem(it, "阶段", "stage_text")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function CloseIssuesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "原因", "reason") === "resolved" ? "good" : "bad"}>
            {labelIssue(pickItem(it, "局势编号", "issue_id"))} {pickItem(it, "原因", "reason") === "resolved" ? "结案" : "失败"}
          </b>
          {pickItem(it, "叙述", "narrative") ? <span>{pickItem(it, "叙述", "narrative")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function CancelsBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>{labelIssue(pickItem(it, "局势编号", "issue_id"))} 撤旨</b>
          {pickItem(it, "叙述", "narrative") ? <span>{pickItem(it, "叙述", "narrative")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function OfficeChangesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "rejected", "rejected") ? "bad" : "good"}>
            {pickItem(it, "姓名", "name")} → {pickItem(it, "新官职", "new_office")}
            {pickItem(it, "新官署类别", "new_office_type") ? `（${pickItem(it, "新官署类别", "new_office_type")}）` : ""}
            {pickItem(it, "rejected", "rejected") ? "（未落地）" : pickItem(it, "kind", "kind") === "appoint" ? "（新进朝堂）" : ""}
          </b>
          {pickItem(it, "displaced", "displaced") ? <span>顶替 {pickItem(it, "displaced", "displaced")} 去职</span> : null}
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function StatusChangesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  const label: Record<string, string> = {
    dismissed: "罢黜", imprisoned: "下狱", exiled: "流放",
    retired: "致仕", dead: "身故", offstage: "去位",
  };
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "rejected", "rejected") ? "bad" : ""}>
            {pickItem(it, "姓名", "name")} {label[pickItem(it, "状态", "status")] || cnValue(pickItem(it, "状态", "status"))}
            {pickItem(it, "rejected", "rejected") ? "（未落地）" : ""}
          </b>
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function AppointmentsBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "rejected", "rejected") ? "bad" : "good"}>
            {pickItem(it, "姓名", "name")} 册封 {pickItem(it, "位号", "office")}
            {pickItem(it, "rejected", "rejected") ? "（未落地）" : ""}
          </b>
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function FiscalBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={Number(pickItem(it, "增量", "delta")) >= 0 ? "good" : "bad"}>
            {fiscalKeyLabel(pickItem(it, "键", "key"))} {fmtDelta(pickItem(it, "增量", "delta"))}
          </b>
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}


// 一个字段值渲染成可读串：数字带正负号，文字直接显示（英文枚举翻中文）。
export function fmtFieldVal(v: any): { text: string; tone: string } {
  if (typeof v === "number") return { text: fmtDelta(v), tone: v >= 0 ? "good" : "bad" };
  const n = Number(v);
  if (v !== "" && v != null && Number.isFinite(n) && String(v).trim() !== "" && !isNaN(n) && /^-?\d+$/.test(String(v).trim())) {
    return { text: fmtDelta(n), tone: n >= 0 ? "good" : "bad" };
  }
  return { text: cnValue(v), tone: "" };
}


// 地区/军队/势力变化：外层 key=实体 id（翻中文名），内层=字段→增量/新值。
export function EntityDeltaBlock({ data, labelFn }: { data: any; labelFn: (id: any) => string }) {
  if (isEmptyData(data) || typeof data !== "object" || Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {Object.entries(data).map(([id, fields]: [string, any]) => (
        <li key={id}>
          <b>{labelFn(id)}</b>
          {fields && typeof fields === "object" && !Array.isArray(fields) ? (
            <span className="extraction-fieldline">
              {Object.entries(fields).map(([fk, fv]) => {
                const { text, tone } = fmtFieldVal(fv);
                return <em key={fk} className={tone}>{cnField(fk)} {text}</em>;
              })}
            </span>
          ) : (
            <span>{cnValue(fields)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}


// 外交关系：key=势力 id（翻中文名），value=态度字符串。
export function DiplomacyBlock({ data }: { data: any }) {
  if (isEmptyData(data) || typeof data !== "object" || Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([id, stance]: [string, any]) => (
        <li key={id}><span>{labelPower(id)}</span><b>{cnValue(stance)}</b></li>
      ))}
    </ul>
  );
}


export function ClassDeltaBlock({ data }: { data: any }) {
  if (isEmptyData(data) || typeof data !== "object" || Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([k, v]: [string, any]) => {
        if (v && typeof v === "object") {
          return (
            <li key={k}>
              <span>{labelClass(k)}</span>
              <b>{Object.entries(v).map(([kk, vv]) => `${SAT_LEV_CN[kk] || cnField(kk)}${fmtDelta(vv)}`).join("  ")}</b>
            </li>
          );
        }
        return <li key={k}><span>{labelClass(k)}</span><b className={Number(v) >= 0 ? "good" : "bad"}>{fmtDelta(v)}</b></li>;
      })}
    </ul>
  );
}


// 人物易主：姓名 → 新势力（翻中文名）。
export function PowerChangesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>{pickItem(it, "姓名", "name")} → {labelPower(pickItem(it, "new_power", "new_power"))}</b>
          {pickItem(it, "reason", "reason") || pickItem(it, "原因", "reason") ? <span>{pickItem(it, "reason", "reason") || pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}


// 密令副作用：active 密令的推演副作用。
export function SecretSideBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>密令 #{pickItem(it, "密令编号", "order_id")}</b>
          <span>{pickItem(it, "推演备注", "sim_note") || ""}</span>
        </li>
      ))}
    </ul>
  );
}


// 密令核议：pending_review 密令结案判定。
export function SecretCloseBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => {
        const st = pickItem(it, "状态", "status");
        return (
          <li key={i}>
            <b className={st === "done" ? "good" : "bad"}>
              密令 #{pickItem(it, "密令编号", "order_id")} {st === "done" ? "办结" : "失败"}
            </b>
            <span>{pickItem(it, "结果", "result") || ""}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function NewArmiesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((item: any, i: number) => {
        const name = pickItem(item, "名称", "name") || pickItem(item, "编号", "id") || "?";
        const owner = labelPower(pickItem(item, "归属", "owner_power")) || "?";
        const manpower = pickItem(item, "人数", "manpower");
        const station = pickItem(item, "驻扎地", "station") || "";
        const commander = pickItem(item, "统将", "commander") || "";
        return (
          <li key={i}>
            <b>{name}</b>（归属：{owner}）{manpower ? ` · ${manpower}人` : ""}
            <span>{station}{commander ? ` · ${commander}` : ""}</span>
          </li>
        );
      })}
    </ul>
  );
}
