# 运行与排错

本机配置在 `.env`，示例在 `.env.example`。部署读取 `SSH_PASSWORD`，数据库连接读取 `DB_PASSWORD`；请勿把密码发到聊天或写入操作记录。

## 本地运行

1. `powershell -NoProfile -ExecutionPolicy Bypass -File .\start-tunnel.ps1`，按提示登录并保持窗口开启。当前隧道脚本仍为交互式登录。
2. `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1`。
3. 打开 `http://127.0.0.1:8010/`；启动脚本首次会安装依赖。

本机的既有 Python 环境曾可运行项目，项目 `.venv` 的依赖下载曾失败；新电脑按 README 安装，不复用别人的绝对路径。安装失败遵守两次上限。无需为了读取 SSH 密码安装 Paramiko；该方案因依赖下载失败已经放弃。

## 发布和服务器

正常使用 `workflow.py release`，先推 GitHub，再按同一提交打包部署。低层 `deploy.py` 保留供已授权的部署恢复使用，不是绕过发布规则的日常入口。

服务器目录 `/opt/apiele-test`，网站容器 `apiele-test-web`，数据库容器 `apiele-mysql`。服务器应用日志在 `/opt/apiele-test/logs/app.log`；浏览器报错中的异常编号可用来检索。部署不会删除 MySQL 数据卷。

```sh
docker logs --tail 60 apiele-test-web
grep '异常编号' /opt/apiele-test/logs/app.log
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' apiele-test-web
cat /opt/apiele-test/.release-revision
```

容器版本 label 是实际运行版本；目录中的 `.release-revision` 是最近上传版本，若部署中途失败两者可能不同。只有服务器输出 `DEPLOYMENT_OK`（网站和数据库检查均通过）且部署进程退出 0 才可报告成功。建立流程前的旧容器还没有版本 label，需首次正式发布后才具备。

服务器发布成功后网页通过 `http://服务器公网IP:8010/` 访问，安全组须放行 8010。当前未设置页面访问密码，遵从用户明确要求。关本机电脑/隧道不会停服务器网站。

## 当前已知阻碍

此前一次 GitHub push 提示缺少凭据，Git Credential Manager 登录也未成功完成，已达到该问题的两次尝试上限。本次不重复尝试认证。用户需先在本机 Git 客户端完成 GitHub 登录，并确认具有 `hestia1024/APIELE-TEST` 写权限，再明确要求推送或发布。流程会在推送失败处停下，不再走旧的“仓库没推成功也继续部署”路径。

获取公开仓库更新不需要写权限；本次 `fetch` 已成功，未发现远端新增提交。未来以每次实际检查为准。
