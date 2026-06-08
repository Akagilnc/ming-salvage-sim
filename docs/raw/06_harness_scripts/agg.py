import glob, json, os, re, statistics
B3="/tmp/bench3_out"; B2="/tmp/bench2_out"; M="/tmp/merged_narr"; os.makedirs(M,exist_ok=True)

CODEX=["gpt-5.5","gpt-5.4","gpt-5.4-mini","gpt-5.3-codex-spark"]
CLAUDE=["sonnet4.6","haiku4.5"]
ORDER=CODEX+CLAUDE+["agy"]
NARR=["simulator","minister","decree","chapter_memory"]
STRUCT=["ext_internal","ext_military","ext_personnel","secret_extract"]

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

# 读 durations
dur={}
for fn in [f"{B3}/results.json",f"{B2}/results.json"]:
    for r in json.load(open(fn)):
        dur[(r["role"],r["backend"],r["run"])]=r["dur"]

rows=[]  # role,cat,backend,run,chars,parse,nonempty,dur
# codex: 从 RAW 重抽
for f in glob.glob(f"{B3}/RAW_*.txt"):
    base=os.path.basename(f)[4:-4]
    role,b,run=base.rsplit("__",2); run=int(run)
    if b not in CODEX: continue
    raw=open(f).read(); clean=raw.split("OpenAI Codex v")[0].strip()
    cat="narr" if role in NARR else "struct"
    pk,ne=judge(clean) if cat=="struct" else (None,None)
    if cat=="narr" and clean: open(f"{M}/{role}__{b}__{run}.txt","w").write(clean)
    rows.append([role,cat,b,run,len(clean),pk,ne,dur.get((role,b,run),0)])
# claude: bench3 clean
for r in json.load(open(f"{B3}/results.json")):
    if r["backend"] not in CLAUDE: continue
    role=r["role"]; cat=r["cat"]
    nf=f"{B3}/{role}__{r['backend']}__{r['run']}.txt"
    if cat=="narr" and os.path.exists(nf):
        import shutil; shutil.copy(nf,f"{M}/{role}__{r['backend']}__{r['run']}.txt")
    rows.append([role,cat,r["backend"],r["run"],r.get("chars",0),r.get("parse"),r.get("nonempty"),r["dur"]])
# agy: bench2
for r in json.load(open(f"{B2}/results.json")):
    if r["backend"]!="agy": continue
    role=r["role"]; cat=r["cat"]
    nf=f"{B2}/{role}__agy__{r['run']}.txt"
    if cat=="narr" and os.path.exists(nf):
        import shutil; shutil.copy(nf,f"{M}/{role}__agy__{r['run']}.txt")
    rows.append([role,cat,r["backend"],r["run"],r.get("chars",0),r.get("parse"),r.get("nonempty"),r["dur"]])

# ===== 结构化表 =====
print("="*78)
print("结构化模块(4 模块×2 跑,程序判 JSON 合法+非空字段数)")
print("="*78)
hdr=f"{'后端':<20}{'合法率':<9}{'平均非空字段':<13}{'平均耗时s':<10}{'平均字符'}"
print(hdr); print("-"*70)
for b in ORDER:
    rs=[r for r in rows if r[1]=="struct" and r[2]==b]
    if not rs: continue
    n=len(rs); ok=[r for r in rs if r[5]==1]
    rate=f"{len(ok)}/{n}"
    ne=f"{statistics.mean([r[6] for r in ok]):.1f}" if ok else "-"
    d=f"{statistics.mean([r[7] for r in rs]):.0f}"
    ch=f"{statistics.mean([r[4] for r in rs]):.0f}"
    print(f"{b:<20}{rate:<9}{ne:<13}{d:<10}{ch}")

# ===== 叙事清单 =====
print("\n"+"="*78)
print("叙事类(每后端1跑,字符数+耗时;原文已归并到 /tmp/merged_narr)")
print("="*78)
print(f"{'后端':<20}"+''.join(f'{r[:9]:<11}' for r in NARR))
for b in ORDER:
    cells=[]
    for role in NARR:
        rr=[r for r in rows if r[0]==role and r[2]==b]
        if rr and rr[0][4]>0: cells.append(f"{rr[0][4]}c/{rr[0][7]:.0f}s")
        elif rr: cells.append("失败")
        else: cells.append("-")
    print(f"{b:<20}"+''.join(f'{c:<11}' for c in cells))
print("\n注:sonnet4.6 simulator 超时(360s);codex 全程 medium;agy 默认无 reasoning 旋钮")
