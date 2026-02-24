#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表情包添加文字插件
功能：引用表情图片，添加自定义文字生成新表情包
支持：jpg/png/gif 格式，自定义颜色、大小、位置、描边
"""

import os
import io
import re
import aiohttp
from PIL import Image, ImageDraw, ImageFont
from typing import Optional, Tuple, List, Dict

from astrbot.api import logger
from astrbot.api.star import Star, Context, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image as ImageComponent

# 尝试导入 aiocqhttp 事件类型
try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
except ImportError:
    AiocqhttpMessageEvent = None

# 插件目录
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(PLUGIN_DIR, "fonts")

# 颜色映射
COLOR_MAP = {
    "白色": "#FFFFFF",
    "黑色": "#000000",
    "红色": "#FF0000",
    "黄色": "#FFFF00",
    "蓝色": "#0000FF",
    "绿色": "#00FF00",
    "粉色": "#FF69B4",
    "紫色": "#9400D3",
}

# 位置映射 (x, y 百分比)
POSITION_MAP = {
    "上左": (0.15, 0.15),
    "上中": (0.50, 0.15),
    "上右": (0.85, 0.15),
    "中左": (0.15, 0.50),
    "中": (0.50, 0.50),
    "中右": (0.85, 0.50),
    "下左": (0.15, 0.85),
    "下中": (0.50, 0.85),
    "下右": (0.85, 0.85),
}

# 位置别名（兼容旧写法与常见输入）
POSITION_ALIAS_MAP = {
    "上": "上中",
    "下": "下中",
    "左上": "上左",
    "中上": "上中",
    "右上": "上右",
    "左中": "中左",
    "右中": "中右",
    "左下": "下左",
    "中下": "下中",
    "右下": "下右",
}

# 字体大小映射 (相对图片宽度的百分比)
SIZE_MAP = {
    "小字体": 0.05,
    "中字体": 0.08,
    "大字体": 0.12,
}

# 描边颜色映射
STROKE_MAP = {
    "白色描边": "#FFFFFF",
    "黑色描边": "#000000",
}


@register("meme_text", "haoyuedashi", "表情包添加文字插件", "1.0.0")
class MemeTextPlugin(Star):
    """表情包添加文字插件"""

    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.config = config or {}
        
        # 配置项
        self.command_prefix = self.config.get("command_prefix", "表情加字")
        self.default_color = self.config.get("default_color", "白色")
        self.default_size = self.config.get("default_size", "中字体")
        self.default_position = self._normalize_position(self.config.get("default_position", "下"))
        self.auto_stroke = self.config.get("auto_stroke", True)
        self.stroke_width = self.config.get("stroke_width", 2)
        self.max_text_length = self.config.get("max_text_length", 50)
        self.cleanup_days = self.config.get("cleanup_days", 2)  # 清理超过N天的文件
        
        # 字体路径
        self.font_path = self._find_font()
        
        # 临时文件目录
        self.temp_dir = os.path.join(PLUGIN_DIR, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # 启动定期清理任务
        import asyncio
        asyncio.create_task(self._cleanup_loop())
        
        # 立即执行一次清理
        self._cleanup_old_files()
        
        logger.info(f"[表情文字] 插件已加载，命令: {self.command_prefix}，自动清理: {self.cleanup_days}天")

    def _cleanup_old_files(self):
        """清理超过指定天数的临时文件"""
        import time
        try:
            if not os.path.exists(self.temp_dir):
                return
            
            now = time.time()
            max_age = self.cleanup_days * 24 * 60 * 60  # 转换为秒
            cleaned_count = 0
            
            for filename in os.listdir(self.temp_dir):
                filepath = os.path.join(self.temp_dir, filename)
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > max_age:
                        try:
                            os.remove(filepath)
                            cleaned_count += 1
                        except Exception as e:
                            logger.warning(f"[表情文字] 删除文件失败: {filepath}, {e}")
            
            if cleaned_count > 0:
                logger.info(f"[表情文字] 清理了 {cleaned_count} 个过期临时文件")
        except Exception as e:
            logger.error(f"[表情文字] 清理临时文件失败: {e}")

    async def _cleanup_loop(self):
        """定期清理循环（每天检查一次）"""
        import asyncio
        while True:
            # 每24小时执行一次清理
            await asyncio.sleep(24 * 60 * 60)
            self._cleanup_old_files()

    def _find_font(self) -> str:
        """查找可用的中文字体"""
        # 优先使用插件目录下的字体
        local_fonts = [
            os.path.join(FONTS_DIR, "Alibaba-PuHuiTi-Bold.ttf"),      # 阿里巴巴普惠体粗体
            os.path.join(FONTS_DIR, "Alibaba-PuHuiTi-Medium.ttf"),    # 阿里巴巴普惠体中等
            os.path.join(FONTS_DIR, "SOURCEHANSANSCN-BOLD.OTF"),      # 思源黑体粗体
            os.path.join(FONTS_DIR, "SOURCEHANSANSCN-MEDIUM.OTF"),    # 思源黑体中等
            os.path.join(FONTS_DIR, "msyh.ttc"),                       # 微软雅黑
            os.path.join(FONTS_DIR, "simhei.ttf"),                     # 黑体
        ]
        for font in local_fonts:
            if os.path.exists(font):
                logger.info(f"[表情文字] 使用本地字体: {font}")
                return font
        
        # 使用系统字体
        system_fonts = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
            "C:/Windows/Fonts/simsun.ttc",    # 宋体
            "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",  # Linux
            "/System/Library/Fonts/PingFang.ttc",  # macOS
        ]
        for font in system_fonts:
            if os.path.exists(font):
                return font
        
        logger.warning("[表情文字] 未找到中文字体，将使用默认字体")
        return ""

    def _normalize_position(self, position: str) -> str:
        """标准化位置参数，兼容旧写法与同义写法"""
        if position in POSITION_MAP:
            return position
        return POSITION_ALIAS_MAP.get(position, "下中")

    def _parse_args(self, text: str) -> Dict:
        """智能解析参数（任意顺序）"""
        result = {
            "text": "",
            "color": self.default_color,
            "size": self.default_size,
            "position": self.default_position,
            "stroke": None,
        }
        
        parts = text.strip().split()
        text_parts = []
        
        for part in parts:
            # 检查颜色
            if part in COLOR_MAP:
                result["color"] = part
            # 检查大小
            elif part in SIZE_MAP:
                result["size"] = part
            # 检查位置
            elif part in POSITION_MAP or part in POSITION_ALIAS_MAP:
                result["position"] = self._normalize_position(part)
            # 检查描边
            elif part in STROKE_MAP:
                result["stroke"] = part
            # 其他作为文字
            else:
                text_parts.append(part)
        
        result["text"] = " ".join(text_parts)
        return result

    def _get_stroke_color(self, text_color: str) -> str:
        """根据文字颜色自动选择描边颜色"""
        # 浅色文字用黑描边，深色文字用白描边
        light_colors = {"白色", "黄色", "粉色"}
        if text_color in light_colors:
            return "#000000"
        return "#FFFFFF"

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logger.error(f"[表情文字] 下载图片失败: {e}")
        return None

    def _add_text_to_image(self, img: Image.Image, text: str, 
                           color: str, size: str, position: str,
                           stroke_color: Optional[str]) -> Image.Image:
        """给静态图片添加文字"""
        draw = ImageDraw.Draw(img)
        
        # 计算字体大小
        img_width, img_height = img.size
        font_size = int(img_width * SIZE_MAP.get(size, 0.08))
        font_size = max(12, min(font_size, 200))  # 限制范围
        
        # 加载字体
        try:
            if self.font_path:
                font = ImageFont.truetype(self.font_path, font_size)
            else:
                font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        
        # 计算文字位置
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        position_key = self._normalize_position(position)
        x_ratio, y_ratio = POSITION_MAP.get(position_key, POSITION_MAP["下中"])
        x = int(img_width * x_ratio - text_width // 2)
        y = int(img_height * y_ratio - text_height // 2)
        
        # 确保文字在图片范围内（含边距保护）
        padding = max(8, int(min(img_width, img_height) * 0.04))
        max_x = max(padding, img_width - text_width - padding)
        max_y = max(padding, img_height - text_height - padding)
        x = max(padding, min(x, max_x))
        y = max(padding, min(y, max_y))
        
        # 获取颜色
        fill_color = COLOR_MAP.get(color, "#FFFFFF")
        
        # 绘制文字（带描边）
        if stroke_color:
            stroke_hex = STROKE_MAP.get(stroke_color, stroke_color)
            draw.text((x, y), text, font=font, fill=fill_color, 
                     stroke_width=self.stroke_width, stroke_fill=stroke_hex)
        elif self.auto_stroke:
            auto_stroke = self._get_stroke_color(color)
            draw.text((x, y), text, font=font, fill=fill_color,
                     stroke_width=self.stroke_width, stroke_fill=auto_stroke)
        else:
            draw.text((x, y), text, font=font, fill=fill_color)
        
        return img

    def _add_text_to_gif(self, img_data: bytes, text: str,
                         color: str, size: str, position: str,
                         stroke_color: Optional[str]) -> bytes:
        """给 GIF 添加文字（逐帧处理）"""
        img = Image.open(io.BytesIO(img_data))
        
        frames = []
        durations = []
        
        try:
            while True:
                # 转换为 RGBA
                frame = img.convert("RGBA")
                # 添加文字
                frame = self._add_text_to_image(frame, text, color, size, position, stroke_color)
                frames.append(frame)
                
                # 获取帧延迟
                duration = img.info.get("duration", 100)
                durations.append(duration)
                
                img.seek(img.tell() + 1)
        except EOFError:
            pass
        
        if not frames:
            return img_data
        
        # 保存为 GIF
        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2
        )
        output.seek(0)
        return output.read()

    def _process_image(self, img_data: bytes, text: str,
                       color: str, size: str, position: str,
                       stroke_color: Optional[str]) -> Tuple[bytes, str]:
        """处理图片，返回 (图片数据, 格式)"""
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else "png"
        
        # GIF 特殊处理
        if img_format == "gif":
            result_data = self._add_text_to_gif(img_data, text, color, size, position, stroke_color)
            return result_data, "gif"
        
        # 静态图片处理
        if img.mode == "RGBA":
            result_img = self._add_text_to_image(img, text, color, size, position, stroke_color)
        else:
            result_img = self._add_text_to_image(img.convert("RGBA"), text, color, size, position, stroke_color)
        
        # 保存（优先保持原格式，最大质量）
        output = io.BytesIO()
        if img_format == "jpeg" or img_format == "jpg":
            result_img = result_img.convert("RGB")
            # 使用最高质量和无二次采样保持清晰度
            result_img.save(output, format="JPEG", quality=100, subsampling=0)
            return output.getvalue(), "jpg"
        else:
            # PNG 无损压缩，不会模糊
            result_img.save(output, format="PNG", optimize=False)
            return output.getvalue(), "png"

    async def _get_reply_image_url(self, event: AstrMessageEvent) -> Optional[str]:
        """获取引用消息中的图片 URL"""
        if not AiocqhttpMessageEvent or not isinstance(event, AiocqhttpMessageEvent):
            logger.debug("[表情文字] 非 aiocqhttp 事件，跳过引用检测")
            return None
        
        try:
            reply_id = None
            
            # 方式1: 从 message_obj.message 消息链中获取 Reply 组件
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'message'):
                message_chain = event.message_obj.message
                if message_chain:
                    for comp in message_chain:
                        # 检查是否有 Reply 组件
                        comp_type = type(comp).__name__
                        logger.debug(f"[表情文字] 消息组件类型: {comp_type}")
                        if comp_type == 'Reply' and hasattr(comp, 'id'):
                            reply_id = comp.id
                            logger.debug(f"[表情文字] 从消息链获取到引用ID: {reply_id}")
                            break
            
            # 方式2: 从 raw_message 中获取
            if not reply_id and hasattr(event, 'message_obj'):
                raw_message = getattr(event.message_obj, 'raw_message', None)
                
                if isinstance(raw_message, list):
                    for seg in raw_message:
                        if isinstance(seg, dict) and seg.get("type") == "reply":
                            reply_id = seg.get("data", {}).get("id")
                            logger.debug(f"[表情文字] 从 raw_message list 获取到引用ID: {reply_id}")
                            break
                elif isinstance(raw_message, dict):
                    # raw_message 可能直接是 dict 格式
                    message_content = raw_message.get("message", [])
                    if isinstance(message_content, list):
                        for seg in message_content:
                            if isinstance(seg, dict) and seg.get("type") == "reply":
                                reply_id = seg.get("data", {}).get("id")
                                logger.debug(f"[表情文字] 从 raw_message dict 获取到引用ID: {reply_id}")
                                break
            
            if not reply_id:
                logger.debug("[表情文字] 未找到引用消息ID")
                return None
            
            # 获取引用的消息内容
            logger.debug(f"[表情文字] 正在获取消息 ID={reply_id} 的内容")
            msg_info = await event.bot.get_msg(message_id=int(reply_id))
            message = msg_info.get("message", [])
            logger.debug(f"[表情文字] 获取到的消息内容: {message}")
            
            # 查找图片
            for seg in message:
                if isinstance(seg, dict) and seg.get("type") == "image":
                    url = seg.get("data", {}).get("url")
                    logger.debug(f"[表情文字] 找到图片 URL: {url}")
                    return url
            
            logger.debug("[表情文字] 引用的消息中没有找到图片")
            
        except Exception as e:
            logger.error(f"[表情文字] 获取引用图片失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return None

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听消息，处理表情文字命令"""
        text = event.message_str.strip() if event.message_str else ""
        
        # 检查命令格式（不需要#前缀）
        prefix = self.command_prefix
        if not text.startswith(prefix):
            return
        
        # 解析参数
        args_text = text[len(prefix):].strip()
        if not args_text:
            await event.send(event.plain_result(f"❌ 用法: {prefix} 文字 [颜色] [字体大小] [位置] [描边]\n"
                f"示例: {prefix} 我是帅哥 白色 中字体 下\n"
                f"颜色: 白色/黑色/红色/黄色/蓝色/绿色/粉色/紫色\n"
                f"大小: 小字体/中字体/大字体\n"
                f"位置: 上左/上中/上右/中左/中/中右/下左/下中/下右（兼容: 上/中/下）\n"
                f"描边: 白色描边/黑色描边"))
            event.stop_event()
            return
        
        # 解析参数
        args = self._parse_args(args_text)
        
        if not args["text"]:
            await event.send(event.plain_result("❌ 请输入要添加的文字"))
            event.stop_event()
            return
        
        if len(args["text"]) > self.max_text_length:
            await event.send(event.plain_result(f"❌ 文字过长，最多 {self.max_text_length} 个字符"))
            event.stop_event()
            return
        
        # 获取引用的图片
        img_url = await self._get_reply_image_url(event)
        if not img_url:
            await event.send(event.plain_result("❌ 请引用一张图片（表情）后使用此命令"))
            event.stop_event()
            return
        
        # 下载图片
        await event.send(event.plain_result("⏳ 处理中..."))
        img_data = await self._download_image(img_url)
        if not img_data:
            await event.send(event.plain_result("❌ 图片下载失败"))
            event.stop_event()
            return
        
        try:
            # 处理图片
            result_data, img_format = self._process_image(
                img_data, 
                args["text"],
                args["color"],
                args["size"],
                args["position"],
                args["stroke"]
            )
            
            # 保存临时文件
            temp_dir = os.path.join(PLUGIN_DIR, "temp")
            os.makedirs(temp_dir, exist_ok=True)
            
            import time
            temp_file = os.path.join(temp_dir, f"meme_{int(time.time() * 1000)}.{img_format}")
            with open(temp_file, "wb") as f:
                f.write(result_data)
            
            # 发送图片
            await event.send(event.image_result(temp_file))
            
            # 清理临时文件
            try:
                os.remove(temp_file)
            except:
                pass
            
        except Exception as e:
            logger.error(f"[表情文字] 处理图片失败: {e}")
            await event.send(event.plain_result(f"❌ 处理失败: {e}"))
        
        event.stop_event()

    @filter.command("皓月表情加字帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = f"""🎨 表情包添加文字插件

📝 使用方法
1. 引用一张表情图片
2. 发送: {self.command_prefix} 文字

📌 完整命令
{self.command_prefix} 文字 [颜色] [大小] [位置] [描边]
（参数顺序随意）

🎨 可用颜色
白色 黑色 红色 黄色 蓝色 绿色 粉色 紫色

📏 字体大小
小字体 中字体 大字体

📍 文字位置
上左 上中 上右
中左 中 中右
下左 下中 下右
（兼容旧写法：上/中/下）

✨ 描边效果
白色描边 黑色描边（不写则自动）

💡 示例
{self.command_prefix} 哈哈哈
{self.command_prefix} 帅哥 红色 大字体 上
{self.command_prefix} 快跑 黄色 中字体 下右
{self.command_prefix} 666 黑色 白色描边"""
        
        yield event.plain_result(help_text)
