"""汇总基准日志里的 [TOKEN] 行 → 按 model + caller 聚合出 token 用量表。

play_as_emperor.py 跑压测时,游戏侧(deepseek)与玩家侧(qwen)每次 completion 都打一行:
  [TOKEN] caller=minister model=deepseek-v4-flash prompt=1234 cached=0 cache_creation=0 completion=56 reasoning=0 total=1290

本脚本扫一个或多个日志(含 .stdout),把这些行按 model 聚合(可选再按 caller 细分),
算出 calls / prompt / cached / completion / total 与缓存命中率,给基准结论用。

用法:
    .venv/bin/python scripts/sum_token_log.py scripts/runs/bench_*.log scripts/runs/bench_*.log.stdout
    .venv/bin/python scripts/sum_token_log.py --by-caller <logs...>
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from collections import defaultdict
from typing import Dict

LINE = re.compile(
    r"\[TOKEN\]\s+caller=(?P<caller>\S+)\s+model=(?P<model>\S+)\s+"
    r"prompt=(?P<prompt>\d+)\s+cached=(?P<cached>\d+)"
    r"(?:\s+cache_creation=(?P<cc>\d+))?\s+"
    r"completion=(?P<completion>\d+)\s+reasoning=(?P<reasoning>\d+)\s+total=(?P<total>\d+)"
)

FIELDS = ("calls", "prompt", "cached", "cache_creation", "completion", "reasoning", "total")

# 各模型单价(人民币元 / 1M tokens)。缓存命中只对 prompt 里 cached 那部分计;
# 其余 prompt(prompt-cached) 按缓存未命中价;completion 按输出价。
# deepseek-v4-flash 单价取自官方 pricing 中文站(2026-04-26 调整后)。
PRICES = {
    "deepseek-v4-flash": {"hit": 0.02, "miss": 1.0, "out": 2.0},
    "deepseek-v4-pro": {"hit": 0.025, "miss": 3.0, "out": 6.0},
    # qwen 走 dashscope,单价口径不同(且本基准只关注游戏侧),默认不计价。
}


def cost_cny(model: str, b: Dict[str, int]) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    cached = b["cached"]
    miss = max(b["prompt"] - cached, 0)
    return (cached * p["hit"] + miss * p["miss"] + b["completion"] * p["out"]) / 1_000_000


def blank() -> Dict[str, int]:
    return {f: 0 for f in FIELDS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", help="日志文件(支持 glob);通常同时传 .log 与 .log.stdout")
    ap.add_argument("--by-caller", action="store_true", help="再按 caller(minister/simulator/extractor/...) 细分")
    args = ap.parse_args()

    paths = []
    for pat in args.logs:
        hit = glob.glob(pat)
        paths.extend(hit or [pat])

    by_model: Dict[str, Dict[str, int]] = defaultdict(blank)
    by_mc: Dict[str, Dict[str, int]] = defaultdict(blank)
    seen = 0
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    m = LINE.search(raw)
                    if not m:
                        continue
                    seen += 1
                    model = m.group("model")
                    caller = m.group("caller")
                    cc = int(m.group("cc") or 0)
                    vals = {
                        "calls": 1,
                        "prompt": int(m.group("prompt")),
                        "cached": int(m.group("cached")),
                        "cache_creation": cc,
                        "completion": int(m.group("completion")),
                        "reasoning": int(m.group("reasoning")),
                        "total": int(m.group("total")),
                    }
                    for k, v in vals.items():
                        by_model[model][k] += v
                        by_mc[f"{model}\t{caller}"][k] += v
        except OSError as e:
            print(f"[warn] 读不了 {path}: {e}", file=sys.stderr)

    if not seen:
        print("没扫到任何 [TOKEN] 行。确认日志路径,或跑局是否真的产生了 token 日志。")
        return 1

    def row(label: str, b: Dict[str, int], model: str, share_base: float = 0.0) -> str:
        hit = (b["cached"] / b["prompt"] * 100) if b["prompt"] else 0.0
        c = cost_cny(model, b)
        cost_part = ""
        if c is not None:
            share = f" 占{c / share_base * 100:.1f}%" if share_base else ""
            cost_part = f" 费用=¥{c:.4f}{share}"
        return (
            f"  {label}: calls={b['calls']} prompt={b['prompt']} "
            f"cached={b['cached']}({hit:.1f}%) cache_creation={b['cache_creation']} "
            f"completion={b['completion']} total={b['total']}{cost_part}"
        )

    print(f"\n========== TOKEN 汇总({seen} 行,{len(paths)} 文件) ==========")
    grand = blank()
    for model in sorted(by_model):
        mcost = cost_cny(model, by_model[model]) or 0.0
        print(row(model, by_model[model], model))
        if args.by_caller:
            callers = [(k.split("\t")[1], by_mc[k]) for k in by_mc if k.split("\t")[0] == model]
            # 按费用(无价时按 total)降序,占比相对该模型总费用
            callers.sort(key=lambda kv: cost_cny(model, kv[1]) or kv[1]["total"], reverse=True)
            for caller, b in callers:
                print(row(f"  └ {caller}", b, model, share_base=mcost))
        for k in FIELDS:
            grand[k] += by_model[model][k]
    # 总计费用:各模型分别计价再相加(单价不同不能合并)
    grand_cost = sum(cost_cny(m, by_model[m]) or 0.0 for m in by_model)
    hit = (grand["cached"] / grand["prompt"] * 100) if grand["prompt"] else 0.0
    print(
        f"  总计: calls={grand['calls']} prompt={grand['prompt']} "
        f"cached={grand['cached']}({hit:.1f}%) completion={grand['completion']} "
        f"total={grand['total']} 费用=¥{grand_cost:.4f}（仅计已知单价模型）"
    )
    print("=" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())
