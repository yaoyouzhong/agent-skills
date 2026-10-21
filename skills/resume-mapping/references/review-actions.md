# 复核回读与字段语义

> 本文件是可选脚本路径的复核回读契约，仅在宿主已有对应运行环境并选用这些工具时执行。默认使用 [宿主文档流程](host-workflow.md)，不要求用户安装 Python，也不强制原生文档工具生成相同 JSON/CSV。

先导出当前数据的队列，再回读决策；输出始终用新目录。

```text
PYTHON SKILL/scripts/review_actions.py --data TASK/data.json --sources TASK/sources.json --queue TASK/review-queue/queue.json --decisions TASK/decisions.json --outdir TASK/reviewed-v2
```

决策数组每项必须有 `id`（导出行 ID）、`action`、`reviewer` 和具体 `reason`。不接受批量设置 closed。工具重新执行规则、字段事实、日期毕业和原文审计，输出新数据、新清单及逐人剩余条目。

- `correct_field`：`expected_value`、`value`、`origin` 和必要的 `source_quotes`。origin 为 source_direct/source_assembled/source_inferred/not_provided/intentionally_blank；来源引文须为真实单元全文。未知、无法辨认不冒充未提供。
- `confirm_completion`：行必须是 education[n].status，提供 expected_value、basis、source_quotes 及对应证明信息。真实用户确认还须 confirmation_reference；不能由 Agent 编造确认来清零。
- `review_source`：对应 source_warnings 行，提供 source_id、all_source_content_reviewed=true。确实需要读图的来源还需 media_report 和 reviewed_assets（asset_id/asset_sha256/finding）；普通图片附件默认无需全部检查。质量复核不会清除独立的日期或事实冲突。
- `resolve_conflict`：对应 source_conflict 行，为该矛盾所有 retained_conflict 原文单元提供新的 coverage_decisions，保留原矛盾和理由历史，再重做来源审计。字段修正应通过同批字段决策完成。
- `defer`：保留问题，记录原因。不会批准空字段或毕业状态。

CSV 回读使用 decision/action、reviewer、decision_reason；`expected_value_json`、`value_json`、`source_quotes_json` 为 JSON 字面量，`origin` 为类型。额外证明放在 proof_json 对象。普通空字符串写 `""`，不要以 Excel 空单元格代替必需的 expected_value。CSV 源文字防公式转义，JSON 字段不执行代码。

## 毕业依据

`education_status_evidence` 继续绑定 education_binding(record)。新增 basis=`source_declared_graduation_date`：学校、明确的“毕业时间/年月/日期”标签及对应日期必须在同一来源记录，日期需与该教育 end 一致。普通结束时间、相邻学校日期、空毕业标签、预计/在读均不算。未来、无效或倒序日期仍由日期门禁阻止使用。

## 人物、客户和证书

person_source_scope 是 `{source_id:[unit_id,...]}`，可同时包括名册中该人的行和正文。它约束自动定位及字段引文。已复核图片的 owner_person_id 绑定数据人员 ID；identity_checks 可附 `{field,value}`，只核对已存在的身份信息，不为测试收集新的敏感号码。

客户补全候选会核对实体角色。明确实施方、供应商、厂商不补作客户。标题等上下文推断须 role_review={role:client,reviewer,reason,reviewed_quote}，reviewed_quote 与本次候选 quote 一致；无法判断仍留空。

人员 credentials 位于 fields 外，是证照审核元数据：每项 id/name/source_quotes，可分别填 obtained/issued/valid_until，used_as_current 指明是否用于当前资格主张。日期必须来自引文；英文日期可忠实转换。历史过期附件可保留；用于当前资格时，有效期未知/过期/精度不足会待核。续证可用 supersedes 关联同类旧证，不能据此鉴定真伪。
