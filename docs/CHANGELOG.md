# 版本历史

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.0.1]

**修复**

- 落地页页脚错位。`style.css` 里一条按元素名匹配的 `footer` 规则会命中
  `.site-footer` 并把它变成 flex 容器：免责声明与「Powered by」被挤进同一行，
  分隔线因此失去意义，站点名也继承了本不该有的浅灰色。两个页脚都自带 class
  并自行排版，该规则已删除。
- 页脚的源码链接（AGPL-3.0 §13 要求的那条）由脚本在运行时注入，是个没有 class
  的裸 `<a>`，此前没有任何样式命中它，渲染成浏览器默认的蓝色下划线链接。现在
  与「Powered by」的链接样式一致。

**维护**

- 删除 `static/css/style.css` 里重复的一整份样式表副本（384 行）。重复不改变
  渲染结果 —— 同优先级下后一份覆盖前一份 —— 但会让改动落在前一份上时毫无反应。
- 静态资源缓存串 `lite8` → `lite9`，否则已缓存的浏览器仍会拿到旧样式。

## [1.0.0]

首个公开版本。

**下载**

- 支持 Instagram、X / Twitter、TikTok、YouTube、抖音、哔哩哔哩。
- 双引擎：视频走 yt-dlp，图集走 gallery-dl，按链接自动选，失败互相兜底。
- 在线预览后按文件勾选下载，支持打包成 ZIP。
- 「获取可用画质」列出这条内容真实存在的分辨率与编码；默认不重新编码，
  浏览器放不了时可手动转成 H.264/AAC。
- 抖音 / TikTok 解析器链（自托管容器与 TikHub.io），解析失败自动回退 yt-dlp。

**部署与运维**

- Docker Compose 一条命令起服务，多架构镜像（AMD64 / ARM64）。
- 按平台分别配置代理与 Cookies，三种 Cookies 注入方式。
- 可选的管理后台：运行概览、任务管理、Cookies 上传、手动清理。
  不设 `ADMIN_TOKEN` 时整个后台返回 404。
- 按保留窗口 + 每日定时自动清理，正在下载的任务不会被删。

[Unreleased]: https://github.com/jinqians/FetchKeep/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/jinqians/FetchKeep/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/jinqians/FetchKeep/releases/tag/v1.0.0
