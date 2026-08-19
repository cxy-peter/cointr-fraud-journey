# Playwright / KEP 接入边界

本仓库不包含真实 KEP/CMS 自动化。若未来在获授权环境增加 Playwright 包装层，必须遵守：

1. 人工完成登录和多因素验证；脚本不保存或绕过凭证。
2. 只读搜索；先 `sorusturma_no`，无唯一结果再查 `sayi/reference`。
3. 仅解析明确 `Konu:` 段，要求合格的 OUTGOING/ORIGINAL 语义，排除 `icra`。
4. `NOT_FOUND`、`BUSINESS_NO_RESPONSE`、多结果分别进入人工复核。
5. 单案 timeout 90 秒，以 `case_id` 为 checkpoint/resume key，记录查询键和匹配证据。
6. 禁止自动发送、删除、修改案件、外部报送或产生监管含义判断。

当前 `kep.py` 只是可重复的离线合成压力测试；13,703 是测试参数。资料中的 1,273 CMS / 184 异常 / 抽样 20 是独立历史口径，不是本次运行结果。
