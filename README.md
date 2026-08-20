# CoinTR Fraud Journey + SQL Risk Profile Demo

这是一个完全独立、可重复运行的合成数据项目。它把支付与数字资产风控材料中的通用方法论转成最小可运行代码：用户生命周期事件、Fraud 候选特征、浅层 Decision Tree、折内隔离的五折 XGBoost OOF、Risk Graph、人工复核队列、SQLite/SQL 客户画像，以及 KEP 邮件主题确定性匹配。

## 结果与方法报告

- [中文完整结果报告：执行过程、关键指标、边界与复现](docs/RESULT_REPORT_ZH.md)
- [Fraud Journey 分析与模型面试综合报告（公开脱敏版）](docs/COINTR_FRAUD_JOURNEY_ANALYSIS_CN.md)
- [流水线自动生成的简版运行摘要](outputs/RUN_REPORT.md)
- [后续 Codex 实现任务](docs/CODEX_FRAUD_JOURNEY_TASK.md)

## Source-aligned Fraud Journey 层

现有固定 Demo 保留原有的确定性运行契约；新增的 source-aligned 层用于审计“材料中的分析流程”与“公开合成项目目前能支持的字段”之间的差距，而不是再叠加一个通用 AI Agent。

```text
现有策略基线
→ 黑 / 白 / 未标记 / 排除账户口径
→ 交易币对与行为范围
→ 银行数据质量
→ 金额、时间、比例和计数特征
→ 单特征有效性
→ 黑用户全链路
→ 清洗后的行为序列
→ 链上与 Risk Graph
→ 浅层 Tree
→ XGBoost / 可选 LightGBM
→ 在线、离线策略和生命周期
```

核心控制包括：

- `fraud_label=0` 不等于经过业务确认的白样本；
- 交易币对是分群变量，不是单独的 Fraud 定义；
- 在过滤自动系统/子事件之前，原始 60 分钟 Session 密度无效；
- `1:4` 是当前固定 Demo 的兼容性默认值，也是材料比较过的候选之一，但不是先验最佳比例；
- 后续版本应在 Development 比较自然分布、1:3、1:4、1:5，并在自然分布的时间外 OOT 上评价；
- 欠采样模型分在校准前不能解释为真实欺诈概率。

生成 source-aligned 审计文件：

```powershell
python scripts/run_source_aligned_fraud_journey.py
```

输出目录为 `outputs/fraud_journey/`，包括分析步骤、样本口径、模型实验网格、字段覆盖、特征预览、清洗后的 Session 预览和自动生成报告。

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

`13,703` 仅为本项目的合成压力测试规模，不代表真实业务量；公开仓库不披露真实案件数量。

## 运行

```powershell
python -m pip install -e ".[dev]"
python scripts/run_demo.py
python scripts/run_source_aligned_fraud_journey.py
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
- `outputs/fraud_journey/`

## 方法约束

事件特征只统计 `SUCCESS` 终态，避免 `FAILED`/`PENDING` 事件进入特征；本 Demo 没有实现基于业务交易键的状态去重。每项特征在 `feature_contracts.csv` 明确 definition/source/window/available_at/owner；特征截止早于约 52 天的标签观察点并执行 PIT 检查。API/夜间占比保留为 context-only 描述，因其不具有通用风险方向，不进入 Tree/XGBoost，也不能单独转规则。单特征分析用于描述，不参与 OOF 验证折选择。XGBoost 的预处理和 1:4 负样本下采样只在每个训练折完成，验证折从不重采样或用于 fit。五折是随机 Stratified OOF，不是 OOT/时序外推验证；项目不输出或冒充 OOT 指标。Tree 数值特征不标准化，因此规则阈值保持业务单位；类别 one-hot 分支还原为 `==` / `!=` 条件；最终全量 Tree 规则显式标记 `exploratory_full_fit_not_oof_validated`。Lift 对分数 ties 做比例捕获，不由输入行顺序挑选。

Risk Graph 的强边为 KYC/Device/Phone（Mobile）/Email/Withdraw Address，IP 权重仅 0.25；公共 IP、交易所归集/企业代理前缀和 supernode 被过滤，入金地址不建图。路径证据包含两侧时间、方向、金额和事件数。单次合成运行把 Onboarding、注册后 T+1 弱规则、模型输入可用后的动态快照和人工 override 分层写入历史表，并让人工 override 成为 current；当前 SQLite 每次重建，未实现生产级不可变存储或跨批次刷新保护。普通客户画像 SQL 不包含 STR 案件细节，STR 仅是内部候选且不可自动外部提交。

50 条人工容量采用显式双通道：35 个 XGBoost OOF 排序席位 + 15 个可解释 Graph 补召回席位，按 UID 去重后补满；输出 overlap、swap-in、swap-out 与每条 `selection_lane`。XGBoost 因折内 1:4 下采样而未做概率校准，综合分使用 OOF 百分位与 Graph 证据，只是调查优先级，不是联合模型概率；SQLite 中的风险 band 也仅供 synthetic/demo 展示。

KEP 合成层先查 `sorusturma_no`，再查 `sayi/reference`，只解析严格 `Konu:` 段，排除 icra，并把 `NOT_FOUND` 与业务未回复分开。真实浏览器接入必须人工登录、支持 90 秒 timeout/按 case_id resume，禁止自动发送。详见 `docs/SOURCE_METHOD_MAPPING.md`、`docs/AI_AUTOMATION_BOUNDARIES.md` 和 `docs/PLAYWRIGHT_BOUNDARY.md`。

## 资料使用说明

项目仅采用参考材料中可公开复述的通用概念，例如 PIT、成熟标签、资金闭环、事件窗口、图关系强弱、人工复核、KEP 编号优先级和监管外发边界。没有复制材料中的原始记录或敏感字段值。

## License

MIT。部分建模与图谱设计沿用 `digital-asset-cex-risk-strategy-ai-copilot` 中的通用实现思路；保留原作者版权声明。第三方 Python 包适用各自许可证。
