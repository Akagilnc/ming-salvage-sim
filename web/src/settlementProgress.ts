/**
 * #1725：月末结算等待期的 typed 进度事实。
 *
 * 六个 stage 名是确定性 UI chrome（陛下裁定 stage-labels-are-ui-chrome-not-diegetic-text），
 * 顺序与真入口 POST /api/decree/issue/stream 实测一致。进度刻度由本表下标驱动，
 * 不从自由文案推断。
 *
 * #1740：结局第七段另常量，不并入六名表——普通回合 total 仍为 6；
 * 仅命中结局段时 total/current 为 7（进度不消失、不倒退）。
 */
export const SETTLEMENT_WAIT_STAGES = [
  "固定月度财政入账",
  "回顾近来朝局",
  "推演月末邸报",
  "数值推演结算",
  "落库与事项推进",
  "记起居注",
] as const;

/** #1740：结局回合第七段；与后端 SETTLEMENT_ENDING_STAGE_LABEL 同源冻结。 */
export const SETTLEMENT_ENDING_STAGE = "国史编纂结局总评" as const;

export type SettlementWaitStage = (typeof SETTLEMENT_WAIT_STAGES)[number];

/** 玩家可见进度刻度：1-based current + 场景 total（普通 6 / 结局段 7）。 */
export type SettlementWaitProgress = {
  label: SettlementWaitStage | typeof SETTLEMENT_ENDING_STAGE;
  /** 当前步（1..total） */
  current: number;
  /** 总步数 */
  total: number;
};

const STAGE_INDEX = new Map<string, number>(
  SETTLEMENT_WAIT_STAGES.map((label, i) => [label, i]),
);

/**
 * 将 SSE stage 内容解析为 typed 进度。
 * 命中冻结六阶 → total=6；命中结局第七段 → total=7；
 * 其它标签（如 HITL 续推提示）不伪造刻度。
 */
export function resolveSettlementWaitProgress(
  stage: string | null | undefined,
): SettlementWaitProgress | null {
  if (!stage) return null;
  if (stage === SETTLEMENT_ENDING_STAGE) {
    const total = SETTLEMENT_WAIT_STAGES.length + 1;
    return { label: SETTLEMENT_ENDING_STAGE, current: total, total };
  }
  const index = STAGE_INDEX.get(stage);
  if (index === undefined) return null;
  return {
    label: SETTLEMENT_WAIT_STAGES[index],
    current: index + 1,
    total: SETTLEMENT_WAIT_STAGES.length,
  };
}
