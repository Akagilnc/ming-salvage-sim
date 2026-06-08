"""claude 两家用 MAX_THINKING_TOKENS=10000(≈medium)重跑,对比速度/质量。"""
import json, time, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0,"/Users/akagilnc/WorkSpace/Ming_LLM")
PR="/tmp/roleprompts"; OUT="/tmp/bench_claude_out"; os.makedirs(OUT,exist_ok=True)
NARR=set(["simulator","minister","decree","chapter_memory"])
CLAUDE=[("claude-sonnet-4-6","sonnet4.6"),("claude-haiku-4-5-20251001","haiku4.5")]
ROLES=[("simulator","simulator.txt","narr",1),("minister","minister.txt","narr",1),
 ("decree","decree.txt","narr",1),("chapter_memory","chapter_memory.txt","narr",1),
 ("ext_internal","extractor_internal.txt","struct",2),("ext_military","extractor_military_external.txt","struct",2),
 ("ext_personnel","extractor_personnel_secret.txt","struct",2),("secret_extract","secret_extract.txt","struct",2)]
ENV={**os.environ,"MAX_THINKING_TOKENS":"10000"}

def run(model,prompt):
    t0=time.time()
    try:
        p=subprocess.run(["claude","-p","--model",model,"--output-format","text",
            "--disallowed-tools","Bash","Read","Edit","Write","Glob","Grep","WebFetch","WebSearch","Task","NotebookEdit"],
            input=prompt,capture_output=True,text=True,timeout=600,env=ENV)
        return time.time()-t0,(p.stdout or "").strip(),"" if p.returncode==0 else f"rc{p.returncode}"
    except subprocess.TimeoutExpired: return time.time()-t0,"","timeout"

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
def judge(t):
    o=balanced(t)
    if not o:return 0,0
    b=max(o,key=lambda x:len(json.dumps(x,ensure_ascii=False)))
    return 1,sum(1 for v in b.values() if v)

JOBS=[]
for role,pf,cat,runs in ROLES:
    prompt=open(os.path.join(PR,pf)).read()
    for mid,label in CLAUDE:
        for r in range(runs): JOBS.append((role,cat,label,r,(lambda p,_m=mid:run(_m,p)),prompt))
print(f"启动 {len(JOBS)} 任务,并发4...",flush=True)
results=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    futs={ex.submit(fn,prompt):(role,cat,b,r) for role,cat,b,r,fn,prompt in JOBS}
    done=0
    for fut in as_completed(futs):
        role,cat,b,r=futs[fut]; dur,clean,err=fut.result(); done+=1
        rec={"role":role,"cat":cat,"backend":b,"run":r,"dur":dur,"err":err,"chars":len(clean)}
        if cat=="struct" and not err:
            pk,ne=judge(clean); rec["parse"]=pk; rec["nonempty"]=ne
        if cat=="narr" and clean: open(f"{OUT}/{role}__{b}__{r}.txt","w").write(clean)
        results.append(rec)
        print(f"[{done}/{len(JOBS)}] {role:<15}{b:<11}{dur:.0f}s {err or (cat=='struct' and 'p'+str(rec.get('parse'))) or ''} {rec['chars']}c",flush=True)
json.dump(results,open(f"{OUT}/results.json","w"),ensure_ascii=False,indent=1)
print("\n=== DONE ===",flush=True)
