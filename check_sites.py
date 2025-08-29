import os
import difflib
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Bot
from playwright.sync_api import sync_playwright
import requests
from PIL import Image, ImageDraw, ImageFont
import logging
from bs4 import BeautifulSoup
import html
from urllib.parse import urlparse  # 添加导入用于解析URL

# === 配置 ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ADMIN_USER_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))  # Telegram 用户 ID
DATA_DIR = Path("data")
LOG_FILE = Path("changes.log")
FONT_FILE = "aliph.ttf"  # 直接使用当前目录下的字体文件

DATA_DIR.mkdir(exist_ok=True)
LOG_FILE.touch(exist_ok=True)

bot = Bot(token=BOT_TOKEN)


# === 工具函数 ===
def get_cst_time():
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S CST")


def normalize_text(text):
    return text.replace("\r\n", "\n").strip()


def get_page_content(url, dynamic=False):
    try:
        # 解析URL获取域名
        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        # 检查域名是否包含"m."，如果是则使用移动版User-Agent
        is_mobile_domain = "m." in domain

        if dynamic:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
                        if is_mobile_domain
                        else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                page.goto(url, timeout=30000, wait_until="networkidle")
                content = page.content()
                browser.close()
                return normalize_text(content)
        else:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
                    if is_mobile_domain
                    else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                )
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = "utf-8"
            return normalize_text(resp.text)
    except Exception as e:
        return f"ERROR: {e}"


def safe_filename(url):
    return url.replace("://", "_").replace("/", "_").replace("?", "_").replace("&", "_")


def format_html_content(html_content):
    """格式化HTML内容，提高diff可读性"""
    try:
        # 使用BeautifulSoup解析并格式化HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # 压缩和美化HTML
        for element in soup.find_all(True):
            # 压缩连续的空白字符
            if element.string:
                element.string = " ".join(element.string.split())

        # 格式化HTML（设置缩进）
        formatted_html = soup.prettify(formatter="html")

        # 处理特殊字符
        formatted_html = html.unescape(formatted_html)

        # 移除多余空行（保留最多连续2个空行）
        lines = []
        empty_count = 0
        for line in formatted_html.splitlines():
            if line.strip() == "":
                empty_count += 1
                if empty_count <= 2:
                    lines.append(line)
            else:
                empty_count = 0
                lines.append(line)

        return normalize_text("\n".join(lines))
    except Exception as e:
        logging.error(f"HTML格式化失败: {e}")
        return html_content  # 失败时返回原始内容


def wrap_line(line, font, max_width):
    """将长行拆分为多行以适应最大宽度"""
    words = []
    current_word = ""

    # 按单词拆分（保留空格）
    for char in line:
        if char.isspace():
            if current_word:
                words.append(current_word)
                current_word = ""
            words.append(char)
        else:
            current_word += char

    if current_word:
        words.append(current_word)

    # 构建行列表
    wrapped_lines = []
    current_line = ""

    for word in words:
        # 测量添加单词后的宽度
        test_line = current_line + word
        bbox = (
            font.getbbox(test_line)
            if hasattr(font, "getbbox")
            else font.getsize(test_line)
        )
        test_width = bbox[2] - bbox[0] if hasattr(font, "getbbox") else bbox[0]

        # 如果当前行不为空且添加单词后超宽，则换行
        if current_line and test_width > max_width:
            wrapped_lines.append(current_line.rstrip())
            current_line = word
        else:
            current_line = test_line

    if current_line:
        wrapped_lines.append(current_line.rstrip())

    return wrapped_lines


def diff_to_image(
    diff_text, output_file, min_width=400, max_width=1200, line_height_pad=8
):
    # 创建新的行列表，用于处理换行
    processed_lines = []

    # 设置左右边距
    left_margin = 10
    right_margin = 10
    max_content_width = max_width - left_margin - right_margin

    # 直接使用当前目录下的字体文件
    font_path = Path(FONT_FILE)
    font_size = 16

    # 尝试加载字体
    font = None
    if font_path.exists():
        try:
            font = ImageFont.truetype(str(font_path), font_size)
            logging.info(f"使用字体: {font_path}")
        except Exception as e:
            logging.warning(f"字体加载失败 {font_path}: {e}")
            font = None

    # 如果加载失败，使用默认字体
    if font is None:
        try:
            # 尝试使用常见的系统字体作为回退
            fallback_fonts = ["Arial.ttf", "arial.ttf", "DejaVuSans.ttf"]
            for font_name in fallback_fonts:
                try:
                    font = ImageFont.truetype(font_name, font_size)
                    logging.info(f"使用回退字体: {font_name}")
                    break
                except:
                    continue
        except:
            pass

        # 如果所有回退都失败，使用PIL默认字体
        if font is None:
            font = ImageFont.load_default()
            logging.warning("使用PIL默认字体")

    # 计算行高
    bbox = font.getbbox("A") if hasattr(font, "getbbox") else font.getsize("A")
    line_height = (
        bbox[3] - bbox[1] if hasattr(font, "getbbox") else bbox[1]
    ) + line_height_pad

    # 处理每一行，进行换行
    for line in diff_text.splitlines():
        # 测量行宽度
        bbox = font.getbbox(line) if hasattr(font, "getbbox") else font.getsize(line)
        line_width = bbox[2] - bbox[0] if hasattr(font, "getbbox") else bbox[0]

        # 如果行太长，则换行处理
        if line_width > max_content_width:
            wrapped_lines = wrap_line(line, font, max_content_width)
            processed_lines.extend(wrapped_lines)
        else:
            processed_lines.append(line)

    # 计算图片高度和宽度
    height = min((line_height * len(processed_lines)) + 20, 2000)

    # 重新计算最大行宽度（考虑换行后）
    max_line_width = 0
    for line in processed_lines:
        bbox = font.getbbox(line) if hasattr(font, "getbbox") else font.getsize(line)
        width = bbox[2] - bbox[0] if hasattr(font, "getbbox") else bbox[0]
        if width > max_line_width:
            max_line_width = width

    # 动态宽度（考虑边距）
    width = min(max(max_line_width + left_margin + right_margin, min_width), max_width)

    # 创建图片
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # 绘制文本
    y = 10
    for line in processed_lines:
        # 确定行颜色
        if line.startswith("+"):
            fill = (0, 128, 0)
        elif line.startswith("-"):
            fill = (255, 0, 0)
        elif line.startswith("@"):
            fill = (0, 0, 255)
        else:
            fill = (0, 0, 0)

        draw.text((left_margin, y), line, font=font, fill=fill)
        y += line_height

    img.save(output_file)


# === 核心逻辑 ===
def compare_and_notify(url, dynamic=False, is_text=False):
    content = get_page_content(url, dynamic)
    timestamp = get_cst_time()
    snapshot_file = DATA_DIR / f"{safe_filename(url)}.txt"
    diff_image_file = DATA_DIR / f"{safe_filename(url)}_diff.png"

    # 网站访问失败 → 发送给管理员
    if content.startswith("ERROR:"):
        message = f"⚠️ 无法访问: {url}\n时间: {timestamp}\n错误信息: {content}"
        bot.send_message(chat_id=ADMIN_USER_ID, text=message)
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(f"[{timestamp}] {url} 访问失败: {content}\n")
        return

    # 格式化HTML内容（非纯文本时）
    if not is_text:
        content = format_html_content(content)

    first_run = not snapshot_file.exists()
    if first_run:
        snapshot_file.write_text(content, encoding="utf-8")
        message = f"📥📥 首次抓取内容: {url}\n时间: {timestamp}"
        bot.send_message(chat_id=ADMIN_USER_ID, text=message)
        logging.info(f"首次抓取: {url}")
    else:
        try:
            old_content = snapshot_file.read_text(encoding="utf-8", errors="ignore")
            # 格式化旧内容以保持一致性
            if not is_text:
                old_content = format_html_content(old_content)

            old_content = normalize_text(old_content)

            if old_content != content:
                # 生成更精确的diff
                diff_lines = list(
                    difflib.unified_diff(
                        old_content.splitlines(keepends=False),
                        content.splitlines(keepends=False),
                        n=3,  # 增加上下文行数
                    )
                )
                diff_text = "\n".join(diff_lines)

                # 生成diff图片
                diff_to_image(diff_text, diff_image_file)

                # 发送更新通知
                caption = f"🔍🔍 内容更新: {url}\n时间: {timestamp}"
                bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=open(diff_image_file, "rb"),
                    caption=caption,
                )
                logging.info(f"检测到更新: {url}")
            else:
                logging.info(f"内容未变化: {url}")
        except Exception as e:
            logging.error(f"比较内容时出错: {e}")
            message = f"⚠️ 内容比较失败: {url}\n错误信息: {e}"
            bot.send_message(chat_id=ADMIN_USER_ID, text=message)

    # 写日志
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"[{timestamp}] {url} 已抓取/更新\n")

    # 更新快照
    snapshot_file.write_text(content, encoding="utf-8")


def main():
    if not BOT_TOKEN or not CHANNEL_ID or not ADMIN_USER_ID:
        raise ValueError(
            "请设置 TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID 和 TELEGRAM_ADMIN_ID 环境变量"
        )

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("monitor.log"), logging.StreamHandler()],
    )

    # 字体检测
    font_path = Path(FONT_FILE)
    if font_path.exists():
        logging.info(f"使用字体: {font_path}")
    else:
        logging.warning(f"字体文件 {font_path} 不存在")
        bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"⚠️ 字体文件 {font_path} 不存在，将尝试使用回退字体",
        )

    # 读取监测站点列表
    urls = []
    try:
        with open("sites.txt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                type_, url = line.split("|", 1)
                urls.append((type_.strip(), url.strip()))
        logging.info(f"成功读取 {len(urls)} 个监测站点")
    except Exception as e:
        logging.error(f"读取sites.txt失败: {e}")
        bot.send_message(chat_id=ADMIN_USER_ID, text=f"⚠️ 读取监测站点列表失败: {e}")
        return

    # 处理每个站点
    for type_, url in urls:
        dynamic = type_ == "dynamic"
        is_text = type_ == "txt"
        try:
            logging.info(f"开始处理: {url} (类型: {type_})")
            compare_and_notify(url, dynamic=dynamic, is_text=is_text)
        except Exception as e:
            logging.error(f"处理站点 {url} 时出错: {e}")
            message = f"⚠️ 处理站点失败: {url}\n错误信息: {e}"
            bot.send_message(chat_id=ADMIN_USER_ID, text=message)


if __name__ == "__main__":
    main()
