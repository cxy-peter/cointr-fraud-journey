# CoinTR Fraud Journey 合成运行报告

## 本次实际运行

- 固定随机种子：`20260728`
- 用户：**1200**
- 已确认合成 Fraud 标签：**19**
- 时间戳事件：**105318**
- 可解释未标记 Graph 候选：**15**
- 人工复核队列：**50**
- KEP 合成案件：**13703**

| 模型 | OOF AUC | OOF KS | OOF Average Precision | Tie-aware Lift@10% | Tie-aware Lift@20% |
|---|---:|---:|---:|---:|---:|
| decision_tree_depth3 | 0.901711 | 0.809082 | 0.214236 | 8.510687 | 4.338083 |
| xgboost_oof | 0.964704 | 0.855920 | 0.560990 | 8.947368 | 4.736842 |

Tree 文本是全量样本拟合后的探索性规则，全部标记为 `exploratory_full_fit_not_oof_validated`；其中叶节点正例率不是验证结果。XGBoost/Tree 指标来自五折随机 Stratified OOF；每折预处理和 XGBoost 1:4 负样本抽样不读取验证折标签。这里没有宣称 OOT/时间外推验证，也没有输出 OOT 指标。

## 资料约束如何落地

- **Feature contract**：`feature_contracts.csv` 为每个变量给出定义、来源、窗口、`available_at` 和 owner。金额仅是候选之一；资金闭环、时间差、小额入金、银行、设备/IP/地址与图谱变量优先并列呈现，交易覆盖全部合成币对。API/夜间占比只做 context-only 描述，不进入 Tree/XGBoost，也不能单独转规则。
- **约 52 天标签成熟期与 PIT**：标签观察时间固定为注册后 52 天；特征截止为标签观察日前 7 天，只使用截止时已到达且状态为 `SUCCESS` 的事件。当前标签 0 表示未确认/未观察到，不等于真实正常。
- **Graph**：Device/Email/Phone/KYC/Withdraw Address 为强边，IP 权重仅 0.25；公共 IP、交易所归集/企业代理前缀和度数超阈值 supernode 被过滤；入金地址不建图。路径证据含两侧时间、方向、金额和事件数。
- **审核容量**：50 个席位采用可审计双通道，35 个来自 XGBoost OOF 排序，15 个来自可解释 Graph 补召回；去重后补满，并输出 overlap/swap-in/swap-out。XGBoost 因训练折 1:4 下采样而未做概率校准；综合分使用 OOF 百分位与图证据，仅用于队列内排序，不解释为欺诈概率。SQLite risk band 也仅是 synthetic/demo-only 展示。
- **人工复核与 STR**：15 个 Graph 候选和 50 条高分 label-0 记录只进入人工复核，`automatic_relabel_allowed=false`。STR 是隔离的内部候选表，不进入普通客户画像，不自动外部报送。
- **风险画像历史**：Onboarding 静态快照；注册后 T+1 只用截至当天 `available_at` 的弱规则；综合模型另在所有模型/Graph 输入已可用后的 `MODEL_CUTOFF_DYNAMIC` 记录；人工 override 分行保存。风险来源、operator、reason、timestamp 完整保留，动态刷新不会覆盖当前人工 override。
- **SQL**：四份 SQL 都注明 grain/key、状态/时间、join cardinality、PIT 与 reconciliation 口径；仅使用本项目合成 schema，不映射生产表。
- **KEP**：现场浏览器必须人工登录；离线确定性匹配先 `sorusturma_no` 后 `sayi/reference`，只读 `Konu:` 边界，排除 icra，并将 `NOT_FOUND` 与业务未回复拆开；结果含 90 秒 timeout 与 case_id resume key。
- **AI/Playwright**：AI 只建议抽取/摘要；编号匹配、状态迁移、权限、对外提交和资金处置保持确定性校验与人工确认。

## KEP 压力测试（全部为合成）

- MATCH_SORUSTURMA: 12068
- MATCH_SAYI: 939
- EXCLUDED_ICRA: 378
- NOT_FOUND: 120
- BUSINESS_NO_RESPONSE: 63
- AMBIGUOUS_MULTIPLE: 135

**数字口径隔离**：上传资料中可核验的是 1,273 条 CMS 记录、184 条疑似异常、抽样 20 条根因复核；上面的 13,703 条只是本仓库的合成压力测试。两组数字不可混称。

## 真实性边界

所有实体、事件、案件、邮件、阈值和结果均为确定性合成。本报告没有复用材料中的历史混淆矩阵，也不声称代表 CoinTR 生产系统或真实策略效果。材料提到的“链上出金策略 Precision 可接受但 Recall 偏低”仅作为为何要探索模型与图谱补充召回的业务动机；此处指标只证明代码链路可运行。
