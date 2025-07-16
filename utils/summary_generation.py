from pathlib import Path

import aiofiles
import markdown
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.services.llm import (
    LLMException,
    LLMMessage,
    get_model_instance,
)
from zhenxun.services.log import logger

from .. import base_config
from ..store import store
from .core import ErrorCode, SummaryException

md_to_pic, html_to_pic = None, None
if base_config.get("summary_output_type") == "image":
    try:
        from nonebot import require

        require("nonebot_plugin_htmlrender")
        from nonebot_plugin_htmlrender import html_to_pic
    except Exception as e:
        logger.warning(f"加载 htmlrender 失败，图片模式不可用: {e}")


async def messages_summary(
    target: MsgTarget,
    messages: list[dict[str, str]],
    content: str | None = None,
    target_user_names: list[str] | None = None,
    style: str | None = None,
    model_name: str | None = None,
) -> str:
    if not messages:
        logger.warning("没有足够的聊天记录可供总结", command="messages_summary")
        return "没有足够的聊天记录可供总结。"

    prompt_parts = []
    group_id = target.id if not target.private else None

    final_style = style
    if not final_style and group_id:
        final_style = store.get_group_setting(str(group_id), "default_style")
        if final_style:
            logger.debug(f"群聊 {group_id} 使用特定默认风格: '{final_style}'")
    if not final_style:
        final_style = base_config.get("SUMMARY_DEFAULT_STYLE")
        if final_style:
            logger.debug(f"使用插件全局默认风格: '{final_style}'")

    if final_style:
        prompt_parts.append(f"重要指令：请严格使用 '{final_style}' 的风格进行总结。")

    if target_user_names:
        user_list_str = ", ".join(target_user_names)
        task_desc = f"任务：在以下聊天记录中，详细总结用户 [{user_list_str}] "
        if content:
            task_desc += f"仅与'{content}'相关的发言内容和主要观点。"
        else:
            task_desc += "的所有发言内容和主要观点。"
        prompt_parts.append(task_desc)
        if len(target_user_names) > 1:
            prompt_parts.append(
                f"请注意：这里有 {len(target_user_names)} 个不同的用户，必须分别对每个用户的发言进行单独总结。"
            )
    elif content:
        prompt_parts.append(f"任务：请详细总结以下对话中仅与'{content}'相关的内容。")
    else:
        prompt_parts.append("任务：请分析并总结以下聊天记录的主要讨论内容和信息脉络。")

    prompt_parts.append(
        "要求：排版需层次清晰，用中文回答，请包含谁说了什么重要内容。\n"
        "注意使用丰富的markdown格式让内容更美观，注意要在合适的场景使用合适的样式,包括："
        "标题层级(h1-h6),分隔线(hr)、表格(table)、斜体(em)、"
        "任务列表(chekbox)、删除线 (Strikethrough)、"
        "emoji增强格式(emoji-enhanced formatting)等。\n"
        "避免使用graph td样式"
    )
    final_prompt = "\n\n".join(prompt_parts)

    llm_messages: list[LLMMessage] = []

    llm_messages.append(LLMMessage.system(final_prompt))

    user_content = "\n".join([f"{msg['name']}: {msg['content']}" for msg in messages])
    llm_messages.append(LLMMessage.user(user_content))

    final_model_name_str = model_name
    if not final_model_name_str and group_id:
        final_model_name_str = store.get_group_setting(
            str(group_id), "default_model_name"
        )
        if final_model_name_str:
            logger.debug(f"群聊 {group_id} 使用特定模型: {final_model_name_str}")
    if not final_model_name_str:
        final_model_name_str = base_config.get("SUMMARY_MODEL_NAME")
        if final_model_name_str:
            logger.debug(f"使用插件默认模型: {final_model_name_str}")

    try:
        logger.info(
            f"开始调用LLM服务进行总结，模型: {final_model_name_str or 'LLM全局默认'}"
        )

        async with await get_model_instance(final_model_name_str) as model:
            response = await model.generate_response(llm_messages)
            summary_text = response.text

        return summary_text
    except LLMException as e:
        logger.error(
            f"总结生成失败 (LLMException): {e}", command="messages_summary", e=e
        )
        raise
    except Exception as e:
        logger.error(
            f"总结生成过程中出现意外错误: {e}",
            command="messages_summary",
            e=e,
        )
        raise LLMException(f"总结生成失败: {e!s}") from e


async def generate_image(
    summary: str, user_info_cache: dict[str, str] | None = None
) -> bytes:
    if html_to_pic is None:
        raise ValueError("图片生成功能未启用或 htmlrender 未正确加载")
    try:
        html_from_md = markdown.markdown(
            summary,
            extensions=[
                "pymdownx.tasklist",
                "tables",
                "fenced_code",
                "codehilite",
                "mdx_math",
                "pymdownx.tilde",
            ],
            extension_configs={"mdx_math": {"enable_dollar_delimiter": True}},
        )

        enhanced_html = html_from_md
        if user_info_cache:
            from .message_processing import avatar_enhancer

            use_avatars = base_config.get("ENABLE_AVATAR_ENHANCEMENT", False)

            await avatar_enhancer.enhance_summary_with_avatars(
                summary, user_info_cache
            )

            if not use_avatars:
                enhanced_html = avatar_enhancer.enhance_html_with_markup(
                    html_from_md, user_info_cache, mode="mention"
                )
            else:
                enhanced_html = avatar_enhancer.enhance_html_with_markup(
                    html_from_md, user_info_cache, mode="avatar"
                )
        logger.debug(f"final_html: {enhanced_html}")
        css_file = "dark.css"
        theme = base_config.get("summary_theme")
        if theme == "light":
            css_file = "light.css"
        elif theme == "dark":
            css_file = "dark.css"
        elif theme == "cyber":
            css_file = "cyber.css"

        css_path = (Path(__file__).parent.parent / "assert" / css_file).resolve()

        async with aiofiles.open(css_path, encoding="utf-8") as f:
            css_content = await f.read()

        final_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta charset="utf-8">
            <style type="text/css">
                {css_content}
            </style>
            <style>
                .markdown-body {{
                    box-sizing: border-box;
                    min-width: 200px;
                    max-width: 980px;
                    margin: 0 auto;
                    padding: 45px;
                }}
                @media (max-width: 767px) {{
                    .markdown-body {{
                        padding: 15px;
                    }}
                }}
            </style>
        </head>
        <body>
            <article class="markdown-body">
                {enhanced_html}
            </article>
        </body>
        </html>
        """

        logger.debug(f"使用主题 {theme or '默认'} 生成图片", command="图片生成")

        img = await html_to_pic(
            html=final_html,
            viewport={"width": 850, "height": 10},
        )
        return img
    except Exception as e:
        logger.error(f"生成图片过程中发生意外错误: {e}", command="图片生成", e=e)
        raise SummaryException(
            f"图片生成失败: {e!s}", code=ErrorCode.IMAGE_GENERATION_FAILED
        ) from e


async def send_summary(
    bot: Bot,
    target: MsgTarget,
    summary: str,
    user_info_cache: dict[str, str] | None = None,
) -> bool:
    try:
        reply_msg = None
        output_type = base_config.get("summary_output_type", "image")
        fallback_enabled = base_config.get("summary_fallback_enabled", False)

        if output_type == "image":
            try:
                img_bytes = await generate_image(summary, user_info_cache)

                reply_msg = UniMessage.image(raw=img_bytes)
            except (SummaryException, ValueError) as e:
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

            logger.info(
                f"总结已发送，类型: {output_type or 'text'}", command="send_summary"
            )
            return True

        logger.error("无法发送总结：回复消息为空", command="send_summary")
        return False

    except Exception as e:
        logger.error(f"发送总结失败: {e}", command="send_summary", e=e)
        return False


async def read_tpl(path: str) -> str:
    from nonebot_plugin_htmlrender.data_source import TEMPLATES_PATH

    async with aiofiles.open(f"{TEMPLATES_PATH}/{path}") as f:
        return await f.read()
