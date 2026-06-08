"""5 后端 × 5 次基准:质量 + 速度。同一条真实 issues-extractor prompt。
codex 全部 reasoning=medium；agy 无此旋钮走默认。"""
import json, time, subprocess, sys, statistics, os
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/Users/akagilnc/WorkSpace/Ming_LLM")
from ming_sim import cli_backend as cb

PROMPT = open("/tmp/issues_prompt.txt").read()
SANDBOX = "/tmp/ming_agy_sandbox"
os.makedirs(SANDBOX, exist_ok=True)

CODEX_MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"]
RUNS = 5

def run_codex(model):
    t0 = time.time()
    try:
        p = subprocess.run(
            ["codex", "exec", "--model", model,
             "-c", 'model_reasoning_effort="medium"',
             "--skip-git-repo-check", "-"],
            input=PROMPT, capture_output=True, text=True, timeout=300, cwd=SANDBOX,
        )
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return {"dur": time.time()-t0, "err": "timeout", "raw": ""}
    return {"dur": time.time()-t0, "err": "", "raw": out}

def run_agy(_model):
    t0 = time.time()
    try:
        out, _ = cb._run_agy(PROMPT)
    except Exception as e:
        return {"dur": time.time()-t0, "err": str(e)[:80], "raw": ""}
    return {"dur": time.time()-t0, "err": "", "raw": out}

def balanced(raw):
    out=[]; depth=0; start=None
    for i,ch in enumerate(raw):
        if ch=='{':
            if depth==0: start=i
            depth+=1
        elif ch=='}':
            depth-=1
            if depth==0 and start is not None:
                try:
                    o=json.loads(raw[start:i+1])
                    if isinstance(o,dict): out.append(o)
                except: pass
                start=None
    return out

def quality(raw):
    objs=[o for o in balanced(raw) if '新立局势' in o or '局势推进' in o]
    if not objs:
        return {"parse":0,"new":0,"origin_ok":0,"re":0,"fe":0,"adv":0,"advnz":0}
    o=max(objs,key=lambda x:len(json.dumps(x,ensure_ascii=False)))
    ni=o.get('新立局势',[]); adv=o.get('局势推进',[])
    it=ni[0] if ni else {}
    ok=(it.get('来源类型') or it.get('origin_kind'))
    advnz=sum(1 for a in adv if int(a.get('进度增量',0) or 0)!=0)
    return {
        "parse":1, "new":1 if ni else 0,
        "origin_ok":1 if ok=='decree' else 0,
        "re":1 if (it.get('解决效果') or it.get('effect_on_resolve')) else 0,
        "fe":1 if (it.get('失败效果') or it.get('effect_on_fail')) else 0,
        "adv":len(adv), "advnz":advnz,
    }

JOBS=[]
for m in CODEX_MODELS:
    for r in range(RUNS): JOBS.append((m, run_codex))
for r in range(RUNS): JOBS.append(("agy", run_agy))

results={m:[] for m in CODEX_MODELS+["agy"]}
print(f"启动 {len(JOBS)} 个任务,并发5...", flush=True)
with ThreadPoolExecutor(max_workers=5) as ex:
    futs={ex.submit(fn, m):(m) for m,fn in JOBS}
    done=0
    for fut in as_completed(futs):
        m=futs[fut]; res=fut.result(); done+=1
        q=quality(res["raw"]) if not res["err"] else None
        results[m].append({"dur":res["dur"],"err":res["err"],"q":q})
        flag = res["err"] or (f"落库{'✓' if q and q['origin_ok'] and q['new'] else '✗'}")
        print(f"[{done}/{len(JOBS)}] {m:<20} {res['dur']:.1f}s {flag}", flush=True)

json.dump(results, open("/tmp/bench_results.json","w"), ensure_ascii=False, indent=1)

print("\n\n========== 聚合(每后端 5 次) ==========")
hdr=f"{'后端':<20}{'成功跑':<7}{'落库成功':<9}{'origin对':<9}{'解决填':<8}{'失败填':<8}{'推进有效':<9}{'速度s(min/中/max)'}"
print(hdr); print('-'*len(hdr)*1)
for m in CODEX_MODELS+["agy"]:
    rs=results[m]
    okruns=[r for r in rs if not r["err"] and r["q"]]
    n=len(okruns)
    durs=[r["dur"] for r in rs if not r["err"]]
    def rate(key): return f"{sum(r['q'][key] for r in okruns)}/{n}" if n else "0/0"
    advnz=f"{sum(r['q']['advnz'] for r in okruns)/n:.1f}条" if n else "-"
    sp=f"{min(durs):.0f}/{statistics.median(durs):.0f}/{max(durs):.0f}" if durs else "全失败"
    luru=f"{sum(1 for r in okruns if r['q']['origin_ok'] and r['q']['new'])}/{len(rs)}"
    print(f"{m:<20}{f'{len(durs)}/{len(rs)}':<7}{luru:<9}{rate('origin_ok'):<9}{rate('re'):<8}{rate('fe'):<8}{advnz:<9}{sp}")
print("\n注:落库成功=产新立局势且origin_kind=decree;推进有效=进度增量非0的局势数均值;codex=reasoning medium,agy=默认")
print("=== DONE ===", flush=True)
