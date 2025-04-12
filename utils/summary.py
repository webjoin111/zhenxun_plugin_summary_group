from typing import List, Dict, Optional, Any, Set, Tuple, Union
from pathlib import Path
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import UniMessage, Target, MsgTarget

from zhenxun.configs.config import Config
from zhenxun.services.log import logger
from zhenxun.utils.platform import PlatformUtils, UserData


base_config = Config.get("summary_group")
if base_config is None:
    logger.error("[utils/summary.py] 无法加载 'summary_group' 配置!")
    base_config = {}

from ..model import detect_model, ModelException


md_to_pic = None
if base_config.get("summary_output_type") == "image":
    try:
        from nonebot import require

        require("nonebot_plugin_htmlrender")
        from nonebot_plugin_htmlrender import md_to_pic
    except Exception as e:
        logger.warning(f"加载 htmlrender 失败，图片模式不可用: {e}")

from .scheduler import SummaryException
from .health import with_retry


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
    if not messages:
        logger.warning("没有足够的聊天记录可供总结", command="messages_summary")
        return "没有足够的聊天记录可供总结。"

    prompt_parts = []

    if style:
        prompt_parts.append(f"重要指令：请严格使用 '{style}' 的风格进行总结。")
        logger.debug(
            f"已应用总结风格: '{style}' (置于Prompt开头)", command="messages_summary"
        )

    if target_user_names:
        user_list_str = ", ".join(target_user_names)
        if content:
            prompt_parts.append(
                f"任务：请在以下聊天记录中，详细总结用户 [{user_list_str}] 仅与'{content}'相关的发言内容和主要观点。"
            )
        else:
            prompt_parts.append(
                f"任务：请详细总结用户 [{user_list_str}] 在以下聊天记录中的所有发言内容和主要观点。"
            )

        logger.debug(
            f"为指定用户生成总结, 用户: {user_list_str}, 内容过滤: '{content or '无'}'",
            command="messages_summary",
        )
    elif content:
        prompt_parts.append(f"任务：请详细总结以下对话中仅与'{content}'相关的内容。")
        logger.debug(f"为指定内容 '{content}' 生成总结", command="messages_summary")
    else:
        prompt_parts.append("任务：请分析并总结以下聊天记录的主要讨论内容和信息脉络。")
        logger.debug("生成通用群聊总结", command="messages_summary")

    prompt_parts.append("要求：排版需层次清晰，用中文回答。请包含谁说了什么重要内容。")

    final_prompt = "\n\n".join(prompt_parts)

    logger.debug(f"最终构建的 Prompt: {final_prompt}", command="messages_summary")

    async def invoke_model():
        try:
            model = detect_model()

            return await model.summary_history(messages, final_prompt)
        except ModelException:
            raise
        except Exception as e:
            logger.error(
                f"生成总结失败 (invoke_model): {e}", command="messages_summary", e=e
            )

            raise ModelException(f"生成总结时发生内部错误: {str(e)}") from e

    try:

        max_retries = base_config.get("MAX_RETRIES")
        retry_delay = base_config.get("RETRY_DELAY")
        summary_text = await with_retry(
            invoke_model,
            max_retries=max_retries if max_retries is not None else 3,
            retry_delay=retry_delay if retry_delay is not None else 2,
        )

        beautify_enabled = base_config.get("SUMMARY_BEAUTIFY_USERNAME")
        if beautify_enabled:
            if "<span" not in summary_text and target_user_names:

                pass
        elif "<span" in summary_text:

            pass

        return summary_text
    except ModelException as e:
        logger.error(
            f"总结生成失败，已达最大重试次数: {e}", command="messages_summary", e=e
        )
        raise
    except Exception as e:
        logger.error(
            f"总结生成过程中出现意外错误 (with_retry): {e}",
            command="messages_summary",
            e=e,
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

    if md_to_pic is None:
        raise ValueError("图片生成功能未启用或 htmlrender 未正确加载")
    try:

        css_file = "github-markdown-dark.css"
        theme = base_config.get("summary_theme")

        if theme == "light":
            css_file = "github-markdown-light.css"
        elif theme == "dark":
            css_file = "github-markdown-dark.css"
        elif theme == "vscode_dark":
            css_file = "vscode-dark.css"
        elif theme == "vscode_light":
            css_file = "vscode-light.css"

        css_path = (Path(__file__).parent.parent / "assert" / css_file).resolve()
        logger.debug(f"使用主题 {theme or '默认'} 生成图片", command="图片生成")
        img = await md_to_pic(summary, css_path=css_path)

        return img
    except Exception as e:
        if not isinstance(e, ImageGenerationException):
            logger.error(f"生成图片过程中发生意外错误: {e}", command="图片生成", e=e)
            raise ImageGenerationException(f"图片生成失败: {str(e)}")
        else:
            raise


async def send_summary(bot: Bot, target: MsgTarget, summary: str) -> bool:
    try:

        reply_msg = None
        output_type = base_config.get("summary_output_type")
        fallback_enabled = base_config.get("summary_fallback_enabled")
        beautify_enabled = base_config.get("SUMMARY_BEAUTIFY_USERNAME")

        if output_type == "image":
            try:
                img_bytes = await generate_image(summary)

                reply_msg = UniMessage.image(raw=img_bytes)
            except (ImageGenerationException, ValueError) as e:
                if not fallback_enabled:

                    logger.error(
                        f"图片生成失败且未启用文本回退: {e}",
                        command="send_summary",
                        e=e,
                    )
                    return False

                logger.warning(
                    f"图片生成失败，已启用文本回退: {e}", command="send_summary"
                )

        if reply_msg is None:
            error_prefix = ""
            if output_type == "image" and fallback_enabled:

                error_prefix = "⚠️ 图片生成失败，降级为文本输出：\n\n"

            plain_summary = summary.strip()

            if "<span" in plain_summary:
                import re

                plain_summary = re.sub(
                    r"<span[^>]*>([^<]+?)</span>", r"\1", plain_summary
                )

            max_text_length = 4500
            full_text = f"{error_prefix}{plain_summary}"

            if len(full_text) > max_text_length:
                full_text = full_text[:max_text_length] + "...(内容过长已截断)"
            reply_msg = UniMessage.text(full_text)

        if reply_msg:
            await reply_msg.send(target, bot)

            logger.info(
                f"总结已发送，类型: {output_type or 'text'}", command="send_summary"
            )
            return True

        logger.error("无法发送总结：回复消息为空", command="send_summary")
        return False

    except Exception as e:
        logger.error(f"发送总结失败: {e}", command="send_summary", e=e)
        return False
