from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import Target, UniMessage

from zhenxun import ui
from zhenxun.services.ai import LLMMessage
from zhenxun.services.ai.core.exceptions import LLMException
from zhenxun.services.ai.llm import generate
from zhenxun.services.log import logger

from .. import base_config
from ..config import GroupSettings
from ..ui import GroupSummaryComponent


async def messages_summary(
    target: Target,
    messages: list[dict[str, str]],
    content: str | None = None,
    target_user_names: list[str] | None = None,
    style: str | None = None,
    model_name: str | None = None,
    group_config: GroupSettings | None = None,
) -> str:
    if not messages:
        logger.warning("没有足够的聊天记录可供总结", command="messages_summary")
        return "没有足够的聊天记录可供总结。"

    prompt_parts = []

    final_style = style
    final_style = final_style or (group_config.default_style if group_config else None)

    if not final_style:
        final_style = base_config.get("SUMMARY_DEFAULT_STYLE")

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
                f"请注意：这里有 {len(target_user_names)} 个不同的用户，"
                "必须分别对每个用户的发言进行单独总结。"
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
    if not final_model_name_str and group_config and group_config.default_model_name:
        final_model_name_str = group_config.default_model_name
    if not final_model_name_str:
        final_model_name_str = base_config.get("SUMMARY_MODEL_NAME")
        if final_model_name_str:
            logger.debug(f"使用插件默认模型: {final_model_name_str}")

    try:
        logger.info(
            f"开始调用LLM服务进行总结，模型: {final_model_name_str or 'LLM全局默认'}"
        )

        response = await generate(messages=llm_messages, model=final_model_name_str)
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


async def create_summary_component(
    summary: str, user_info_cache: dict[str, str] | None = None
) -> GroupSummaryComponent:
    """
    创建一个可被渲染的群聊总结UI组件。

    :param summary: Markdown格式的总结文本。
    :param user_info_cache: 用于头像查找的用户信息。
    :return: 一个GroupSummaryComponent实例。
    """
    return GroupSummaryComponent(
        markdown_content=summary,
        user_info_cache=user_info_cache or {},
    )


async def send_summary(
    bot: Bot,
    target: Target,
    summary: str,
    user_info_cache: dict[str, str] | None = None,
) -> bool:
    try:
        reply_msg = None
        output_type = base_config.get("summary_output_type", "image")
        fallback_enabled = base_config.get("summary_fallback_enabled", False)

        if output_type == "image":
            try:
                component = await create_summary_component(summary, user_info_cache)
                img_bytes = await ui.render(
                    component, viewport={"width": 850, "height": 10}
                )
                reply_msg = UniMessage.image(raw=img_bytes)
            except Exception as e:
                if not fallback_enabled:
                    logger.error(
                        f"图片渲染失败且未启用文本回退: {e}",
                        command="send_summary",
                        e=e,
                    )
                    return False

                logger.warning(
                    f"图片渲染失败，已启用文本回退: {e}", command="send_summary"
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
