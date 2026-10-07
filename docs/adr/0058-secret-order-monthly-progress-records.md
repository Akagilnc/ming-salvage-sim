# 0058: 月度进展逐月持久，推送与垂问读同一份记录

Status: 修订待票庭重审（#1895；原决定 PR #573，2026-07-04）

#1900 后出修订稿（2026-10-02）已署——给事中 `01a107bc-4cbd-717a-86b8-40d8dc328fa6`、符宝郎 `01a107cb-0111-7757-87d5-78c1adb9513b`：本票押解／暗护重构中，下文「补护行子结构」「逐月逐路建被护案卷侧对账记录」不再是切片补齐功能或新增载体的施工要求；本票处置以 [0054 后出修订](0054-ledger-cross-links-and-effect-backrefs.md) 与 #1812 现行重构验收为准。实况与奏报不混、读取同一份已有记录的原则不变；功能接续不在本切片重新设计。Accepted 不等于已实现。

月度进展与密奏逐月落库而非结案补记，restore 只读 DB 可接续；月报推送与垂问拉取共用同一份记录，不建平行存储。机械对账差额仍归被护案卷侧真实效果，进展可汇总多路叙事，不冒充实账。

#1895 修订的法源与执行归属引用 [0011](0011-edict-resistance-and-centrifuge-ledger.md#后出设计修订1895待票庭重审)与 [#1895](https://github.com/Akagilnc/ming-salvage-sim/issues/1895)，不在本 ADR 重立 4a 步骤或恢复协议。已建载体：GameDB.record_dossier_progress／list_dossier_progress 经 secret_orders.dossier_progress_json 私密轨和 dossier_reported_progress 通用轨持久读写；密令选择与执行态的相抵机制仍待改约重审，不因机制待改误称持久能力待建。
