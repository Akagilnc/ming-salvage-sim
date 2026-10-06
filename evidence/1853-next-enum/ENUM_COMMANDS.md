# #1853 下一轮枚举命令（纠正上轮虚假服从标签）

## 类一：实际事务提交权单一权威

边界：全仓生产代码中判定「本调用方是否有权真提交」的所有谓词和写口。
手抄 `_commit_suspended`/`_atomic_depth` 组合均在类内。

```bash
rg -n --glob '!tests/**' --glob '!evidence/**' \
  '_commit_suspended|_atomic_depth|connection_owns_transaction|owns_transaction\(' \
  ming_sim web_app.py
```

权威：`applier.connection_owns_transaction` + `GameDB.owns_transaction` 委托。
处置：写前捕获 `owns = …owns_transaction()`，写后按缓存提交；禁止写后手抄 flags。

## 类二：必备DB能力兼容残余清退

边界：对必备 GameDB 属性/方法做 hasattr/getattr/callable，缺失即跳过。
含无条件 `affairs`/`textual_facts` store。不能凭文件职责排除。

```bash
rg -n --glob '!tests/**' --glob '!evidence/**' \
  'hasattr\(|getattr\(|callable\(' ming_sim web_app.py
```

然后逐命中核：属性是否为 GameDB 必备；缺失分支是否空结果/跳过。
