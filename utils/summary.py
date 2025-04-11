from typing import List, Dict, Optional, Any, Set, Tuple, Union
from pathlib import Path
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import UniMessage, Target, MsgTarget

from zhenxun.configs.config import Config
from zhenxun.services.log import logger
from zhenxun.utils.platform import PlatformUtils, UserData

from ..model import detect_model

if Config.get("summary_group").get("summary_in_png"):
    from nonebot import require

    require("nonebot_plugin_htmlrender")
    from nonebot_plugin_htmlrender import md_to_pic

from .scheduler import SummaryException


class ModelException(SummaryException):

    pass


class MessageProcessException(SummaryException):

    pass


class ImageGenerationException(SummaryException):

    pass


async def messages_summary(
    messages: List[Dict[str, str]],
    content: Optional[str] = None,
    target_user_names: Optional[List[str]] = None,
    style: Optional[str] = None,
) -> str:
    from .health import with_retry

    if not messages:
        logger.warning("没有足够的聊天记录可供总结", command="messages_summary")
        return "没有足够的聊天记录可供总结。"

    prompt = ""
    if target_user_names:
        user_list_str = ", ".join(target_user_names)
        if content:
            prompt = (
                f"请在以下聊天记录中，详细总结用户 [{user_list_str}] "
                f"仅与'{content}'相关的发言内容和主要观点。排版需层次清晰，用中文回答。"
            )
        else:
            prompt = (
                f"请详细总结用户 [{user_list_str}] 在以下聊天记录中的所有发言内容和主要观点。"
                f"排版需层次清晰，用中文回答。"
            )
        logger.debug(
            f"为指定用户生成总结, 用户: {user_list_str}, 内容过滤: '{content or '无'}'",
            command="messages_summary",
        )
    elif content:
        prompt = (
            f"请详细总结以下对话中仅与'{content}'相关的内容。"
            f"排版需层次清晰, 用中文回答。"
        )
        logger.debug(f"为指定内容 '{content}' 生成总结", command="messages_summary")
    else:
        prompt = (
            "请详细总结这个群聊的内容脉络，要有什么人说了什么。"
            "排版需层次清晰, 用中文回答。"
        )
        logger.debug("生成通用群聊总结", command="messages_summary")

    final_prompt = prompt
    if style:
        style_instruction = f"\n\n请注意：请使用'{style}'的风格进行总结。"
        final_prompt += style_instruction
        logger.debug(f"已应用总结风格: '{style}'", command="messages_summary")

    async def invoke_model():
        try:
            model = detect_model()
            return await model.summary_history(messages, final_prompt)
        except Exception as e:
            logger.error(f"生成总结失败: {e}", command="messages_summary", e=e)
            raise ModelException(f"生成总结失败: {str(e)}")

    try:
        return await with_retry(
            invoke_model,
            max_retries=Config.get("summary_group").get("MAX_RETRIES", 3),
            retry_delay=Config.get("summary_group").get("RETRY_DELAY", 2),
        )
    except ModelException:
        raise
    except Exception as e:
        logger.error(
            f"总结生成过程中出现意外错误: {e}", command="messages_summary", e=e
        )
        raise ModelException(f"总结生成失败: {str(e)}")


async def process_message(
    messages: list, bot: Bot, group_id: int
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    logger.debug(
        f"开始处理群 {group_id} 的 {len(messages)} 条原始消息", command="消息处理"
    )
    try:
        if not messages:
            logger.warning(f"群 {group_id} 没有消息需要处理", command="消息处理")
            return [], {}

        qq_map: dict[str, str] = {}
        user_info_cache: dict[str, str] = {}
        processed_data: list[dict] = []

        for msg in messages:
            user_id = msg.get("user_id")
            if not user_id:
                logger.warning(
                    f"消息缺少 user_id，跳过处理: {msg.get('message_id', 'N/A')}",
                    group_id=group_id,
                )
                continue

            user_id_str = str(user_id)

            if user_id_str not in user_info_cache:
                sender_name = f"用户_{user_id_str[-4:]}"
                try:
                    user_data: UserData | None = await PlatformUtils.get_user(
                        bot, user_id_str, str(group_id)
                    )
                    if user_data:
                        sender_name = (
                            user_data.card
                            or user_data.name
                            or f"用户_{user_id_str[-4:]}"
                        )
                        logger.debug(
                            f"成功获取用户信息: {user_id_str} -> {sender_name}",
                            group_id=group_id,
                        )
                    else:
                        sender_info_fallback = msg.get("sender", {})
                        sender_name = (
                            sender_info_fallback.get("card")
                            or sender_info_fallback.get("nickname")
                            or f"用户_{user_id_str[-4:]}"
                        )
                        logger.debug(
                            f"PlatformUtils 未获取到用户 {user_id_str} 信息，使用原始消息 sender: {sender_name}",
                            group_id=group_id,
                        )
                    user_info_cache[user_id_str] = sender_name
                except Exception as e:
                    logger.warning(
                        f"获取用户 {user_id_str} 信息失败: {e}. 使用默认值",
                        group_id=group_id,
                        e=e,
                    )
                    sender_info_fallback = msg.get("sender", {})
                    sender_name = (
                        sender_info_fallback.get("card")
                        or sender_info_fallback.get("nickname")
                        or f"user_{user_id_str[-4:]}"
                    )
                    user_info_cache[user_id_str] = sender_name

            raw_segments = msg.get("message", [])
            processed_data.append({"user_id": user_id_str, "segments": raw_segments})

        result: list[Dict[str, str]] = []
        for item in processed_data:
            user_id = item["user_id"]
            sender_name = user_info_cache.get(user_id, f"用户_{user_id[-4:]}")
            marked_sender = f'<span class="user-nickname">{sender_name}</span>'
            text_segments: list[str] = []

            for segment in item["segments"]:
                if not isinstance(segment, dict):
                    continue

                seg_type = segment.get("type")
                seg_data = segment.get("data", {})

                if seg_type == "text" and "text" in seg_data:
                    text = seg_data["text"].strip()
                    if text:
                        text_segments.append(text)
                elif seg_type == "at" and "qq" in seg_data:
                    qq = str(seg_data["qq"])
                    at_name = user_info_cache.get(qq, f"用户{qq[-4:]}")
                    text_segments.append(f"@{at_name}")

            if text_segments:
                result.append({sender_name: "".join(text_segments)})

        if result:
            try:
                result.pop()
                logger.debug(f"移除了处理后的最后一条消息", group_id=group_id)
            except IndexError:
                pass

        logger.debug(
            f"消息处理完成，共生成 {len(result)} 条格式化记录",
            group_id=group_id,
            command="消息处理",
        )
        return result, user_info_cache
    except Exception as e:
        logger.error(
            f"处理群 {group_id} 消息时发生严重错误: {e}",
            command="消息处理",
            e=e,
            group_id=group_id,
        )
        raise MessageProcessException(f"消息处理失败: {str(e)}")


async def generate_image(summary: str) -> bytes:
    try:
        if not Config.get("summary_group").get("summary_in_png"):
            raise ValueError("图片生成功能未启用")

        css_file = "github-markdown-dark.css"
        base_config = Config.get("summary_group")

        theme = base_config.get("summary_theme", "dark")
        if theme == "light":
            css_file = "github-markdown-light.css"
        elif theme == "dark":
            css_file = "github-markdown-dark.css"
        elif theme == "vscode_dark":
            css_file = "vscode-dark.css"
        elif theme == "vscode_light":
            css_file = "vscode-light.css"

        css_path = (Path(__file__).parent.parent / "assert" / css_file).resolve()

        logger.debug(f"使用主题 {theme}，CSS 文件: {css_path}", command="图片生成")
        img = None
        try:
            logger.debug(f"开始调用 md_to_pic 生成图片", command="图片生成")
            img = await md_to_pic(summary, css_path=css_path)

            if img:
                logger.debug(
                    f"md_to_pic 返回类型: {type(img)}, 长度: {len(img)}",
                    command="图片生成",
                )
            else:
                logger.warning("md_to_pic 返回了 None", command="图片生成")
        except Exception as md_e:
            logger.error(f"md_to_pic 调用失败: {md_e}", command="图片生成", e=md_e)
            raise

        if not isinstance(img, bytes) or not img:
            logger.error(
                f"generate_image 未从 md_to_pic 获得有效的 bytes 数据。获得类型: {type(img)}",
                command="图片生成",
            )
            raise ImageGenerationException("md_to_pic 未返回有效的图片数据")

        return img
    except Exception as e:

        if not isinstance(e, ImageGenerationException):
            logger.error(f"生成图片过程中发生意外错误: {e}", command="图片生成", e=e)
            raise ImageGenerationException(f"图片生成失败: {str(e)}")
        else:
            raise


async def send_summary(bot: Bot, target: MsgTarget, summary: str) -> bool:
    try:
        base_config = Config.get("summary_group")
        reply_msg = None

        output_type = base_config.get("summary_output_type", "image")
        fallback_enabled = base_config.get("summary_fallback_enabled", False)

        if output_type == "image":
            try:
                logger.debug(f"开始生成总结图片", command="总结发送")
                img_bytes = await generate_image(summary)

                if img_bytes:
                    logger.debug(
                        f"generate_image 返回了 bytes 数据，长度: {len(img_bytes)}",
                        command="总结发送",
                    )
                    reply_msg = UniMessage.image(raw=img_bytes)
                    logger.debug(
                        f"总结将以图片方式发送到 target: {target.id}",
                        command="总结发送",
                    )
                else:
                    logger.error(
                        "generate_image 意外返回了 None 或空 bytes", command="总结发送"
                    )
                    if not fallback_enabled:
                        raise ImageGenerationException("图片生成失败，且未启用回退模式")
                    logger.warning("图片生成失败，将回退到文本模式", command="总结发送")
            except Exception as e:
                if not fallback_enabled:
                    logger.error(
                        f"图片生成失败且未启用回退模式: {e}", command="总结发送", e=e
                    )
                    raise ImageGenerationException(f"图片生成失败: {str(e)}")
                logger.warning(
                    f"图片生成失败，将回退到文本模式: {e}", command="总结发送"
                )

        if not reply_msg:
            reply_msg = UniMessage.text(summary)
            logger.debug(
                f"总结将以文本方式发送到 target: {target.id}", command="总结发送"
            )

        if reply_msg:
            # logger.debug(f"构造的 UniMessage: {repr(reply_msg)}", command="总结发送")
            try:
                exported_msg = await reply_msg.export(bot)
                # logger.debug(f"导出的消息: {repr(exported_msg)}", command="总结发送")
            except Exception as export_e:
                logger.error(
                    f"UniMessage 导出失败: {export_e}", command="总结发送", e=export_e
                )

            await reply_msg.send(target, bot)
            logger.debug(f"总结成功发送到 target: {target.id}", command="总结发送")
            return True
        else:
            logger.error(
                f"无法构造有效的总结消息发送到 target: {target.id}", command="总结发送"
            )
            return False
    except Exception as e:
        logger.error(f"发送总结消息时发生异常: {e}", command="总结发送", e=e)
        return False
