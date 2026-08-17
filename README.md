# FetchKeep Lite

[![Docker](https://github.com/jinqians/FetchKeep/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/jinqians/FetchKeep/actions/workflows/docker-publish.yml)
[![CI](https://github.com/jinqians/FetchKeep/actions/workflows/ci.yml/badge.svg)](https://github.com/jinqians/FetchKeep/actions/workflows/ci.yml)
[![Docker Hub](https://img.shields.io/docker/pulls/jinqians/fetchkeep.svg)](https://hub.docker.com/r/jinqians/fetchkeep)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

FetchKeep 的开源自建版：粘贴链接，在线预览，挑出你要的文件再下载。

一个 Docker Compose 就能跑起来的 Web 下载器，没有账号体系，没有数据库，没有
外部依赖。支持 **Instagram、X / Twitter、TikTok、YouTube、抖音、哔哩哔哩**。

```bash
git clone https://github.com/jinqians/FetchKeep.git
cd FetchKeep
cp .env.example .env
echo 'FETCHKEEP_IMAGE=jinqians/fetchkeep:latest' >> .env
docker compose pull && docker compose up -d
# 打开 http://127.0.0.1:9080
```

---

## 目录

- [FetchKeep Lite](#fetchkeep-lite)
  - [目录](#目录)
  - [它能做什么](#它能做什么)
  - [快速开始](#快速开始)
  - [配置](#配置)
    - [代理](#代理)
    - [Cookies](#cookies)
    - [抖音 / TikTok 解析器](#抖音--tiktok-解析器)
    - [完整环境变量](#完整环境变量)
  - [管理后台](#管理后台)
  - [生产部署](#生产部署)
    - [常用运维命令](#常用运维命令)
  - [HTTP 接口](#http-接口)
  - [排查](#排查)
  - [项目结构](#项目结构)
  - [和 FetchKeep Pro 的区别](#和-fetchkeep-pro-的区别)
  - [发布](#发布)
  - [许可证](#许可证)
  - [免责声明](#免责声明)

---

## 它能做什么

| | |
| --- | --- |
| **先看再存** | 图片和视频先在页面里预览，勾选需要的再下载，不用整包拿走 |
| **画质可选** | 「获取可用画质」列出这条内容真实存在的分辨率、编码和大致体积 |
| **不做无谓转码** | 默认原样保存不重新编码；浏览器确实放不了时才由你手动触发一次 |
| **双引擎** | 视频走 yt-dlp，图集走 gallery-dl，按链接自动选，失败互相兜底 |
| **抖音解析器链** | 可选。绕开 yt-dlp 的页面提取，解析失败自动回退 |
| **管理后台** | 可选。运行概览、任务管理、Cookies 上传、手动清理 |
| **自动清理** | 按保留窗口 + 每日定时，正在下载的任务不会被删 |

平台差异：

| 平台 | 引擎 | 说明 |
| --- | --- | --- |
| Instagram | Reel/TV → yt-dlp，`/p/` → gallery-dl | 私密内容和快拍需要 Cookies |
| X / Twitter | gallery-dl | 图片与视频 |
| TikTok | yt-dlp（可走解析器） | 单一预混流，不需要 FFmpeg 合并 |
| YouTube | yt-dlp | H.264 只到 1080p，1440p/4K 是 VP9/AV1 |
| 抖音 | yt-dlp（**建议走解析器**） | 原生提取经常因平台反爬更新失效 |
| 哔哩哔哩 | yt-dlp | 纯 DASH 需合并；匿名封顶 480p |

---

## 快速开始

**要求**：Docker 与 Docker Compose。镜像自带 yt-dlp、gallery-dl、FFmpeg 和
Deno（YouTube 提取需要 JS 运行时），支持 **AMD64 / ARM64**。

**用发布的镜像**（推荐，不用本地编译，树莓派之类的机器上快很多）：

```bash
git clone https://github.com/jinqians/FetchKeep.git
cd FetchKeep
cp .env.example .env
echo 'FETCHKEEP_IMAGE=jinqians/fetchkeep:latest' >> .env
nano .env                                    # 其余配置全部可选，不改也能跑
docker compose pull && docker compose up -d
```

**从源码构建**（改过代码，或者想自己编译时）：

```bash
git clone https://github.com/jinqians/FetchKeep.git
cd FetchKeep
cp .env.example .env
docker compose up -d --build
```

镜像 tag：`latest` 跟着最新的版本发布走，`edge` 跟着 `main` 分支的每次提交走，
`v1.2.3` / `v1.2` / `v1` 是具体版本。生产环境建议钉死具体版本：

```env
FETCHKEEP_IMAGE=jinqians/fetchkeep:v1.0.0
```

**不用 Compose，只跑一条 `docker run`**（能起来，但代理、Cookies、解析器这些都要
自己一个个加 `-e`，长期部署还是建议用 Compose）：

```bash
docker run -d --name fetchkeep-lite --restart unless-stopped \
  -p 127.0.0.1:9080:9080 \
  -v "$PWD/data:/data" \
  -e SOURCE_URL=https://github.com/jinqians/FetchKeep \
  jinqians/fetchkeep:latest
```

访问 `http://127.0.0.1:9080`。确认服务正常：

```bash
curl http://127.0.0.1:9080/api/health
```

`status` 为 `ok` 表示三个下载工具都就位。首页的「服务状态」一节显示同样的信息。

**带上抖音解析器一起启动**（可选）。除了这条命令，`.env` 里还要写
`DOUYIN_PARSER_URL=http://douyin-parser:8000`——只开容器不给地址，应用不会去用它。
见[抖音 / TikTok 解析器](#抖音--tiktok-解析器)：

```bash
docker compose --profile douyin-parser up -d
```

---

## 配置

全部通过 `.env` 配置，改完重启容器生效：

```bash
docker compose up -d
```

### 代理

按平台分别设置，留空表示走 VPS 直连。只影响对应平台。

```env
INSTAGRAM_PROXY=
TWITTER_PROXY=
TIKTOK_PROXY=
YOUTUBE_PROXY=
DOUYIN_PROXY=socks5://user:password@1.2.3.4:1080
BILIBILI_PROXY=http://user:password@1.2.3.4:8080
```

支持 HTTP / HTTPS / SOCKS5，IPv6 地址要用方括号包起来。

配之前建议先在宿主机验证线路本身是通的——不然分不清是代理不通还是站点在拒绝：

```bash
curl -6 --proxy 'socks5h://user:password@[IPv6]:1080' https://api6.ipify.org
```

### Cookies

**Cookies 是服务端配置。** 公开的下载页面没有上传入口，也没有对应的 API——
cookie jar 就是导出它那个账号的活会话，无密码的公开页面能上传，等于对外收集
别人的会话。

三种配置方式，任选：

**① 放文件（推荐）**

浏览器扩展导出 Netscape 格式的 `cookies.txt`，按平台命名放进 cookies 目录：

```text
data/cookies/instagram.txt
data/cookies/youtube.txt
data/cookies/tiktok.txt
data/cookies/douyin.txt
data/cookies/bilibili.txt
```

**② 写进环境变量**

`<平台>_COOKIES`，内容是整份 cookies.txt。推荐 base64（`.env` 装不下带 Tab 的
多行文本），也接受把 Tab / 换行写成 `\t` 和 `\n`：

```bash
base64 -w0 cookies.txt    # Linux
base64 -i  cookies.txt    # macOS
```

```env
BILIBILI_COOKIES=IyBOZXRzY2FwZSBIVFRQIENvb2tpZSBGaWxlCi4uLg==
```

启动时写入对应文件（权限 600）。**环境变量优先于卷里的旧文件**，也就是说通过
后台传的文件会在下次重启时被它覆盖——后台会把这种情况标出来。

**③ 管理后台上传**

配了 `ADMIN_TOKEN` 之后在 `/admin` 里传，立即生效不用重启。见
[管理后台](#管理后台)。

**哪些平台需要**

| 平台 | 没有 Cookies 时 |
| --- | --- |
| 抖音 | 网页详情接口可能拒绝返回数据（配了解析器后大多用不上） |
| 哔哩哔哩 | 能下，但封顶 480p；`SESSDATA` 是解锁 1080p+ 的开关 |
| Instagram | 私密内容、快拍取不到 |
| YouTube | 触发「请登录以确认您不是机器人」时失败 |
| TikTok | 少数地区限制内容取不到 |

其它路径：`data/cookies/cookies.txt` 是老部署的遗留文件，仍作为 Instagram 的
兜底；`<平台>_COOKIE_FILE` 可以指向别处挂进来的文件（比如只读的 secret）。

`GET /api/health` 会报告每个平台是否已配置——只报告有无，不返回内容。

### 抖音 / TikTok 解析器

yt-dlp 的抖音提取器跟不上平台的 X-Bogus / A_Bogus 签名轮换，隔一阵就整个失效。
解析器链在 yt-dlp 之前把「解析出直链」这一步接管过去：

```text
URL → 解析器链 → 命中 → 直链下载（失败再用 HTTP 流式下载）
        │
        └── 全部失败 ──────────────→ 完整 yt-dlp 流程
```

**一个都不配时行为与纯 yt-dlp 完全一致**，不会因为没配就出错。

用自带的容器（两句都要写，只写地址容器根本不会启动）：

```env
COMPOSE_PROFILES=douyin-parser
DOUYIN_PARSER_URL=http://douyin-parser:8000
```

指向别处已有的实例则不需要开 profile。也支持 TikHub.io：

```env
TIKHUB_API_KEY=sk-...
PARSER_PRIORITY=self_hosted,tikhub    # 可选，默认就是这个顺序
```

两个安全下限：解析出来的直链会做 SSRF 校验（内网 / 环回 / 链路本地地址一律
拒绝，因为这个 URL 是本进程接着要去请求的）；下回来小于 64 KiB 视为失败——
抖音 CDN 拒绝请求时回的是 HTTP 200 加几百字节 JSON，没有下限那张错误页会被当成
`.mp4` 存下来并发布出去。

### 完整环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WEB_PORT` | `9080` | 宿主机端口。只有 compose 读它，容器内始终监听 9080 |
| `MAX_WORKERS` | `2` | 同时下载数 |
| `JOB_RETENTION_HOURS` | `24` | 文件保留窗口 |
| `YTDLP_SOCKET_TIMEOUT` | `30` | yt-dlp 静默 socket 超时（秒） |
| `ADMIN_TOKEN` | 空 | 管理后台口令，**留空则后台完全关闭** |
| `SOURCE_URL` | 空 | 源码仓库地址，显示在页脚。见[许可证](#许可证) |
| `FETCHKEEP_IMAGE` | 本地构建 | 改用发布的镜像，只有 compose 读它 |
| `<平台>_PROXY` | 空 | 代理出口，见 [代理](#代理) |
| `<平台>_COOKIES` | 空 | Cookie jar 内容，见 [Cookies](#cookies) |
| `<平台>_COOKIE_FILE` | `/data/cookies/<平台>.txt` | Cookie 文件路径 |
| `COOKIES_DIR` | `/data/cookies` | Cookies 目录 |
| `DOUYIN_PARSER_URL` | 空 | 自托管解析器地址 |
| `TIKHUB_API_KEY` | 空 | TikHub.io 密钥 |
| `PARSER_PRIORITY` | `self_hosted,tikhub` | 解析器优先级 |
| `PARSER_TIMEOUT` | `15` | 每个解析器的 HTTP 超时（秒） |

`<平台>` 取值：`INSTAGRAM` `TWITTER` `TIKTOK` `YOUTUBE` `DOUYIN` `BILIBILI`
（Cookies 不含 `TWITTER`——X / Twitter 走 gallery-dl，不需要）。

---

## 管理后台

```env
ADMIN_TOKEN=$(openssl rand -base64 24)
```

重启后打开 `/admin` 输入口令。

**不设 `ADMIN_TOKEN` 时，`/admin` 和全部 `/api/admin/*` 一律返回 404。**
这是刻意的：Lite 是无密码公开部署，一个默认敞开的后台就是对外开放的 Cookies
上传表单。

| 视图 | 内容 |
| --- | --- |
| 运行概览 | 工具就绪状态、解析器链、任务分布、并发占用、磁盘占用 |
| 下载任务 | 全部任务（可按状态过滤）、查看命令与日志、删除任务及文件 |
| 平台 Cookies | 各平台上传 / 删除 `cookies.txt`，显示大小、更新时间与来源 |
| 代理出口 | 只读，凭据打码 |
| 存储与清理 | 磁盘占用，手动触发「按保留窗口」或「全部清空」 |

口令走 `x-admin-token` 请求头（自定义头带不上跨站请求，CSRF 因此不用单独防），
浏览器端存在 sessionStorage，关掉标签页即失效。猜错只会让下一次回答变慢
（翻倍，上限 4 秒），不会锁定——锁定的话，反代后面任何人都能把管理员关在门外。

---

## 生产部署

默认监听 `0.0.0.0:9080`。。

建议前面放 Caddy / Nginx / Cloudflare Tunnel，并把 Compose 端口收到本机：

```yaml
ports:
  - "127.0.0.1:9080:9080"
```

其它注意事项：

- **磁盘**：文件存在 `./data/downloads`，按 `JOB_RETENTION_HOURS` 清理，另外
  每天 00:00 UTC 全清一次。4K 视频很占地方，留够空间。

- **抖音解析器容器**只对 compose 内网开放。它没有任何鉴权，发布到宿主机等于
  对外开了个公开代理。

### 常用运维命令

```bash
# 看日志（跟随输出）
docker compose logs -f downloader

# 改完 .env 之后生效
docker compose up -d

# 升级到最新发布版（用发布镜像时）
docker compose pull && docker compose up -d

# 升级（从源码构建时）
git pull && docker compose up -d --build

# 重启 / 停止
docker compose restart downloader
docker compose down

# 卸载：停容器并删掉下载文件和 Cookies。data/ 删掉就没了，先确认
docker compose down
rm -rf data/
```

升级只换容器，`data/` 是挂载卷不受影响。任务表存在内存里，重启后清空——正在
下载的任务会中断，磁盘上已经下完的文件还在。

---

## HTTP 接口

公开接口：

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

管理接口（全部需要 `x-admin-token` 头，未配置口令时返回 404）：

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

`quality` 取值：`compat`（默认，AVC/AAC，浏览器可直接预览）、`best`、`audio`，
或具体高度如 `1080`。

```bash
curl -X POST http://127.0.0.1:9080/api/jobs \
  -F 'url=https://www.bilibili.com/video/BV1GJ411x7h7' \
  -F 'quality=1080'
```

---

## 排查

**先看首页的「服务状态」**：某个组件不可用是部署问题，重试多少次都一样。

| 现象 | 原因与处理 |
| --- | --- |
| 提示 **429 / 412** | 站点在限流当前出口 IP，跟链接和 Cookies 无关。412 是 B 站的说法，隔几分钟自动恢复。等一会儿，或给该平台配代理 |
| 提示**需要 Cookies** | 站点要求验证，按 [Cookies](#cookies) 配置。抖音先检查解析器 |
| **抖音总是失败** | 配 `DOUYIN_PARSER_URL`。查日志：`docker compose logs --tail=50 downloader \| grep '\[parser\]'` |
| **B 站只有 480p** | 平台对匿名访问的限制，需要配 B 站 Cookies（关键是 `SESSDATA`） |
| **视频不能在线预览** | 编码不是浏览器能放的（HEVC/AV1）。文件本身没问题，点「转为兼容格式」或用本地播放器 |
| **YouTube 下不到 4K** | 选「最高画质」或具体分辨率。H.264 本身只到 1080p |
| **服务异常** | `docker compose logs downloader`，检查 yt-dlp / gallery-dl / FFmpeg |

查看容器内实际生效的环境变量：

```bash
docker exec fetchkeep-lite env | grep PROXY
```

单独用 yt-dlp 验证一条链接，判断是站点问题还是本服务的问题：

```bash
docker exec -it fetchkeep-lite yt-dlp --proxy 'socks5://...' 'https://...'
```

---

## 项目结构

```text
app/
  main.py         应用装配：FastAPI 实例、静态资源、路由、后台任务
  config.py       环境变量、路径、常量
  platform.py     平台识别（URL → 平台）、引擎选择
  cookies.py      Cookie 解析与服务端配置（含环境变量注入）
  proxy.py        各平台代理参数
  quality.py      画质解析、yt-dlp 参数构造、远端画质探测
  media.py        编解码探测、remux、转码、预览图、文件收集
  parsers.py      抖音 / TikTok 解析器链
  downloader.py   下载编排：引擎选择、回退、错误归类
  jobs.py         内存任务表与线程池
  cleanup.py      定时清理
  auth.py         管理后台鉴权
  routes/         HTTP 接口，按职责拆分
static/           首页、样式、图标
templates/        管理后台页面（不在 /static 下：没配口令时连页面外壳都拿不到）
data/             下载文件与 Cookies（挂载卷）
docs/CHANGELOG.md 版本历史
```

任务表只存在内存里，重启即清空；磁盘上的文件由保留窗口和定时清理管理。

---

## 和 FetchKeep Pro 的区别

Lite 是开源自建版，去掉了 Pro 里依赖账号体系和外部服务的部分：

| | Lite | Pro |
| --- | --- | --- |
| 账号 / 登录 | 无 | OIDC，套餐分级 |
| 任务存储 | 内存 | PostgreSQL |
| 代理 | 每平台一条，环境变量 | 代理池，自动故障转移、冷却、VPN Gate |
| 对象存储 | 无（本地磁盘） | S3 / R2 归档 |
| 订阅关注 | 无 | 关注账号自动下载 + 推送 |
| Telegram 机器人 | 无 | 有 |
| 后台 | 单口令 | 身份体系 + 用户 / 兑换码管理 |

下载能力本身（引擎、画质、解析器链、平台支持）两边一致。

---

## 发布

推送到 GitHub 后，`.github/workflows/` 里两个工作流会自动跑：

| 工作流 | 触发 | 做什么 |
| --- | --- | --- |
| `ci.yml` | 每次 push / PR | pyflakes + 冒烟测试（应用能起来、路由在、后台在没口令时确实是 404） |
| `docker-publish.yml` | push 到 main、打 `v*` tag | 构建 AMD64 + ARM64 镜像推到 Docker Hub |

**推镜像前要配两个 secret**（仓库 Settings → Secrets and variables → Actions）：

| Secret | 取值 |
| --- | --- |
| `DOCKERHUB_USERNAME` | Docker Hub 用户名 |
| `DOCKERHUB_TOKEN` | Docker Hub → Account Settings → Personal access tokens 生成的令牌，**不要用账号密码** |

命名空间从 `DOCKERHUB_USERNAME` 取，仓库名是 `docker-publish.yml` 里的
`IMAGE_NAME`（`fetchkeep`），合起来是 `jinqians/fetchkeep`——fork 之后只要配上
自己的 secret 就能推到自己的命名空间，不用改工作流。没配 secret 时工作流只构建
不推送，PR 也是如此（fork 来的 PR 拿不到 secret，这样既能验证 Dockerfile 没写坏，
又不会把未经审阅的代码推成镜像）。

发一个版本：

```bash
git tag v1.0.0 && git push origin v1.0.0
```

这会产出 `v1.0.0`、`v1.0`、`v1`、`latest` 四个 tag，并把本 README 同步成
Docker Hub 的仓库描述。`latest` 只跟版本 tag 走，不跟 `main`——让 `latest` 指向
未发布的提交，等于让所有用 `:latest` 的人替你做测试。

CI 刻意不测真实下载：那要去请求目标站点，会因为限流、地区限制和平台反爬更新而
随机失败，而一个经常无故变红的 CI 比没有 CI 更糟，人很快就会学会无视它。

---

## 许可证

[AGPL-3.0](LICENSE)。

和 MIT / Apache 最重要的区别：**你把改过的版本架在网上给别人用，就必须把你的
源码也公开**——不只是分发二进制时才触发。这是 AGPL 第 13 条。

所以如果你要公开部署：

```env
SOURCE_URL=https://github.com/jinqians/FetchKeep
```

页脚会显示指向它的源码链接，这是许可证自己建议的提供方式。改过代码的话请指向
你的 fork，而不是上游——使用者有权拿到的是**这个部署**的源码。没设置时启动日志
里会提醒一次。

---

## 免责声明

请只下载你自己发布的内容、已获授权的内容，或所在法域允许的合理使用范围内的
内容。是否合规由使用者自行负责，也请遵守各平台的服务条款。

目标网站的登录限制、反爬、IP 限流、Cookies 有效期、地区限制等都可能影响下载
成功率——这些是站点行为，不是本服务的故障。
