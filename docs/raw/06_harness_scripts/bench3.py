"""重跑 codex(--ephemeral 解并发碰撞)+ 补 claude 两家。agy 复用 bench2。存原文。"""
import json, time, subprocess, sys, re, os
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/Users/akagilnc/WorkSpace/Ming_LLM")
from ming_sim import cli_backend as cb

PR="/tmp/roleprompts"; SANDBOX="/tmp/ming_agy_sandbox"; os.makedirs(SANDBOX,exist_ok=True)
OUT="/tmp/bench3_out"; os.makedirs(OUT,exist_ok=True)

CODEX=["gpt-5.5","gpt-5.4","gpt-5.4-mini","gpt-5.3-codex-spark"]
CLAUDE=[("claude-sonnet-4-6","sonnet4.6"),("claude-haiku-4-5-20251001","haiku4.5")]
ROLES=[
 ("simulator","simulator.txt","narr",1),
 ("minister","minister.txt","narr",1),
 ("decree","decree.txt","narr",1),
 ("chapter_memory","chapter_memory.txt","narr",1),
 ("ext_internal","extractor_internal.txt","struct",2),
 ("ext_military","extractor_military_external.txt","struct",2),
 ("ext_personnel","extractor_personnel_secret.txt","struct",2),
 ("secret_extract","secret_extract.txt","struct",2),
]

def codex_run(model,prompt):
    t0=time.time()
    try:
        p=subprocess.run(["codex","exec","--model",model,"-c",'model_reasoning_effort="medium"',
                          "--ephemeral","--skip-git-repo-check","-"],
                         input=prompt,capture_output=True,text=True,timeout=360,cwd=SANDBOX)
        return time.time()-t0,(p.stdout or "")+(p.stderr or ""),""
    except subprocess.TimeoutExpired: return time.time()-t0,"","timeout"

def claude_run(model,prompt):
    t0=time.time()
    try:
        p=subprocess.run(["claude","-p","--model",model,"--output-format","text",
                          "--disallowed-tools","Bash","Read","Edit","Write","Glob","Grep",
                          "WebFetch","WebSearch","Task","NotebookEdit"],
                         input=prompt,capture_output=True,text=True,timeout=360)
        return time.time()-t0,(p.stdout or "")+("\n[STDERR]"+p.stderr if p.returncode else ""),"" if p.returncode==0 else f"rc{p.returncode}"
    except subprocess.TimeoutExpired: return time.time()-t0,"","timeout"

LOG=re.compile(r'^\d{4}-\d\d-\d\dT.*(ERROR|WARN|INFO)')
def codex_final(raw):
    i=raw.rfind('tokens used'); seg=raw[i+len('tokens used'):] if i!=-1 else raw
    seg=re.sub(r'^\s*[\d,]+\s*\n','',seg)
    return '\n'.join(l for l in seg.splitlines() if not LOG.match(l) and 'rollout items' not in l
                     and 'rmcp::' not in l and 'codex_core::' not in l and l.strip()!='codex').strip()

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
def judge(text):
    o=balanced(text)
    if not o:return 0,0
    b=max(o,key=lambda x:len(json.dumps(x,ensure_ascii=False)))
    return 1,sum(1 for v in b.values() if v)

JOBS=[]
for role,pf,cat,runs in ROLES:
    prompt=open(os.path.join(PR,pf)).read()
    for m in CODEX:
        for r in range(runs): JOBS.append((role,cat,m,"codex",r,(lambda p,_m=m:codex_run(_m,p)),prompt))
    for mid,label in CLAUDE:
        for r in range(runs): JOBS.append((role,cat,label,"claude",r,lambda p,_m=mid:claude_run(_m,p),prompt))

print(f"启动 {len(JOBS)} 任务,并发5...",flush=True)
results=[]
with ThreadPoolExecutor(max_workers=5) as ex:
    futs={ex.submit(fn,prompt):(role,cat,b,kind,r) for role,cat,b,kind,r,fn,prompt in JOBS}
    done=0
    for fut in as_completed(futs):
        role,cat,b,kind,r=futs[fut]; dur,raw,err=fut.result(); done+=1
        clean = "" if err else (codex_final(raw) if kind=="codex" else raw.strip())
        open(f"{OUT}/RAW_{role}__{b}__{r}.txt","w").write(raw)
        rec={"role":role,"cat":cat,"backend":b,"run":r,"dur":dur,"err":err,"chars":len(clean)}
        if cat=="struct" and not err:
            pk,ne=judge(clean); rec["parse"]=pk; rec["nonempty"]=ne
        if cat=="narr" and not err:
            open(f"{OUT}/{role}__{b}__{r}.txt","w").write(clean)
        results.append(rec)
        print(f"[{done}/{len(JOBS)}] {role:<15}{b:<12}{dur:.1f}s {err or ('p'+str(rec.get('parse','')) if cat=='struct' else '')} {rec['chars']}c",flush=True)

json.dump(results,open(f"{OUT}/results.json","w"),ensure_ascii=False,indent=1)
print("\n=== DONE ===",flush=True)
