import React from "react";
import type { CliModelChoice } from "../types";

// 「其他（手填）」逃生口的下拉哨兵值（绝不会是真实模型 id）。
const CUSTOM = "__custom__";

/**
 * CLI Model 策展下拉 + 手填逃生口。
 *
 * 档位清单单一真源在后端 cli_backend.cli_model_choices()，经 config 端点下发，
 * 这里不硬编完整清单（缺失时仅兜底一个「默认」档保证可渲染）。选「其他（手填）」
 * 露出文本框，老手仍能填任意值（含将来新模型 / 大写 id）——不做小写归一，
 * 可用性由连通性检查兜底。
 *
 * 手填态判定每次渲染重算 `manual || !isKnown`：value 不在当前 runner 策展档内
 * （持久化自定义值 / 将来新模型 / 被 resolved 的非策展值）必显手填框，不依赖一次性
 * 初值，故 value 在异步加载或保存后变化也跟随，不会留下空白下拉（CMR R1 codex）。
 * 调用约定：父级仍须传 `key={runner}` 让 runner 切换时重挂（复位 `manual` 显式手填态），
 * 并在 runner onChange 里把 value 归零（默认档），否则旧 runner 的模型会漏进新 runner。
 */
export function CliModelField({
  runner,
  choices,
  value,
  onChange,
  className,
  ariaLabel = "CLI 模型",
}: {
  runner: string;
  choices?: Record<string, CliModelChoice[]>;
  value: string;
  onChange: (value: string) => void;
  className?: string;
  // 控件无障碍名：本组件外层是 <div>（非 <label>，因 custom 态有两个控件，见调用处注释），
  // 故 select/input 不再有隐式 label 关联，须显式 aria-label 给屏幕阅读器可读名（WCAG，CodeRabbit R3）。
  ariaLabel?: string;
}) {
  const base = choices?.[runner] ?? [];
  const options = base.some((o) => o.value === "")
    ? base
    : [{ value: "", label: "默认" }, ...base];
  const isKnown = options.some((o) => o.value === value);
  // manual = 用户显式点了「其他（手填）」；isKnown=false 时也强制手填态（每渲染重算）。
  const [manual, setManual] = React.useState(false);
  const custom = manual || !isKnown;

  return (
    <>
      <select
        className={className}
        aria-label={ariaLabel}
        value={custom ? CUSTOM : value}
        onChange={(e) => {
          const v = e.target.value;
          if (v === CUSTOM) {
            setManual(true);
          } else {
            setManual(false);
            onChange(v);
          }
        }}
      >
        {options.map((o) => (
          <option key={o.value || "__default__"} value={o.value}>
            {o.label}
          </option>
        ))}
        <option value={CUSTOM}>其他（手填）</option>
      </select>
      {custom ? (
        <input
          className={className}
          aria-label={`${ariaLabel}（手填）`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="自定义模型 id（区分大小写，如 gpt-5.5）"
        />
      ) : null}
    </>
  );
}
