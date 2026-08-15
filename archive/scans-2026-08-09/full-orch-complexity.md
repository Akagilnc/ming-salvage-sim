先前超时的「零交叉引用导出」扫描已跑完：`dist`+`scripts` 共扫 **780** 个 export，其中 **241** 个在其它 JS 文件中无引用（例：`routeBuilderBeatToResidentJudge`、`judgeReviewLegSessionMode`、`admitRouteSmoke` 等）。

这只能说明「跨文件未引用」，**不能直接当死代码**——同文件自用、测试入口、或对外公开 API 都会落进这份名单。按宁缺毋滥，不追加进违宪清单。
