"""A/B: 同一条真实 issues-extractor prompt 喂 agy vs codex，对比 新立局势/来源类型 填写。"""
import json, sys, time, traceback
sys.path.insert(0, "/Users/akagilnc/WorkSpace/Ming_LLM")
from ming_sim import cli_backend as cb

prompt = open("/tmp/issues_prompt.txt").read()

def parse_new_issues(raw):
    # 复用项目宽松解析
    obj = cb._loads_lenient(raw) or {}
    ni = obj.get("新立局势") or obj.get("new_issues") or []
    return obj, ni

def run(name, fn):
    print(f"\n========== {name} ==========", flush=True)
    t0 = time.time()
    try:
        out, attempts = fn(prompt)
    except Exception as e:
        print(f"[{name}] 调用失败: {e}", flush=True)
        traceback.print_exc()
        return
    dur = time.time() - t0
    print(f"[{name}] dur={dur:.1f}s attempts={attempts} resp_chars={len(out)}", flush=True)
    open(f"/tmp/ab_{name}_raw.txt", "w").write(out)
    obj, ni = parse_new_issues(out)
    print(f"[{name}] 顶层字段: {list(obj.keys())}", flush=True)
    print(f"[{name}] 新立局势条数: {len(ni)}", flush=True)
    for i, item in enumerate(ni):
        ok = item.get("来源类型") or item.get("origin_kind")
        print(f"  #{i} 来源类型={ok!r} 标题={item.get('标题') or item.get('title')!r} "
              f"类型={item.get('类型') or item.get('kind')!r} "
              f"可撤销={item.get('可撤销') or item.get('可否撤销') or item.get('cancellable')!r}", flush=True)
        print(f"     全字段: {list(item.keys())}", flush=True)

run("agy", cb._run_agy)
run("codex", cb._run_codex)
print("\n=== DONE ===", flush=True)
