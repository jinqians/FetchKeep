# FetchKeep Lite

[![Docker](https://github.com/jinqians/FetchKeep/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/jinqians/FetchKeep/actions/workflows/docker-publish.yml)
[![CI](https://github.com/jinqians/FetchKeep/actions/workflows/ci.yml/badge.svg)](https://github.com/jinqians/FetchKeep/actions/workflows/ci.yml)
[![Docker Hub](https://img.shields.io/docker/pulls/jinqians/fetchkeep.svg)](https://hub.docker.com/r/jinqians/fetchkeep)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

粘贴链接，在线预览，挑出你要的文件再下载。

---

## 目录

- [FetchKeep Lite](#fetchkeep-lite)
  - [目录](#目录)
  - [项目介绍](#项目介绍)
  - [快速开始](#快速开始)
    - [方式一：Docker Compose（推荐）](#方式一docker-compose推荐)
    - [方式二：docker run](#方式二docker-run)
    - [方式三：从源码构建](#方式三从源码构建)
    - [验证](#验证)
    - [升级、重启与卸载](#升级重启与卸载)
    - [放到公网之前](#放到公网之前)
  - [配置说明](#配置说明)
    - [代理](#代理)
    - [Cookies](#cookies)
    - [抖音 / TikTok 解析器](#抖音--tiktok-解析器)
    - [管理后台](#管理后台)
    - [完整环境变量](#完整环境变量)
  - [鸣谢](#鸣谢)
  - [许可证](#许可证)
  - [免责声明](#免责声明)

更多文档：[HTTP 接口](docs/api.md) ·
[排查](docs/troubleshooting.md) ·
[版本历史](docs/CHANGELOG.md)

---

## 项目介绍

FetchKeep Lite 是 FetchKeep 的开源自建版：一个 Docker 就能跑起来的 Web 下载器，
支持 **Instagram、X / Twitter、TikTok、YouTube、抖音、哔哩哔哩**。
**建议自行搭建，不公开搭建后的域名**


| | |
| --- | --- |
| **先看再存** | 图片和视频先在页面里预览，勾选需要的再下载 |
| **画质可选** | 「获取可用画质」列出这条内容真实存在的分辨率、编码和大致体积 |
| **不做无谓转码** | 默认原样保存不重新编码；浏览器确实放不了时才由你手动触发一次 |
| **双引擎** | 视频走 yt-dlp，图集走 gallery-dl，按链接自动选，失败互相兜底 |
| **抖音解析器链** | 可选。绕开 yt-dlp 的页面提取，解析失败自动回退 |
| **管理后台** | 可选。运行概览、任务管理、Cookies 上传、手动清理 |
| **自动清理** | 按保留窗口 + 每日定时，正在下载的任务不会被删 |

各平台的差异：

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

**要求**：Docker（Compose 方式还需要 Docker Compose）。镜像自带 yt-dlp、
gallery-dl、FFmpeg 和 Deno（YouTube 提取需要 JS 运行时），支持
**AMD64 / ARM64**，不需要在宿主机上装任何东西。

镜像发布在 Docker Hub：[`jinqians/fetchkeep`](https://hub.docker.com/r/jinqians/fetchkeep)


### 方式一：Docker Compose（推荐）

```bash
mkdir -p ~/fetchkeep && cd ~/fetchkeep
nano docker-compose.yml        # 内容见下方
docker compose up -d
```

```yaml
services:
  downloader:
    image: jinqians/fetchkeep:1.0.0
    container_name: fetchkeep-lite
    restart: unless-stopped
    ports:
      # 只监听本机。前面放反代；要直接对外就把 127.0.0.1: 去掉
      - "127.0.0.1:9080:9080"
    environment:
      # AGPL-3.0 §13：公开部署时指向你自己的仓库，见「许可证」
      SOURCE_URL: "https://github.com/jinqians/FetchKeep"
      # 留空则 /admin 与全部 /api/admin/* 返回 404
      ADMIN_TOKEN: ""
      MAX_WORKERS: "2"
      JOB_RETENTION_HOURS: "24"

      # 抖音 / TikTok 解析器链。全部留空 ⇒ 行为与纯 yt-dlp 一致，不会出错。
      # 要用下面那个 douyin-parser 容器，就把这行的注释去掉：
      # DOUYIN_PARSER_URL: "http://douyin-parser:8000"
      # TIKHUB_API_KEY: ""                      # 可选的商业 API
      # PARSER_PRIORITY: "self_hosted,tikhub"   # 默认就是这个顺序
      # PARSER_TIMEOUT: "15"

      # 代理与 Cookies 按需添加，变量名见「完整环境变量」
      # BILIBILI_COOKIES: "<base64>"
      # DOUYIN_PROXY: "socks5://user:password@1.2.3.4:1080"
    volumes:
      - ./data:/data

  # 可选：自托管的抖音 / TikTok 解析器。不需要就整段删掉。
  # 平时不启动，只有 --profile douyin-parser 才会拉起来。
  douyin-parser:
    image: evil0ctal/douyin_tiktok_download_api:latest
    container_name: douyin-parser
    profiles: ["douyin-parser"]
    restart: unless-stopped
    environment:
      TZ: "UTC"
    # 只对 compose 内网开放，不要用 ports 映射到宿主机：这个服务没有任何鉴权，
    # 谁能连上谁就能让它替自己抓任意抖音链接。
    expose:
      - "8000"
```

`./data` 空着就行，不用预先建子目录——应用启动时会自己创建 `downloads/` 和
`cookies/`。

**克隆仓库来用 Compose 也可以**，好处是能直接用 `.env.example` 里的完整变量注释，
配置从 `.env` 走而不用改 YAML：

```bash
git clone https://github.com/jinqians/FetchKeep.git
cd FetchKeep
cp .env.example .env
echo 'FETCHKEEP_IMAGE=jinqians/fetchkeep:1.0.0' >> .env
nano .env                                    # 其余配置全部可选，不改也能跑
docker compose pull && docker compose up -d
```

仓库里那份 `docker-compose.yml` 带 `build: .`：镜像能正常拉到时不会触发构建，但
一旦 pull 失败、或者你敲了 `--build`，它就会去找 Dockerfile。不想要这个行为就用
上面那份自己写的。

**带上抖音解析器一起启动**（可选）：

```bash
docker compose --profile douyin-parser up -d
```

**两件事都要做**：起容器（上面这条命令）**和**把地址配给应用
（`DOUYIN_PARSER_URL=http://douyin-parser:8000`）。只开容器不给地址，应用根本
不会去用它；只给地址不开容器，则每次解析都连不上再回退 yt-dlp。原理和 TikHub
的接法见[抖音 / TikTok 解析器](#抖音--tiktok-解析器)。

### 方式二：docker run

不装 Compose 也能跑，代价是每个配置项都要自己加一个 `-e`：

```bash
docker run -d --name fetchkeep-lite --restart unless-stopped \
  -p 127.0.0.1:9080:9080 \
  -v "$PWD/data:/data" \
  -e SOURCE_URL=https://github.com/jinqians/FetchKeep \
  -e MAX_WORKERS=2 \
  -e JOB_RETENTION_HOURS=24 \
  jinqians/fetchkeep:1.0.0
```

后台、代理、Cookies 同理，按需追加 `-e`（变量名见[完整环境变量](#完整环境变量)；
不加就是关闭 / 直连 / 无 Cookies）：

```bash
  -e ADMIN_TOKEN="$(openssl rand -base64 24)" \
  -e BILIBILI_PROXY=http://user:password@1.2.3.4:1080 \
  -e BILIBILI_COOKIES="$(base64 -w0 cookies.txt)" \
```

**要用抖音解析器，得先自己建一个网络。** Compose 会自动建网络并让容器之间按
服务名互相解析，`docker run` 不会——默认 bridge 网络不提供 DNS，
`http://douyin-parser:8000` 根本解析不出来。所以要显式建一个用户自定义网络，
把两个容器都放进去：

```bash
docker network create fetchkeep-net

# 解析器：不要加 -p，它没有任何鉴权，只能留在这个私有网络里
docker run -d --name douyin-parser --restart unless-stopped \
  --network fetchkeep-net \
  evil0ctal/douyin_tiktok_download_api:latest

# 主服务：加 --network，并把地址配给它
docker run -d --name fetchkeep-lite --restart unless-stopped \
  --network fetchkeep-net \
  -p 127.0.0.1:9080:9080 \
  -v "$PWD/data:/data" \
  -e SOURCE_URL=https://github.com/jinqians/FetchKeep \
  -e DOUYIN_PARSER_URL=http://douyin-parser:8000 \
  jinqians/fetchkeep:1.0.0
```

升级也得手动：`docker pull` 新镜像 → `docker rm -f` 旧容器 → 把上面那串参数
原样再敲一遍。少抄一个 `-e` 就是一个静默失效的配置，所以长期部署还是建议用
Compose。

### 方式三：从源码构建

改过代码，或者想自己编译时：

```bash
git clone https://github.com/jinqians/FetchKeep.git
cd FetchKeep
cp .env.example .env
docker compose up -d --build
```

树莓派之类的机器上构建会很慢（要编译依赖、装 Deno），能用发布的镜像就别本地构建。

### 验证

访问 `http://127.0.0.1:9080`。确认服务正常：

```bash
curl http://127.0.0.1:9080/api/health
```

`status` 为 `ok` 表示三个下载工具都就位。首页的「服务状态」一节显示同样的信息。

### 升级、重启与卸载

```bash
# 看日志（跟随输出）
docker compose logs -f downloader

# 改完配置之后生效
docker compose up -d

# 升级到最新发布版（用发布镜像时；钉了版本就先改 tag 再执行）
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

### 放到公网之前

默认监听 `0.0.0.0:9080`。建议前面放 Caddy / Nginx / Cloudflare Tunnel，并把端口
收到本机：

```yaml
ports:
  - "127.0.0.1:9080:9080"
```

其它注意事项：

- **磁盘**：文件存在 `./data/downloads`，按 `JOB_RETENTION_HOURS` 清理，另外
  每天 00:00 UTC 全清一次。4K 视频很占地方，留够空间。
- **抖音解析器容器**只对 compose 内网开放。它没有任何鉴权，发布到宿主机等于
  对外开了个公开代理。

---

## 配置说明

**变量名三种部署方式完全一样，只是写法不同**——下面各节
统一用 `.env` 的写法举例，按你用的方式对照着翻译：

| 部署方式 | 写在哪 | 写法 |
| --- | --- | --- |
| 方式一（精简 compose） | `docker-compose.yml` 的 `environment:` | `DOUYIN_PROXY: "socks5://..."` |
| 方式一（克隆仓库） | 同目录的 `.env` | `DOUYIN_PROXY=socks5://...` |
| 方式二（docker run） | 命令行 | `-e DOUYIN_PROXY=socks5://...` |

⚠️ **精简 compose 旁边放 `.env` 是不生效的**，而且不会报错。Compose 的 `.env`
只用来给 compose 文件做变量替换（`${VAR}`），不会自动注入容器；仓库那份 compose
能读到，是因为它每行都写了 `DOUYIN_PROXY: "${DOUYIN_PROXY:-}"`。精简版是硬编码
的字面值，所以要改就改 `environment:` 那几行本身。

改完重启容器生效：

```bash
docker compose up -d          # 方式一 / 方式三
docker rm -f fetchkeep-lite   # 方式二：删掉重跑，参数原样再敲一遍
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

用自带的容器要做**两件事**：把容器起起来，再把地址配给应用。只做一件都等于没配。

| 部署方式 | 起容器 | 配地址 |
| --- | --- | --- |
| 方式一（精简 compose） | `docker compose --profile douyin-parser up -d` | `environment:` 里加 `DOUYIN_PARSER_URL` |
| 方式一（克隆仓库） | `.env` 里写 `COMPOSE_PROFILES=douyin-parser` | `.env` 里写 `DOUYIN_PARSER_URL` |
| 方式二（docker run） | 见[方式二](#方式二docker-run)，要先建网络 | `-e DOUYIN_PARSER_URL=...` |

地址统一是 `http://douyin-parser:8000`——靠 Compose 网络里的服务名解析，所以
`docker run` 必须自己建用户自定义网络，默认 bridge 解析不出这个名字。

指向别处已有的实例则不需要起容器，填那个实例的地址即可。也支持 TikHub.io：

```env
TIKHUB_API_KEY=sk-...
PARSER_PRIORITY=self_hosted,tikhub    # 可选，默认就是这个顺序
```

两个安全下限：解析出来的直链会做 SSRF 校验（内网 / 环回 / 链路本地地址一律
拒绝，因为这个 URL 是本进程接着要去请求的）；下回来小于 64 KiB 视为失败——
抖音 CDN 拒绝请求时回的是 HTTP 200 加几百字节 JSON，没有下限那张错误页会被当成
`.mp4` 存下来并发布出去。

### 管理后台

生成一个口令填进去。**注意别把 `$(openssl ...)` 原样写进 `.env`**——`.env` 不做
命令替换，那样存进去的会是这串字面文本，而不是随机口令：

```bash
openssl rand -base64 24        # 把输出填到 ADMIN_TOKEN
```

```env
ADMIN_TOKEN=zK3n8Qw1p...
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

## 鸣谢

这个项目本身只是编排层——真正把文件取下来的是下面这些开源项目：

| 项目 | 在这里做什么 | 许可证 |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 视频引擎：提取、选流、下载 | Unlicense |
| [gallery-dl](https://github.com/mikf/gallery-dl) | 图集引擎：Instagram `/p/`、X / Twitter | GPL-2.0 |
| [FFmpeg](https://ffmpeg.org/) | DASH 合并、转码、抽预览图、编解码探测 | LGPL-2.1+ / GPL-2+ |
| [Deno](https://github.com/denoland/deno) | YouTube 提取所需的 JS 运行时 | MIT |
| [yt-dlp/ejs](https://github.com/yt-dlp/ejs) | 配合 Deno 求解 YouTube 的 JS 挑战 | Unlicense |
| [FastAPI](https://github.com/fastapi/fastapi) | Web 框架 | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | BSD-3-Clause |
| [curl-cffi](https://github.com/lexiforest/curl_cffi) | TLS 指纹模拟，绕过部分站点的客户端识别 | MIT |
| [Requests](https://github.com/psf/requests) | HTTP 客户端 | Apache-2.0 |
| [python-multipart](https://github.com/Kludex/python-multipart) | 表单解析 | Apache-2.0 |
| [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | 可选的自托管抖音 / TikTok 解析器容器 | Apache-2.0 |

平台反爬每隔一阵就会更新一轮，这些项目的维护者在持续跟进——本项目能用，几乎
全靠他们。遇到某个平台下不动，先 `docker compose pull` 拉个新镜像，多数情况是
上游已经修好了。

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
