# HTTP 接口

← 回到 [README](../README.md)

服务不需要账号，公开接口直接调用即可。管理接口需要口令。

## 公开接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 工具与配置状态 |
| `GET` | `/api/info` | 同上（别名） |
| `POST` | `/api/probe` | 探测可用画质，表单字段 `url` |
| `POST` | `/api/jobs` | 建任务，表单字段 `url` `engine` `quality` |
| `GET` | `/api/jobs/{id}` | 任务状态与文件列表 |
| `GET` | `/api/jobs/{id}/files` | 只要文件列表 |
| `GET` | `/api/jobs/{id}/files/{path}` | 取单个文件，`?download=1` 触发下载 |
| `GET` | `/api/jobs/{id}/download` | 单文件任务的直接下载（多文件任务返回 400） |
| `POST` | `/api/jobs/{id}/download-selected` | 打包选中文件为 ZIP |
| `POST` | `/api/jobs/{id}/transcode` | 转 H.264/AAC，JSON `{"path": "..."}` |
| `DELETE` | `/api/jobs/{id}` | 删除任务及文件 |

`quality` 取值：`compat`（默认，AVC/AAC，浏览器可直接预览）、`best`、`audio`，
或具体高度如 `1080`。

```bash
curl -X POST http://127.0.0.1:9080/api/jobs \
  -F 'url=https://www.bilibili.com/video/BV1GJ411x7h7' \
  -F 'quality=1080'
```

`GET /api/health` 会报告每个平台的 Cookies 是否已配置——只报告有无，不返回内容。

## 管理接口

全部需要 `x-admin-token` 请求头。**未配置 `ADMIN_TOKEN` 时一律返回 404**，
不是 401——没开这个功能时，连「这里有个后台」都不该暴露出去。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/admin/overview` | 运行概览 |
| `GET` | `/api/admin/jobs` | 任务列表，`?status=` 过滤 |
| `GET` | `/api/admin/jobs/{id}/log` | 该任务的命令与输出 |
| `DELETE` | `/api/admin/jobs/{id}` | 删除任务 |
| `GET` | `/api/admin/cookies` | 各平台 Cookies 状态 |
| `POST` | `/api/admin/cookies/{platform}` | 上传 cookies.txt |
| `DELETE` | `/api/admin/cookies/{platform}` | 删除 |
| `GET` | `/api/admin/proxies` | 代理配置（凭据打码） |
| `POST` | `/api/admin/maintenance/cleanup` | 手动清理，`?scope=expired\|all` |

口令的配置方式见 README 的[管理后台](../README.md#管理后台)一节。
