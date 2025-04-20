from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.configs.config import Config
from zhenxun.services.log import logger

base_config = Config.get("summary_group")

from ..model import ModelException, detect_model
from ..store import Store

# 创建 Store 实例
store = Store()

md_to_pic = None
if base_config.get("summary_output_type") == "image":
    try:
        from nonebot import require

        require("nonebot_plugin_htmlrender")
        from nonebot_plugin_htmlrender import md_to_pic
    except Exception as e:
        logger.warning(f"加载 htmlrender 失败，图片模式不可用: {e}")

from .health import with_retry
from .scheduler import SummaryException


class MessageProcessException(SummaryException):
    pass


class ImageGenerationException(SummaryException):
    pass


async def messages_summary(
    target: MsgTarget,
    messages: list[dict[str, str]],
    content: str | None = None,
    target_user_names: list[str] | None = None,
    style: str | None = None, # 这个 style 是命令传入的
) -> str:
    if not messages:
        logger.warning("没有足够的聊天记录可供总结", command="messages_summary")
        return "没有足够的聊天记录可供总结。"

    prompt_parts = []
    group_id = target.id if not target.private else None # 获取 group_id

    # --- 决定最终使用的 style ---
    final_style = style # 优先使用命令传入的 style
    if not final_style and group_id:
        group_default_style = store.get_group_setting(str(group_id), "default_style")
        if group_default_style:
            final_style = group_default_style
            logger.debug(f"群聊 {group_id} 使用特定默认风格: '{final_style}'")

    if final_style:
        prompt_parts.append(f"重要指令：请严格使用 '{final_style}' 的风格进行总结。")
        logger.debug(f"最终应用总结风格: '{final_style}' (置于Prompt开头)", command="messages_summary")

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

    # --- 决定最终使用的模型名称 ---
    final_model_name_str = Config.get_config("summary_group", "CURRENT_ACTIVE_MODEL_NAME") # 全局激活
    if group_id:
        group_specific_model = store.get_group_setting(str(group_id), "default_model_name")
        if group_specific_model:
            # 验证模型是否存在
            from .handlers.model_control import parse_provider_model_string, find_model
            prov_name, mod_name = parse_provider_model_string(group_specific_model)
            if prov_name and mod_name and find_model(prov_name, mod_name):
                 final_model_name_str = group_specific_model
                 logger.debug(f"群聊 {group_id} 使用特定模型: {final_model_name_str}")
            else:
                 logger.warning(f"群聊 {group_id} 配置的特定模型 '{group_specific_model}' 无效，将使用全局模型 '{final_model_name_str}'。")

    # --- 定义调用模型的内部函数 ---
    async def invoke_model():
        try:
            # --- 使用新的函数获取模型实例 ---
            from .handlers.model_control import get_model_instance_by_name
            model = get_model_instance_by_name(final_model_name_str)
            return await model.summary_history(messages, final_prompt)
        except ModelException:
            raise
        except Exception as e:
            logger.error(f"生成总结失败 (invoke_model): {e}", command="messages_summary", e=e)
            raise ModelException(f"生成总结时发生内部错误: {e!s}") from e

    try:
        max_retries = base_config.get("MAX_RETRIES", 3)
        retry_delay = base_config.get("RETRY_DELAY", 2)
        summary_text = await with_retry(
            invoke_model,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        return summary_text
    except ModelException as e:
        logger.error(f"总结生成失败，已达最大重试次数: {e}", command="messages_summary", e=e)
        raise
    except Exception as e:
        logger.error(
            f"总结生成过程中出现意外错误 (with_retry): {e}",
            command="messages_summary",
            e=e,
        )
        raise ModelException(f"总结生成失败: {e!s}")


async def generate_image(summary: str) -> bytes:
    if md_to_pic is None:
        raise ValueError("图片生成功能未启用或 htmlrender 未正确加载")
    try:
        css_file = "github-markdown-dark.css"
        theme = base_config.get("summary_theme", "vscode_dark")

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
            raise ImageGenerationException(f"图片生成失败: {e!s}")
        else:
            raise


async def send_summary(bot: Bot, target: MsgTarget, summary: str) -> bool:
    try:
        reply_msg = None
        output_type = base_config.get("summary_output_type", "image")
        fallback_enabled = base_config.get("summary_fallback_enabled", False)

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

                logger.warning(f"图片生成失败，已启用文本回退: {e}", command="send_summary")

        if reply_msg is None:
            error_prefix = ""
            if output_type == "image" and fallback_enabled:
                error_prefix = "⚠️ 图片生成失败，降级为文本输出：\n\n"

            plain_summary = summary.strip()

            if "<" in plain_summary and ">" in plain_summary:
                import re

                plain_summary = re.sub(r"<[^>]+>", "", plain_summary)

            max_text_length = 4500
            full_text = f"{error_prefix}{plain_summary}"

            if len(full_text) > max_text_length:
                full_text = full_text[:max_text_length] + "...(内容过长已截断)"
            reply_msg = UniMessage.text(full_text)

        if reply_msg:
            await reply_msg.send(target, bot)

            logger.info(f"总结已发送，类型: {output_type or 'text'}", command="send_summary")
            return True

        logger.error("无法发送总结：回复消息为空", command="send_summary")
        return False

    except Exception as e:
        logger.error(f"发送总结失败: {e}", command="send_summary", e=e)
        return False
