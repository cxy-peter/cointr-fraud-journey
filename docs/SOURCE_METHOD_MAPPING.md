# 资料方法约束映射

本文件记录对上传 PDF/DOCX 的“方法级”落地，不转录专有原文，不包含生产数据或真实阈值。

| 资料约束 | 代码/输出落点 | 可验证断言 |
|---|---|---|
| 标签约 52 天成熟；0 不是已证实正常 | `generator.py` 的 `label_observed_at`；复核队列 `INCONCLUSIVE_UNCONFIRMED` | 19 个已确认标签；所有高分 label-0 禁止自动改标 |
| Feature contract 与 PIT | `features.py`、`feature_contracts.csv` | definition/source/window/available_at/owner 六列齐全；只取 cutoff 前已到达 SUCCESS |
| 全币对与银行字段 | `asset_pair` 六个合成币对；`bank_user_name` 兼容 `bankUserName` | audit 输出币对、别名与非空覆盖率 |
| 时间差/闭环/小额/银行/设备/IP/地址优先；金额不稳定 | `MODEL_FEATURES` 与单特征诊断 | 包含 `fund_loop_cv`、`amount_diff_ratio`；金额仅是候选，不是规则结论 |
| Train/validation 泄漏隔离 | `models.py` | 五折随机 Stratified OOF；折内预处理；XGB 只下采样训练折；验证标签不参与 fit；不声称 OOT |
| Tree 可解释但不冒充验证 | `tree_rules.txt` | 业务单位阈值、OHE 回映；每条规则标记 `exploratory_full_fit_not_oof_validated` |
| Graph 强弱边、supernode 与路径证据 | `generator.py`、`graph.py` | IP=0.25；无 deposit address；过滤公共/归集/代理/supernode；时间/方向/金额/次数齐全 |
| Onboarding、T+1、override 历史保护 | SQLite `risk_profile_history` | T+1 仅用注册后 1 天前 available 事件；模型快照晚于全部输入；manual 保留来源/操作人/原因/时间 |
| STR 隔离与外发边界 | SQLite `str_cases`、`02_str_case_mart.sql` | 四状态字段分开；普通画像不含 STR；自动外发始终 false |
| SQL 工作方法 | `sql/*.sql` | grain/key、state/time、join cardinality、PIT、window/sequence、reconciliation 注释；无生产 schema |
| KEP 搜索边界 | `kep.py` | 人工登录；先调查号后参考号；只解析 Konu；排除 icra；NOT_FOUND/业务未回复拆分；timeout/resume |

## 数字口径隔离

- 上传资料可核验历史口径：1,273 条 CMS 记录、184 条疑似异常、抽样 20 条根因复核。
- 本项目压力测试：13,703 条确定性合成 KEP 案件。

前者是资料口径，后者是测试参数；报告、README 和代码均不得混称。资料中“既有链上出金策略 Precision 可接受而 Recall 偏低”只作为补充模型/图谱召回的业务动机，不把其历史混淆矩阵复制成 Demo 结果。
