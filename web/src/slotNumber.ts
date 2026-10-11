/** Config-slot numeric coerce (mirrors ming_sim.llm_config._slot_number duty). */

export function slotNumber(value: unknown, fallback: number): number {
  if (value == null) return fallback;
  if (typeof value === "string" && !value.trim()) return fallback;
  const n = typeof value === "number" ? value : parseFloat(String(value));
  return Number.isFinite(n) ? n : fallback;
}
