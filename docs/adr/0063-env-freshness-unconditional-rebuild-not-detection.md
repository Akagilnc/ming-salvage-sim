Status: Proposed

# 0063: 编排器环境新鲜靠无条件重建，不做检测式 staleness 闸

## 决定

worker 环境（dist/souls/skills/镜像）的新鲜性靠 **无条件重建 by construction**：launcher 派活前无条件 `npx tsc` + `docker build`（Docker layer cache 即内容寻址的增量判断，自有代码零检测逻辑）；souls 等数据文件能 mount 就 mount；base 镜像与 apt/curl 安装工具的慢漂移用人手/定期 `rebake --no-cache` 兜底，不进每次 run 路径。**检测式方案（比 mtime、查 manifest、解析 registry digest、版本 pin 强制）整体否决**——检测要正确必须完备枚举全部漂移源，是无底洞（#372 家族 34 轮 CMR 长出 5 条 staleness 轴即其逻辑终点），而重建在缓存命中时是秒级，符合「不拿免费的换最贵的」。

使用者将只面对一个公开开工入口并只提供 issue 号；该入口在派活前完成上述全部 freshness 准备。后续 Policy preflight、Issue Admission、Scene Provisioning / Recovery、facts→Flow 与 fixed-position 接力只读 #869/#871，本 ADR 不保存第二份开工拓扑；任何新 scene 副作用都不得早于已批准的 preflight 与无现场准入。`runFamilyDriver` 仍是内部能力，不是第二个公开入口；待公开的 issue-number 开工入口落地时，实现切片 #885 必须同步更新 README/公开文档，届时才退休手工 freshness ritual、创建 per-issue driver 和拼装内部参数的说明。

## 后果

- #372 重写为「无条件重建」薄 issue；#594/#595/#599（检测式三件套）关闭、由其 supersede。
- 该逻辑属 launcher/入口（指编排器任务启动器，而非仓库根目录桌面客户端的 `launcher.py`），不进 runner 循环（runner 三功能见 ADR 0062）。
- 所有 single/family 公开启动路径必须收口到同一入口；直接导入内部 driver 只允许内部组合与测试，不作为操作手册中的启动方式。
