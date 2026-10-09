# Web Invite

**中文说明** | [English](#english)

Web Invite 是一款本地优先的邀请函图片个性化工具：上传 PSD 模板，在浏览器中填写多个文字字段、实时预览，并批量导出 PNG。它使用 Canvas 绘制可编辑文字；本地 Python 服务负责模板存储和文件输出。

本项目适合邀请函、证书、名牌等**多字段批量个性化**，不是通用 Photoshop Action 播放器，也不保证完整还原任意 PSD 效果。

## 功能

- 检查 PSD 文字图层并建议可编辑字段
- 浏览器 Canvas 实时预览，可加载用户提供的字体
- 普通文字、下划线填空、互斥选项字段
- CSV、TSV、XLSX 名单导入、列映射和预览
- 导出前检查、版本墙和批量 PNG 导出
- 手机端预览、填写、名单和版本视图
- 本地模板 ZIP 备份与恢复
- 可选打包为只读访客静态网站

## 环境要求

- Python 3.10 或更高版本
- 依赖见 `requirements.txt`
- XLSX 解析库已随仓库放在 `vendor/`，附 Apache-2.0 许可证；运行时不需要 Node.js
- 自行准备有权使用的 PSD 模板和字体

## 快速开始

1. 创建并启用 Python 虚拟环境。
2. 安装依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. 在当前终端设置自己的管理钥匙和页面密码。请使用强随机值，不要提交到仓库：

   ```powershell
   $env:INVITE_ADMIN_KEY = "替换为强随机管理密钥"
   $env:INVITE_PAGE_PASSWORD = "替换为私有页面密码"
   ```

4. 启动：

   ```powershell
   python server.py
   ```

5. 打开 `http://127.0.0.1:8790`，上传 PSD 模板和有授权的字体文件。

如果没有设置任一密钥，服务会拒绝启动。其他终端请设置对应环境变量后再运行。

## 模板与素材

真实模板和字体属于运行时用户数据，本仓库不包含这些文件。请通过本地页面上传；服务会将模板保存在 `assets/templates/`、字体保存在 `assets/fonts/`，PNG 输出到 `output/`，运行记录写入 `logs/`。

未经明确授权，不要发布真实邀请函设计、参会者姓名、导出图片、访问日志、API 密钥、密码或字体文件。`.gitignore` 已忽略常见运行数据；每次提交前仍需检查 `git status` 和暂存文件清单。

## 静态访客网站

`tools/build_site.py` 可把当前本地模板打包为静态网站。打包内容会包含邀请函背景图和字体，发布前须检查素材并确认图片、字体都有再分发授权。静态版在访客浏览器中渲染和导出，不支持服务端导出统计、模板管理或备份恢复。

## 渲染边界

程序读取 PSD 文字图层信息，将背景合成为平面图，再用 Canvas 重绘可编辑文字。支持基本位置、字体、字号、颜色、对齐、字距、填空和选项。任意 Photoshop 图层效果、蒙版、混合模式、智能对象、变形文字、逐字符混排以及通用 Photoshop Action 都不保证完全一致。复杂装饰可先扁平化为背景，再用样张逐个校准。

## 安全与隐私

- 名单文件仅在浏览器中解析，不会上传到服务器。
- 若共享部署，本地服务会保存导出的 PNG，并在日志中记录访客 IP、浏览器标识、模板名和文件名；对外开放前应规划日志访问权限与保留期限。
- 共享部署必须使用 HTTPS 和强随机 `INVITE_ADMIN_KEY`。
- 不要把真实凭据放入 `.env.example`、源码、截图、测试夹具或公开 issue。

## 许可证

本项目代码采用 MIT License。第三方库、字体、PSD、图片和模板仍受各自许可证约束；本项目许可证不授予这些素材的使用权。

---

<a id="english"></a>
## English

A local-first invitation image personalizer. Upload a PSD template, map editable text fields, preview changes in the browser, and export PNG images. The browser renders text with Canvas; the local Python service stores templates and exported files.

This project is a multi-field personalization tool. It is not a general-purpose Photoshop Action runner or a pixel-identical PSD renderer.

## Features

- PSD text-layer inspection and editable-field suggestions
- Browser Canvas preview with uploaded fonts
- Text, fill-in, and mutually exclusive choice fields
- Per-version underline toggle for fill-in fields
- CSV, TSV, and XLSX list import with column mapping and preview
- Export preflight checks, batch version gallery, and PNG export
- Mobile preview, form, list, and version views
- Local template backup and restore
- Optional static-site packaging for read-only visitor use

## Requirements

- Python 3.10 or newer
- Node-free runtime; the XLSX browser library is vendored under `vendor/` with its Apache-2.0 license
- Dependencies listed in `requirements.txt`
- A PSD template and fonts that you are permitted to use and redistribute within your deployment

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Set secrets in the current shell. Use your own strong values; never commit them:

   ```powershell
   $env:INVITE_ADMIN_KEY = "your-long-random-admin-key"
   $env:INVITE_PAGE_PASSWORD = "your-private-page-password"
   ```

4. Start the local service:

   ```powershell
   python server.py
   ```

5. Open `http://127.0.0.1:8790` and upload a PSD template and a licensed font file.

The server refuses to start if either secret is unset. For other shells, set the equivalent environment variables before launching Python.

## Templates and Assets

Templates and fonts are runtime user data and are intentionally not included in this repository. Upload them through the local UI. The service stores them under `assets/templates/` and `assets/fonts/`; generated PNG files go to `output/`, and event logs go to `logs/`.

Do not publish real invitation designs, attendee names, exports, visitor logs, API keys, passwords, or fonts without explicit redistribution rights. `.gitignore` excludes the usual local-data directories, but review `git status` and the staged file list before every commit.

## Static Visitor Site

`tools/build_site.py` packages the current local templates for static hosting. The generated package contains invitation artwork and fonts, so treat it as publishable user content: inspect the templates and confirm all image/font rights before hosting. Static mode renders and exports in the visitor's browser and does not provide server-side export statistics, template administration, or backup/restore.

## Rendering Limits

The PSD parser extracts text-layer metadata and builds a flattened background with editable text redrawn by Canvas. Basic position, font, size, color, alignment, spacing, fill fields, and choices are supported. Arbitrary Photoshop layer effects, masks, blend modes, smart objects, warped text, mixed per-character formatting, and general Photoshop Actions are not guaranteed to render identically. Flatten complex decorative artwork before using it as a template background, then verify each template with sample exports.

## Security and Privacy

- List files are parsed in the browser; the application does not upload list contents to the server.
- The local server writes generated PNG files and logs visitor IP, user-agent, template, and filenames when used in a shared deployment. Review retention and access controls before exposing the service publicly.
- Use HTTPS and a strong random `INVITE_ADMIN_KEY` for any shared deployment.
- Never put real credentials in `.env.example`, source files, screenshots, fixtures, or public issue reports.

## License

The project source is offered under the MIT License. Third-party libraries, fonts, PSDs, images, and templates retain their own licenses; this repository license does not grant rights to those assets.
