# voipms-mcp — 模块事实

追加式文档：每张单交付后加一节 `## PRD-XXXXX · <日期>`，不改写既有小节。引用一律带 `path:line` + commit sha；本文件目前只在工作分支 `dev01.mbagent/PRD-18607` 上存在（该分支尚未合入 `main`），所以下面的 sha 全部以这条工作分支为锚，不是已发布事实——人工合入 `main` 后应重新核对这些引用是否仍然成立。

## PRD-18607 · 2026-09-10

**这个仓库从这张单才第一次有代码。** 之前只有一份 `README.md` 脚手架（`eb772ac`），没有任何实现。

- 服务形态：Python 3.12 + FastMCP（Streamable HTTP，`stateless_http=True`），四个工具，见 `src/voipms_mcp/tools/subaccounts.py`（`dev01.mbagent/PRD-18607` @ `5565e98`）。
- 凭据模型：只从 Header 读（`X-Voipms-Api-Username` / `X-Voipms-Api-Password`），`contextvars.ContextVar` 做请求级隔离，`finally` 里 reset——`src/voipms_mcp/server.py:38-118`（同上 sha）。**不缓存**、**不落环境变量**。
- `voipms_set_voicemail_redirect` 强制 read-modify-write：`src/voipms_mcp/tools/subaccounts.py:141-183`。**已核实**（非假设）vendor `setSubAccount` 确实要求整份记录写回——对照公开的 `python-voipms` 参考实现（<https://github.com/4doom4/python-voipms>）确认，见 `src/voipms_mcp/api_client.py:1-24` 的模块文档字符串。这条约束是本仓库存在的原因，之后任何改动都不能把它退化成单字段写。
- 错误信封与错误码词汇表固定在 `src/voipms_mcp/errors.py:11-40`（同上 sha），遵循工单附件 `vendor-mcp-development-sop 1.md` §4.2，不要自造新 code。
- 已知未验证：真实 VOIP.ms 账号的端到端联调（需要客户凭据，尚未提供）；Docker 镜像实际构建（本机 Docker daemon 未运行）。两者详情见 `docs/tickets/PRD-18607.md` 「自测」一节「本地验证的已知盲区」。
- 尚未完成的跨仓库依赖：`mcp-service-gateway/vendor/registry.yaml` 还没有 `voipms` 条目，这个连接器目前对产品 Library 不可见。见 `docs/tickets/PRD-18607.md` 「交接」一节。
