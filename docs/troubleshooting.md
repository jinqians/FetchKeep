# 排查

← 回到 [README](../README.md)

**先看首页的「服务状态」**：某个组件不可用是部署问题，重试多少次都一样。

## 常见现象

| 现象 | 原因与处理 |
| --- | --- |
| 提示 **429 / 412** | 站点在限流当前出口 IP，跟链接和 Cookies 无关。412 是 B 站的说法，隔几分钟自动恢复。等一会儿，或给该平台配代理 |
| 提示**需要 Cookies** | 站点要求验证，按 [Cookies](../README.md#cookies) 配置。抖音先检查解析器 |
| **抖音总是失败** | 配 `DOUYIN_PARSER_URL`。查日志：`docker compose logs --tail=50 downloader \| grep '\[parser\]'` |
| **B 站只有 480p** | 平台对匿名访问的限制，需要配 B 站 Cookies（关键是 `SESSDATA`） |
| **视频不能在线预览** | 编码不是浏览器能放的（HEVC/AV1）。文件本身没问题，点「转为兼容格式」或用本地播放器 |
| **YouTube 下不到 4K** | 选「最高画质」或具体分辨率。H.264 本身只到 1080p |
| **服务异常** | `docker compose logs downloader`，检查 yt-dlp / gallery-dl / FFmpeg |

## 定位手段

看服务日志：

```bash
docker compose logs -f downloader
```

查看容器内实际生效的环境变量（确认 `.env` 真的被读到了）：

```bash
docker exec fetchkeep-lite env | grep PROXY
```

单独用 yt-dlp 验证一条链接，判断是站点问题还是本服务的问题：

```bash
docker exec -it fetchkeep-lite yt-dlp --proxy 'socks5://...' 'https://...'
```

## 某个平台整体失效

平台反爬每隔一阵就会更新一轮，上游工具通常几天内跟进。先拉个新镜像：

```bash
docker compose pull && docker compose up -d
```

多数情况是上游已经修好了。抖音例外——它的签名轮换太快，建议直接走
[解析器链](../README.md#抖音--tiktok-解析器)而不是等 yt-dlp 修。
