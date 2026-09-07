import React from "react";

/** #1794：设置页附加请求头表（名/值）。不做校验/白名单/默认行；空名行保存时跳过。 */
export type HeaderRow = { id: string; name: string; value: string };

let headerRowSeq = 0;

export function newHeaderRow(name = "", value = ""): HeaderRow {
  headerRowSeq += 1;
  return { id: `hdr-${headerRowSeq}`, name, value };
}

export function headersToRows(headers?: Record<string, string> | null): HeaderRow[] {
  return Object.entries(headers || {}).map(([name, value]) => newHeaderRow(name, value));
}

export function rowsToHeaders(rows: HeaderRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    if (row.name === "") continue;
    out[row.name] = row.value;
  }
  return out;
}

export function DefaultHeadersField({
  rows,
  onChange,
  variant = "game",
}: {
  rows: HeaderRow[];
  onChange: (next: HeaderRow[]) => void;
  variant?: "game" | "menu";
}) {
  const updateRow = (id: string, patch: Partial<Pick<HeaderRow, "name" | "value">>) => {
    onChange(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };
  const removeRow = (id: string) => onChange(rows.filter((row) => row.id !== id));
  const addRow = () => onChange([...rows, newHeaderRow()]);

  return (
    <div className={variant === "menu" ? "menu-cli-field menu-headers-field" : "menu-field menu-headers-field"}>
      <span>附加请求头 <small className="menu-hint">（名/值原样保存；空表＝不附加）</small></span>
      {rows.map((row) => (
        <div className="menu-row menu-header-row" key={row.id}>
          <input
            className={variant === "game" ? "menu-input" : undefined}
            aria-label="请求头名"
            value={row.name}
            onChange={(e) => updateRow(row.id, { name: e.target.value })}
            placeholder="Header-Name"
            autoComplete="off"
          />
          <input
            className={variant === "game" ? "menu-input" : undefined}
            aria-label="请求头值"
            value={row.value}
            onChange={(e) => updateRow(row.id, { value: e.target.value })}
            placeholder="value"
            autoComplete="off"
          />
          {variant === "game" ? (
            <button
              type="button"
              className="menu-btn"
              aria-label="删除请求头行"
              onClick={() => removeRow(row.id)}
            >
              删
            </button>
          ) : (
            <button type="button" aria-label="删除请求头行" onClick={() => removeRow(row.id)}>
              删
            </button>
          )}
        </div>
      ))}
      {variant === "game" ? (
        <button type="button" className="menu-btn" onClick={addRow}>
          增行
        </button>
      ) : (
        <button type="button" className="menu-headers-add" onClick={addRow}>
          增行
        </button>
      )}
    </div>
  );
}
