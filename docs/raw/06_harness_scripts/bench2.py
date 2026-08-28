"""全角色基准:叙事类剥壳存原文(人工评) + 结构化自动判。
5 后端(4 codex medium + agy)。"""
import json, time, subprocess, sys, re, os, statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/Users/akagilnc/WorkSpace/Ming_LLM")
from ming_sim import cli_backend as cb

PR = "/tmp/roleprompts"
SANDBOX = "/tmp/ming_agy_sandbox"; os.makedirs(SANDBOX, exist_ok=True)
OUT = "/tmp/bench2_out"; os.makedirs(OUT, exist_ok=True)

CODEX = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"]
ALL = CODEX + ["agy"]
# (role, prompt_file, category, runs)
ROLES = [
    ("simulator",      "simulator.txt",                  "narr", 1),
    ("minister",       "minister.txt",                   "narr", 1),
    ("decree",         "decree.txt",                     "narr", 1),
    ("chapter_memory", "chapter_memory.txt",             "narr", 1),
    ("ext_internal",   "extractor_internal.txt",         "struct", 2),
    ("ext_military",   "extractor_military_external.txt", "struct", 2),
    ("ext_personnel",  "extractor_personnel_secret.txt", "struct", 2),
    ("secret_extract", "secret_extract.txt",             "struct", 2),
]

def codex_run(model, prompt):
    t0=time.time()
    try:
        p=subprocess.run(["codex","exec","--model",model,"-c",'model_reasoning_effort="medium"',
                          "--skip-git-repo-check","-"],
                         input=prompt, capture_output=True, text=True, timeout=360, cwd=SANDBOX)
        return time.time()-t0, (p.stdout or "")+(p.stderr or ""), ""
    except subprocess.TimeoutExpired:
        return time.time()-t0, "", "timeout"

def agy_run(_model, prompt):
    t0=time.time()
    try:
        out,_=cb._run_agy(prompt); return time.time()-t0, out, ""
    except Exception as e:
        return time.time()-t0, "", str(e)[:80]

LOGPAT=re.compile(r'^\d{4}-\d\d-\d\dT.*(ERROR|WARN|INFO)')
def codex_final(raw):
    i=raw.rfind('tokens used')
    seg = raw[i+len('tokens used'):] if i!=-1 else raw
    seg = re.sub(r'^\s*[\d,]+\s*\n','',seg)
    lines=[l for l in seg.splitlines()
           if not LOGPAT.match(l) and 'rollout items' not in l
           and 'rmcp::' not in l and 'codex_core::' not in l and l.strip()!='codex']
    return '\n'.join(lines).strip()

def balanced(raw):
    out=[];d=0;s=None
    for i,c in enumerate(raw):
        if c=='{':
            if d==0:s=i
            d+=1
        elif c=='}':
            d-=1
            if d==0 and s is not None:
                try:
                    o=json.loads(raw[s:i+1])
                    if isinstance(o,dict):out.append(o)
                except:pass
                s=None
    return out

def judge_struct(text):
    objs=balanced(text)
    if not objs: return 0,0  # parse_ok, nonempty_fields
    o=max(objs,key=lambda x:len(json.dumps(x,ensure_ascii=False)))
    ne=sum(1 for v in o.values() if v)
    return 1, ne

JOBS=[]
for role,pf,cat,runs in ROLES:
    prompt=open(os.path.join(PR,pf)).read()
    for b in ALL:
        fn = codex_run if b in CODEX else agy_run
        for r in range(runs):
            JOBS.append((role,cat,b,r,fn,prompt))

print(f"启动 {len(JOBS)} 任务,并发5...",flush=True)
results=[]
with ThreadPoolExecutor(max_workers=5) as ex:
    futs={ex.submit(fn,b,prompt):(role,cat,b,r) for role,cat,b,r,fn,prompt in JOBS}
    done=0
    for fut in as_completed(futs):
        role,cat,b,r=futs[fut]; dur,raw,err=fut.result(); done+=1
        clean = codex_final(raw) if (b in CODEX and not err) else (raw if not err else "")
        rec={"role":role,"cat":cat,"backend":b,"run":r,"dur":dur,"err":err,"chars":len(clean)}
        if cat=="struct" and not err:
            pk,ne=judge_struct(clean); rec["parse"]=pk; rec["nonempty"]=ne
        if cat=="narr" and not err:
            open(f"{OUT}/{role}__{b}__{r}.txt","w").write(clean)
        results.append(rec)
        print(f"[{done}/{len(JOBS)}] {role:<15}{b:<20}{dur:.1f}s {err or rec.get('parse','') and 'parse'+str(rec.get('parse'))} {rec['chars']}c",flush=True)

json.dump(results,open(f"{OUT}/results.json","w"),ensure_ascii=False,indent=1)
print("\n=== DONE ===",flush=True)
