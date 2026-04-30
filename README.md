# cross-etf-scout

收盘后跨境 ETF 观察池工具。

项目从 `cross_etf.csv` 导入跨境 ETF 池，把每日行情快照存入 SQLite，
然后生成第二天需要观察的可选池、危险池和特别关注摘要。它不是分钟级监控，
也不做自动交易。

## 功能

- 用 `xueqiu-cli` 采集雪球行情。
- 行情和信号存入 SQLite，不使用 CSV 保存历史数据。
- 采集过程幂等，已采集的日期和代码不会重复拉取。
- 支持批量查询、重试、超时后重启无头浏览器容器。
- 生成完整本地报告和精简 Telegram 日报。
- 支持企业微信简短通知和 Telegram HTML 日报。
- 支持手动配置特别关注 ETF。

## 依赖

- Python 3.10+
- `sqlite3` 命令行工具
- [`xueqiu-cli`](https://github.com/kowloonzh/xueqiu-cli/blob/main/README_zh.md)
- Chrome/Chromium remote debugging endpoint

`xueqiu-cli` 的安装和使用见它的中文文档：

```text
https://github.com/kowloonzh/xueqiu-cli/blob/main/README_zh.md
```

服务器无 Chrome 桌面环境时，可以按 `xueqiu-cli` 文档启动无头浏览器：

```bash
docker run -d -p 9222:9222 --rm --name headless-shell chromedp/headless-shell
curl http://127.0.0.1:9222/json/version
```

确认 `xueqiu-cli` 可用：

```bash
xueqiu-cli --chrome-remote-url=http://127.0.0.1:9222 stock SH513310
xueqiu-cli --chrome-remote-url=http://127.0.0.1:9222 stocks SH513310,SH000001
```

## 安装

```bash
python3 -m pip install -e ".[dev]"
```

## 配置

本地真实配置文件不会提交到 git。先从模板复制：

```bash
mkdir -p config
cp config/config.example.yaml config/config.yaml
```

编辑 `config/config.yaml`：

```yaml
notifications:
  workwechat:
    enabled: false
    env_file: ".env"
    corp_id_env: "WORKWECHAT_CORP_ID"
    corp_secret_env: "WORKWECHAT_CORP_SECRET"
    agent_id_env: "WORKWECHAT_AGENT_ID"
    user_ids: []
    department_ids: []
    tag_ids: []
  telegram:
    enabled: false
    source: env
    env_file: ".env"
    bot_token_env: "TELEGRAM_BOT_TOKEN"
    chat_id_env: "TELEGRAM_CHAT_ID"
    parse_mode: "HTML"

focus_etfs:
  - "513310"
```

通知密钥可以放在配置指定的 `.env` 文件里：

```env
WORKWECHAT_CORP_ID=your-corp-id
WORKWECHAT_CORP_SECRET=your-app-secret
WORKWECHAT_AGENT_ID=your-agent-id
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
```

企业微信接收人是可选配置：

- `user_ids`: 企业微信用户 ID 列表
- `department_ids`: 部门 ID 列表
- `tag_ids`: 标签 ID 列表

如果三者都为空，企业微信会发送给 `@all`。如果只想发到部门 3：

```yaml
department_ids: ["3"]
```

## 首次使用

```bash
ces init-db
ces import-etfs
```

默认数据库路径：

```text
data/cross_etf_scout.sqlite
```

ETF 池来自：

```text
cross_etf.csv
```

## 采集行情

采集当天数据：

```bash
ces collect
```

指定日期：

```bash
ces collect --date YYYY-MM-DD
```

指定 Chrome remote endpoint：

```bash
ces collect --chrome-remote-url http://127.0.0.1:9222
```

调整批量大小、超时和重试：

```bash
ces collect --batch-size 10 --request-timeout 30 --retries 2 --retry-delay 1
```

采集默认幂等：如果某个日期和代码已经有行情，就跳过。需要强制刷新时：

```bash
ces collect --force
```

如果批量查询多次超时，程序会重启默认容器 `headless-shell` 后再试。禁用重启：

```bash
ces collect --no-restart-on-timeout
```

## 查看报告

完整本地报告：

```bash
ces report --date YYYY-MM-DD
```

生成并保存观察信号：

```bash
ces candidates --date YYYY-MM-DD
```

生成 Telegram HTML 日报：

```bash
ces telegram-digest --date YYYY-MM-DD
```

查看单个 ETF：

```bash
ces show SH513310
```

Telegram 日报只展示：

- 特别关注
- 可选池
- 危险池

完整报告仍保存到 `logs/report-YYYY-MM-DD.md`。

## 通知

手动发送企业微信：

```bash
PYTHONPATH=src python3 -m cross_etf_scout.notifications \
  --channel workwechat \
  --message "test"
```

手动发送 Telegram 日报：

```bash
PYTHONPATH=src python3 -m cross_etf_scout.notifications \
  --channel telegram \
  --file logs/telegram-YYYY-MM-DD.md
```

## 每日定时任务

每日脚本会循环采集，直到目标日期的行情数量等于 active ETF 数量。
它同样是幂等的，已采集完成的数据不会重复采集。

脚本当前默认项目路径是：

```text
/root/python/cross-etf-scout
```

如果项目放在其它目录，先修改 `scripts/collect_until_complete.sh` 里的 `ROOT_DIR`。

手动运行：

```bash
scripts/collect_until_complete.sh YYYY-MM-DD
```

安装每天 15:00 Asia/Shanghai 执行的 cron：

```cron
0 15 * * * TZ=Asia/Shanghai /root/python/cross-etf-scout/scripts/collect_until_complete.sh
```

脚本环境变量：

```bash
CES_COLLECT_MAX_ATTEMPTS=24
CES_COLLECT_SLEEP_SECONDS=300
CES_COLLECT_BATCH_SIZE=5
CES_COLLECT_REQUEST_TIMEOUT=30
CES_COLLECT_RETRIES=2
CES_COLLECT_RETRY_DELAY=1
```

## 开发

```bash
pytest -v
```
