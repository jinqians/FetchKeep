# 版本历史

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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

[Unreleased]: https://github.com/jinqians/FetchKeep/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/jinqians/FetchKeep/releases/tag/v1.0.0
