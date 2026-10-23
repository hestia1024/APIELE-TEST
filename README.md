# APIELE-TEST

一个用于验证开发流程的 MySQL 测试页：检查连接、添加测试记录、读取最近 50 条记录。

## 本地运行（Windows）

需要 Python 3.12+、Git 和 Windows 自带的 OpenSSH 客户端。前端随 FastAPI 一起提供，不需要 Node.js 或前端构建。

1. 克隆仓库并准备配置：

   ```powershell
   git clone https://github.com/hestia1024/APIELE-TEST.git
   cd APIELE-TEST
   Copy-Item .env.example .env
   notepad .env
   ```

   在 `.env` 中填写 `SSH_HOST`（服务器公网 IP）、`SSH_USER`、`SSH_PORT` 和 `DB_PASSWORD`（MySQL 的 apiele_dev 密码）。默认数据库为 `apiele_test_dev`，服务器数据库端口为 `3307`，本地隧道端口为 `13307`。密码含 `#` 等符号时保留双引号。

2. 在第一个终端启动隧道：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\start-tunnel.ps1
   ```

   按 SSH 提示输入服务器登录密码（不是 MySQL 密码），或使用已配置的 SSH 密钥；首次连接核对服务器指纹。保持这个终端打开。

3. 在第二个终端启动网站：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
   ```

   脚本首次运行会创建 `.venv` 并安装依赖，然后启动服务。

4. 打开 <http://127.0.0.1:8010>。确认“已连接”，输入测试内容并保存，刷新后仍能看到同一条记录。在 Navicat 中也可查看 `apiele_test_dev.apiele_test_notes`。

修改 `.env` 后重启网站；隧道配置变化时也需要重启隧道。用 Ctrl+C 停止对应终端。

## 页面与接口

- `GET /`：测试页面。
- `GET /api/health`：网站是否运行（不代表数据库连接成功）。
- `GET /api/database`：实际查询 MySQL，返回版本与数据库名称。
- `GET /api/bootstrap`：一次请求读取连接状态和最近记录，用于页面初始化。
- `GET /api/notes`：读取最近 50 条测试记录，首次操作自动创建测试表。
- `POST /api/notes`：提交 `{"content":"测试内容"}`，写入并返回刚刚保存的记录。

仅使用 `apiele_test_notes` 测试表，不包含删除接口。数据库账号需具备该开发库的 CREATE、SELECT、INSERT 权限。页面时间采用数据库连接的时区，未自动换算为北京时间。

后端复用空闲连接，借出前检查连接有效性；同一个连接不会同时交给两个请求。测试表每次启动仅在首次读写时检查创建，写入失败不会自动重试。保存成功后直接显示数据库返回的记录；点击“刷新记录”可获取其他人的最新数据。

## 常见报错

| 现象 | 处理 |
|---|---|
| 未填写密码/配置错误 | 修改 `.env`，重启网站 |
| 连接不到数据库 | 先启动 SSH 隧道，检查本地端口 13307 与服务器端口 3307 |
| SSH 提示 Permission denied | 检查 SSH 登录账号、密码或私钥 |
| 数据库账号密码不正确 | 检查 DB_USER、DB_PASSWORD，重启网站 |
| 数据库不存在/权限不足 | 在 Navicat 检查数据库名及账号权限 |

页面报错附异常编号，可在 `logs/app.log` 按编号查找错误类型和 MySQL 错误码；不记录密码和测试记录正文。

## 同事运行与提交

同事克隆仓库后，按照相同流程配置自己的 `.env` 和 SSH 隧道。双方连接同一个开发库，可以看到对方写入的测试记录。

`.env`、日志和 `.venv` 已被 Git 忽略；不要提交真实密码、私钥或业务数据。本地启动脚本仅绑定本机地址。

## 部署到服务器

服务器需要已启动 Docker 和 MySQL（服务器本机端口 3307）。本地 `.env` 中填写服务器 SSH 信息和数据库密码后，在本机项目目录执行：

```powershell
python deploy.py
```

按提示输入服务器登录密码。脚本通过一条 SSH 连接上传代码及数据库配置，随后构建、启动 Docker 容器并检查数据库连接。不需要先推送到 GitHub，也不需要复制粘贴数据库密码到服务器命令中。

- 网站地址：`http://服务器公网IP:8010/`，按当前测试要求不设访问密码。
- 云平台安全组需允许 TCP 8010 入站；MySQL 的 3307 端口继续仅监听服务器本机。
- 项目目录：`/opt/apiele-test`，容器：`apiele-test-web`，日志目录：`/opt/apiele-test/logs`。
- 查看启动日志：`docker logs --tail 60 apiele-test-web`。
- 停止网站：`docker stop apiele-test-web`；重新启动：`docker start apiele-test-web`。
- 更新：修改本地代码后再次执行 `python deploy.py`。会短暂重启网站；不删除 MySQL 容器或数据库数据卷。

部署使用 Linux host 网络，因此后端直接访问同机 `127.0.0.1:3307`，不再经过本地 SSH 数据库隧道。关闭电脑和本地隧道不会停止服务器上的网站。
