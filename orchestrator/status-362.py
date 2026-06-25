#!/usr/bin/env python3
"""只读 dogfood 进度板：读驱动日志 + docker + ledger，渲染 S0–S8。
零写入、不碰编排器——纯观测。用法: python3 status-362.py"""
import re, subprocess, os, glob, time

LOG = "/tmp/dogfood-362.log"
# $HOME-relative, not a hard-coded absolute home path (gemini #384 R4).
LEDGER = os.path.expanduser("~/.sc-orchestrator/dogfood-362-ledger")
STEPS = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
LABEL = {"S0": "gate", "S1": "load", "S2": "code", "S3": "rev",
         "S4": "route", "S5": "fix", "S6": "re-rev", "S7": "ship", "S8": "done"}

# 1. 各片最新 S 步 + review/fix 轮次 (数每片步进出现次数)
cur = {}    # issue -> (stepIdx, role)
revN = {}   # issue -> review 轮数 (S3 初评 + 每个 S6 复评)
fixN = {}   # issue -> fix 轮数 (每个 S5 coder_fix)
pat = re.compile(r"\[S(\d)-(\w+)\] Started on branch \S*issue-(\d+)")
if os.path.exists(LOG):
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            m = pat.search(line)
            if m:
                s, role, iss = int(m.group(1)), m.group(2), int(m.group(3))
                cur[iss] = (s, role)
                if s in (3, 6): revN[iss] = revN.get(iss, 0) + 1   # S3/S6 = 一轮 review
                if s == 5:      fixN[iss] = fixN.get(iss, 0) + 1   # S5 = 一轮 fix

# 2. docker 活动容器
try:
    n_ctr = len([l for l in subprocess.run(
        ["docker", "ps", "-q"], capture_output=True, text=True, timeout=10
    ).stdout.splitlines() if l.strip()])
except Exception:
    n_ctr = "?"

# 3. 驱动进程 + 运行时长
try:
    pid = subprocess.run(["pgrep", "-f", "launch-362.mjs"], capture_output=True, text=True, timeout=10).stdout.split()
    if pid:
        et = subprocess.run(["ps", "-o", "etime=", "-p", pid[0]], capture_output=True, text=True, timeout=10).stdout.strip()
        drv = f"✅ 跑了 {et}"
    else:
        drv = "⏹ 已退出 (跑完?)"
except Exception:
    drv = "?"

# 4. ledger 条目
led = sorted(os.path.basename(p) for p in glob.glob(os.path.join(LEDGER, "*"))) if os.path.isdir(LEDGER) else []

# ── 渲染 ──
print("═" * 60)
print("  dogfood #362 — 编排器进度板 (只读)")
print(f"  驱动: {drv}   容器: {n_ctr} Up   ledger: {len(led)} 项")
print("═" * 60)
hdr = "子片    " + "  ".join(f"{s}" for s in STEPS) + "   当前"
print(hdr)
print("-" * 60)
for iss in sorted(cur):
    s, role = cur[iss]
    cells = []
    for i in range(len(STEPS)):
        if i < s:    cells.append("✅")
        elif i == s: cells.append("🔵")
        else:        cells.append(" ·")
    rv = revN.get(iss, 0)
    fx = fixN.get(iss, 0)
    rnd = f"评{rv}轮" + (f"/修{fx}轮" if fx else "") if rv else "—"
    print(f"#{iss}  " + "  ".join(cells) + f"   {STEPS[s]} {role}  [{rnd}]")
print("-" * 60)
print("步骤: " + " ".join(f"{s}={LABEL[s]}" for s in STEPS))
print("✅已过  🔵进行中   ·未到")
if not cur:
    print("(驱动日志暂无步骤记录——可能还在 clone/起步)")
