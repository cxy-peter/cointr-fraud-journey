# CoinTR Fraud Journey + SQL Risk Profile Demo

这是一个完全独立、可重复运行的合成数据项目。它把支付与数字资产风控材料中的通用方法论转成最小可运行代码：用户生命周期事件、Fraud 候选特征、浅层 Decision Tree、折内隔离的五折 XGBoost OOF、Risk Graph、人工复核队列、SQLite/SQL 客户画像，以及 KEP 邮件主题确定性匹配。

## 真实性与使用边界

- 所有用户、事件、案件、邮件、指标和模型结果均为固定随机种子生成的合成数据。
- 项目不包含 CoinTR 或任何公司的生产数据、内部原文、账号、密钥、阈值、系统连接或自动处置能力。
- 项目仅重建通用分析方法，不代表 CoinTR 的生产架构、线上模型、真实策略效果或个人独立开发了相关生产系统。
- 高分、图谱关联和 KEP 匹配结果只进入人工复核；不会自动改标签、冻结账户、限制资金或提交 STR/监管回复。
- `fraud_label=0` 只表示合成标签中未确认 Fraud，不自动等于正常；高分负样本保留为人工复核候选。

## 固定运行契约

- 1,200 个合成用户；
- 精确 19 个 Fraud 标签；
- 精确 105,318 条带时间戳事件；
- 注册 -> KYC -> 法币入金 -> 现货/API 交易 -> 链上出金生命周期；
- Device、IP、Email、Phone、KYC ID 与 Withdraw Address 关系；IP 权重较弱，不使用入金地址建图；
- 五折随机 Stratified OOF，折内预处理与训练集负样本下采样；它不是 OOT/时间外推验证；
- 15 个可解释未标记图谱候选；
- 50 条高分负样本人工复核队列；
- 13,703 条合成 KEP 压力测试案件。

`13,703` 只是本项目为了稳定性测试设定的合成规模。上传资料中可核验的历史口径是 **1,273 条 CMS 记录、184 条疑似异常、抽样 20 条根因复核**；两组数字不可互换，也不可把合成压力测试写成真实业务量。

## 运行

```powershell
python -m pip install -e ".[dev]"
python scripts/run_demo.py
pytest
```

主运行会重建确定性输出和 `outputs/cointr_fraud_demo.sqlite`。事件明细只存在 SQLite 中，不额外提交庞大的 raw event CSV。核心结果写入：

- `outputs/model_metrics.csv`
- `outputs/single_feature_metrics.csv`
- `outputs/tree_rules.txt`
- `outputs/graph_top15_candidates.csv`
- `outputs/human_review_queue.csv`
- `outputs/kep_match_results.csv`
- `outputs/sql_results/`
- `outputs/RUN_REPORT.md`

## 方法约束

事件特征只统计 `SUCCESS` 终态，避免 pending/success 重复入账。每项特征在 `feature_contracts.csv` 明确 definition/source/window/available_at/owner；特征截止早于约 52 天的标签观察点并执行 PIT 检查。API/夜间占比保留为 context-only 描述，因其不具有通用风险方向，不进入 Tree/XGBoost，也不能单独转规则。单特征分析用于描述，不参与 OOF 验证折选择。XGBoost 的预处理和 1:4 负样本下采样只在每个训练折完成，验证折从不重采样或用于 fit。五折是随机 Stratified OOF，不是 OOT/时序外推验证；项目不输出或冒充 OOT 指标。Tree 数值特征不标准化，因此规则阈值保持业务单位；类别 one-hot 分支还原为 `==` / `!=` 条件；最终全量 Tree 规则显式标记 `exploratory_full_fit_not_oof_validated`。Lift 对分数 ties 做比例捕获，不由输入行顺序挑选。

Risk Graph 的强边为 KYC/Device/Mobile/Email/Withdraw Address，IP 权重仅 0.25；公共 IP、交易所归集/企业代理前缀和 supernode 被过滤，入金地址不建图。路径证据包含两侧时间、方向、金额和事件数。Onboarding、注册后 T+1 可用事件弱规则、模型输入完全可用后的动态快照，以及人工 override 分层留历史；override 保留 source/operator/reason/timestamp，后续批处理不覆盖。普通客户画像 SQL 不包含 STR 案件细节，STR 仅是内部候选且不可自动外部提交。

50 条人工容量采用显式双通道：35 个 XGBoost OOF 排序席位 + 15 个可解释 Graph 补召回席位，按 UID 去重后补满；输出 overlap、swap-in、swap-out 与每条 `selection_lane`。XGBoost 因折内 1:4 下采样而未做概率校准，综合分使用 OOF 百分位与 Graph 证据，只是调查优先级，不是联合模型概率；SQLite 中的风险 band 也仅供 synthetic/demo 展示。

KEP 合成层先查 `sorusturma_no`，再查 `sayi/reference`，只解析严格 `Konu:` 段，排除 icra，并把 `NOT_FOUND` 与业务未回复分开。真实浏览器接入必须人工登录、支持 90 秒 timeout/按 case_id resume，禁止自动发送。详见 `docs/SOURCE_METHOD_MAPPING.md`、`docs/AI_AUTOMATION_BOUNDARIES.md` 和 `docs/PLAYWRIGHT_BOUNDARY.md`。

## 资料使用说明

项目仅采用参考材料中可公开复述的通用概念，例如 PIT、成熟标签、资金闭环、事件窗口、图关系强弱、人工复核、KEP 编号优先级和监管外发边界。没有复制材料中的专有原文、真实记录或敏感字段值。

## License

MIT。部分建模与图谱设计沿用 `digital-asset-cex-risk-strategy-ai-copilot` 中的通用实现思路；保留原作者版权声明。第三方 Python 包适用各自许可证。
