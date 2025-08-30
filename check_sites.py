import os
import difflib
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Bot
from telegram.request import HTTPXRequest
from playwright.async_api import async_playwright
import requests
from PIL import Image, ImageDraw, ImageFont, ImageColor
import logging
from bs4 import BeautifulSoup
import html
from urllib.parse import urlparse
from pygments import highlight
from pygments.lexers import get_lexer_for_filename, guess_lexer, TextLexer
from pygments.formatters import ImageFormatter
from pygments.style import Style
from pygments.token import Token
import tempfile
import re
import cssbeautifier

# === 配置 ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ADMIN_USER_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))  # Telegram 用户 ID
DATA_DIR = Path("data")
LOG_FILE = Path("changes.log")
FONT_FILE = "aliph.ttf"  # 直接使用当前目录下的字体文件

DATA_DIR.mkdir(exist_ok=True)
LOG_FILE.touch(exist_ok=True)

# 创建自定义请求对象，增加连接池大小和超时时间
request = HTTPXRequest(
    connection_pool_size=20,  # 增加连接池大小
    read_timeout=30,  # 增加读取超时时间
    write_timeout=30,  # 增加写入超时时间
    connect_timeout=30,  # 增加连接超时时间
)

bot = Bot(token=BOT_TOKEN, request=request)


# === 自定义VSCode风格 ===
class VSCodeStyle(Style):
    """
    仿VSCode风格的语法高亮样式
    """

    styles = {
        Token: "#D4D4D4",  # 默认文本颜色
        Token.Comment: "#6A9955",  # 注释 - 绿色
        Token.Keyword: "#C586C0",  # 关键字 - 紫色
        Token.String: "#CE9178",  # 字符串 - 棕色
        Token.Name: "#D4D4D4",  # 变量名 - 白色
        Token.Name.Function: "#DCDCAA",  # 函数名 - 米黄色
        Token.Name.Class: "#4EC9B0",  # 类名 - 青蓝色
        Token.Number: "#B5CEA8",  # 数字 - 浅绿色
        Token.Operator: "#D4D4D4",  # 操作符 - 白色
        Token.Punctuation: "#D4D4D4",  # 标点 - 白色
    }


# === 工具函数 ===
def get_cst_time():
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S CST")


def normalize_text(text):
    return text.replace("\r\n", "\n").strip()


async def get_page_content(url, dynamic=False):
    try:
        # 解析URL获取域名
        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        # 检查域名是否包含"m."，如果是则使用移动版User-Agent
        is_mobile_domain = "m." in domain

        if dynamic:
            # 使用异步Playwright API
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
                        if is_mobile_domain
                        else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(url, timeout=30000, wait_until="networkidle")
                content = await page.content()
                await browser.close()
                return normalize_text(content)
        else:
            # 对于非动态内容，仍然使用requests（同步）
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
                    if is_mobile_domain
                    else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                )
            }
            # 在异步函数中运行同步代码
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, headers=headers, timeout=15)
            )
            resp.encoding = "utf-8"
            return normalize_text(resp.text)
    except Exception as e:
        return f"ERROR: {e}"


def safe_filename(url):
    return url.replace("://", "_").replace("/", "_").replace("?", "_").replace("&", "_")


def format_css_content(css_content):
    """格式化CSS内容"""
    try:
        # 使用cssbeautifier格式化CSS
        options = cssbeautifier.default_options()
        options.indent = "  "  # 使用两个空格缩进
        options.openbrace = "separate-line"  # 大括号单独一行
        return cssbeautifier.beautify(css_content, options)
    except Exception as e:
        logging.error(f"CSS格式化失败: {e}")
        return css_content  # 失败时返回原始内容


def format_html_content(html_content):
    """格式化HTML内容，提高diff可读性"""
    try:
        # 使用BeautifulSoup解析并格式化HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # 处理style标签中的CSS内容
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                try:
                    # 格式化CSS内容
                    formatted_css = format_css_content(style_tag.string)
                    style_tag.string = formatted_css
                except Exception as e:
                    logging.warning(f"格式化CSS内容失败: {e}")
                    # 如果格式化失败，保持原样

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


def highlight_code(code, filename="file.py"):
    """
    使用Pygments对代码进行语法高亮
    """
    try:
        # 尝试根据文件名猜测语言
        try:
            lexer = get_lexer_for_filename(filename)
        except:
            # 如果失败，尝试根据内容猜测语言
            try:
                lexer = guess_lexer(code)
            except:
                # 如果还是失败，使用纯文本lexer
                lexer = TextLexer()

        # 创建临时文件来保存高亮后的图像
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            # 使用自定义的VSCode样式
            formatter = ImageFormatter(
                style=VSCodeStyle,
                line_numbers=True,  # 显示行号
                font_name="DejaVu Sans Mono",  # 使用等宽字体
                font_size=14,
                line_number_bg="#2B2B2B",  # 行号背景色
                line_number_fg="#6E7681",  # 行号前景色
                image_format="png",
            )

            highlight(code, lexer, formatter, temp_file.name)
            return temp_file.name
    except Exception as e:
        logging.error(f"代码高亮失败: {e}")
        return None


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
    left_margin = 50  # 增加左边距以容纳行号
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
            fallback_fonts = ["DejaVuSansMono.ttf", "Consolas.ttf", "Courier New.ttf"]
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
    line_numbers = []
    line_number_width = 0
    line_count = 0

    for line in diff_text.splitlines():
        line_count += 1
        # 测量行宽度
        bbox = font.getbbox(line) if hasattr(font, "getbbox") else font.getsize(line)
        line_width = bbox[2] - bbox[0] if hasattr(font, "getbbox") else bbox[0]

        # 如果行太长，则换行处理
        if line_width > max_content_width:
            wrapped_lines = wrap_line(line, font, max_content_width)
            processed_lines.extend(wrapped_lines)
            line_numbers.extend([line_count] + [""] * (len(wrapped_lines) - 1))
        else:
            processed_lines.append(line)
            line_numbers.append(line_count)

    # 计算行号区域的宽度
    if line_numbers:
        max_line_num = max([num for num in line_numbers if num != ""])
        line_number_width = (
            font.getbbox(str(max_line_num))[2] - font.getbbox(str(max_line_num))[0]
            if hasattr(font, "getbbox")
            else font.getsize(str(max_line_num))[0]
        )
        line_number_width += 20  # 增加一些边距

    # 计算图片高度和宽度
    height = min((line_height * len(processed_lines)) + 20, 2000)

    # 重新计算最大行宽度（考虑换行后）
    max_line_width = 0
    for line in processed_lines:
        bbox = font.getbbox(line) if hasattr(font, "getbbox") else font.getsize(line)
        width = bbox[2] - bbox[0] if hasattr(font, "getbbox") else bbox[0]
        if width > max_line_width:
            max_line_width = width

    # 动态宽度（考虑边距和行号区域）
    width = min(
        max(max_line_width + left_margin + right_margin + line_number_width, min_width),
        max_width,
    )

    # 创建图片
    img = Image.new("RGB", (width, height), color="#1E1E1E")  # VSCode风格的深色背景
    draw = ImageDraw.Draw(img)

    # 绘制行号背景
    draw.rectangle([(0, 0), (left_margin, height)], fill="#2B2B2B")

    # 绘制行号
    for i, line_num in enumerate(line_numbers):
        if line_num != "":
            y_pos = 10 + i * line_height
            # 行号右对齐
            num_str = str(line_num)
            bbox = (
                font.getbbox(num_str)
                if hasattr(font, "getbbox")
                else font.getsize(num_str)
            )
            num_width = bbox[2] - bbox[0] if hasattr(font, "getbbox") else bbox[0]
            x_pos = left_margin - num_width - 10
            draw.text((x_pos, y_pos), num_str, font=font, fill="#6E7681")  # 行号颜色

    # 绘制文本
    y = 10
    for i, line in enumerate(processed_lines):
        # 确定行颜色
        if line.startswith("+"):
            fill = (155, 185, 85)  # 柔和的绿色
        elif line.startswith("-"):
            fill = (224, 108, 117)  # 柔和的红色
        elif line.startswith("@"):
            fill = (86, 156, 214)  # 蓝色
        else:
            fill = (212, 212, 212)  # 浅灰色

        # 移除diff标记以获取纯净的代码
        clean_line = line
        if line.startswith(("+", "-", "@", " ")):
            clean_line = line[1:] if len(line) > 1 else line

        draw.text((left_margin, y), clean_line, font=font, fill=fill)
        y += line_height

    img.save(output_file)


# === 异步消息发送管理器 ===
class TelegramMessageManager:
    def __init__(self, bot):
        self.bot = bot
        self.semaphore = asyncio.Semaphore(5)  # 限制并发数为5

    async def send_message(self, chat_id, text):
        async with self.semaphore:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
                await asyncio.sleep(0.5)  # 添加短暂延迟
            except Exception as e:
                logging.error(f"发送消息失败: {e}")
                raise

    async def send_photo(self, chat_id, photo_path, caption):
        async with self.semaphore:
            try:
                with open(photo_path, "rb") as photo:
                    await self.bot.send_photo(
                        chat_id=chat_id, photo=photo, caption=caption
                    )
                await asyncio.sleep(1)  # 图片发送后添加稍长的延迟
            except Exception as e:
                logging.error(f"发送图片失败: {e}")
                raise


# 创建消息管理器实例
message_manager = TelegramMessageManager(bot)


# === 核心逻辑 ===
async def compare_and_notify_async(url, dynamic=False, is_text=False):
    content = await get_page_content(url, dynamic)  # 使用await调用异步函数
    timestamp = get_cst_time()
    snapshot_file = DATA_DIR / f"{safe_filename(url)}.txt"
    diff_image_file = DATA_DIR / f"{safe_filename(url)}_diff.png"

    # 网站访问失败 → 发送给管理员
    if content.startswith("ERROR:"):
        message = f"⚠️ 无法访问: {url}\n时间: {timestamp}\n错误信息: {content}"
        await message_manager.send_message(ADMIN_USER_ID, message)
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
        await message_manager.send_message(CHANNEL_ID, message)
        logging.info(f"首次抓取: {url}")
    else:
        try:
            old_content = snapshot_file.read_text(encoding="utf-8", errors="ignore")
            # 格式化旧内容以保持一致性
            if not is_text:
                old_content = format_html_content(old_content)

            old_content = normalize_text(old_content)

            if old_content != content:
                # 尝试使用Pygments生成带语法高亮的差异图片
                try:
                    # 根据URL猜测文件类型
                    if "." in url:
                        file_ext = url.split(".")[-1]
                        if len(file_ext) > 5:  # 避免过长的扩展名
                            file_ext = "txt"
                    else:
                        file_ext = "txt"

                    # 生成高亮图片
                    highlighted_old = highlight_code(old_content, f"old.{file_ext}")
                    highlighted_new = highlight_code(content, f"new.{file_ext}")

                    if highlighted_old and highlighted_new:
                        # 如果高亮成功，使用高亮后的图片
                        # 这里可以添加代码将两个图片合并为对比图片
                        # 暂时使用原有的diff文本作为备选
                        pass
                except Exception as e:
                    logging.warning(f"代码高亮失败，使用文本diff: {e}")

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
                await message_manager.send_photo(CHANNEL_ID, diff_image_file, caption)
                logging.info(f"检测到更新: {url}")
            else:
                logging.info(f"内容未变化: {url}")
        except Exception as e:
            logging.error(f"比较内容时出错: {e}")
            message = f"⚠️ 内容比较失败: {url}\n错误信息: {e}"
            await message_manager.send_message(ADMIN_USER_ID, message)

    # 写日志
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"[{timestamp}] {url} 已抓取/更新\n")

    # 更新快照
    snapshot_file.write_text(content, encoding="utf-8")


async def main_async():
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
        await message_manager.send_message(
            ADMIN_USER_ID, f"⚠️ 字体文件 {font_path} 不存在，将尝试使用回退字体"
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
        await message_manager.send_message(
            ADMIN_USER_ID, f"⚠️ 读取监测站点列表失败: {e}"
        )
        return

    # 处理每个站点
    for type_, url in urls:
        dynamic = type_ == "dynamic"
        is_text = type_ == "txt"
        try:
            logging.info(f"开始处理: {url} (类型: {type_})")
            await compare_and_notify_async(url, dynamic=dynamic, is_text=is_text)
        except Exception as e:
            logging.error(f"处理站点 {url} 时出错: {e}")
            message = f"⚠️ 处理站点失败: {url}\n错误信息: {e}"
            await message_manager.send_message(ADMIN_USER_ID, message)


def main():
    # 运行主异步函数
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
