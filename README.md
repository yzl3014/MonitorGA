# MonitorGA

一个基于 Python 的自动化网站变更监测工具，当监测的网站内容发生变化时，通过 Telegram 发送差异对比通知。

## 部署到 GitHub Actions

### 1. Fork 仓库

首先 Fork 这个仓库到你的 GitHub 账户。

### 2. 设置 Telegram Bot

在 Telegram 中与 [@BotFather](https://t.me/BotFather) 对话，创建一个新的机器人

获取机器人的 API Token

找到你的 Telegram 用户 ID（可以使用 [@userinfobot](https://t.me/userinfobot)）

创建一个 Telegram 频道，并将你的机器人添加为管理员

### 3. 配置 GitHub Secrets

首先创建一个 PAT (Personal Access Token), 范围勾选`repo`, 这个 Token 将在每次监测完毕后 Actions 向你的仓库提交网页变动日志时使用

在 Fork 的仓库中，进入 Settings → Secrets → Actions → Repository secrets，添加以下 secrets：

- `TELEGRAM_BOT_TOKEN`: 你的 Telegram 机器人 Token

- `TELEGRAM_CHANNEL_ID`: 你的 Telegram 频道 ID（以 `-100` 开头）

- `TELEGRAM_ADMIN_ID`: 你的 Telegram 用户 ID

- `PAT_TOKEN`: 刚刚创建的 PAT

### 4. 配置监测网站列表

在仓库根目录创建 `sites.txt` 文件，格式如下：

```text
dynamic|https://example.com
txt|https://example.com/text-page
```

`dynamic`: 使用 Playwright 渲染 JavaScript 动态内容

`txt`: 纯文本内容（不进行 HTML 格式化）

### 5. 配置运行计划

编辑 `.github/workflows/check.yml` 文件，修改 `schedule` 部分来设置运行频率：

```yaml
on:
  schedule:
    - cron: "0 0/2 * * *"  # 每2小时触发一次
  workflow_dispatch:
```

使用 [cron 语法](https://crontab.guru/) 来设置你想要的运行频率。

## 工作原理

1. 程序读取 sites.txt 中的网站列表
2. 获取网站当前内容并与之前保存的快照比较
3. 如果发现变化，生成差异对比图片
4. 通过 Telegram 机器人发送通知到指定频道
5. 提交快照文件以备下次比较

## 许可证

[MIT License](./LICENSE)