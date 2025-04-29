from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.services.log import logger

from .. import base_config
from ..model import ModelException
from ..store import store
from .exceptions import (
    ImageGenerationException,
)

md_to_pic = None
if base_config.get("summary_output_type") == "image":
    try:
        from nonebot import require

        require("nonebot_plugin_htmlrender")
        from nonebot_plugin_htmlrender import md_to_pic
    except Exception as e:
        logger.warning(f"加载 htmlrender 失败，图片模式不可用: {e}")

from .health import with_retry


async def messages_summary(
    target: MsgTarget,
    messages: list[dict[str, str]],
    content: str | None = None,
    target_user_names: list[str] | None = None,
    style: str | None = None,
) -> str:
    if not messages:
        logger.warning("没有足够的聊天记录可供总结", command="messages_summary")
        return "没有足够的聊天记录可供总结。"

    prompt_parts = []
    group_id = target.id if not target.private else None

    final_style = style
    if not final_style and group_id:
        group_default_style = store.get_group_setting(str(group_id), "default_style")
        if group_default_style:
            final_style = group_default_style
            logger.debug(f"群聊 {group_id} 使用特定默认风格: '{final_style}'")

    if final_style:
        prompt_parts.append(f"重要指令：请严格使用 '{final_style}' 的风格进行总结。")
        logger.debug(
            f"最终应用总结风格: '{final_style}' (置于Prompt开头)",
            command="messages_summary",
        )

    if target_user_names:
        user_list_str = ", ".join(target_user_names)
        if content:
            prompt_parts.append(
                f"任务：请在以下聊天记录中，详细总结用户 [{user_list_str}] 仅与'{content}'相关的发言内容和主要观点。"
            )
        else:
            prompt_parts.append(
                f"任务：请分别详细总结每个用户 [{user_list_str}] 在以下聊天记录中的所有发言内容和主要观点。"
            )

        if len(target_user_names) > 1:
            prompt_parts.append(
                f"请注意：这里有 {len(target_user_names)} 个不同的用户，必须分别对每个用户的发言进行单独总结."
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

    final_model_name_str = base_config.get("CURRENT_ACTIVE_MODEL_NAME")
    if group_id:
        group_specific_model = store.get_group_setting(
            str(group_id), "default_model_name"
        )
        if group_specific_model:
            from ..handlers.model_control import find_model, parse_provider_model_string

            prov_name, mod_name = parse_provider_model_string(group_specific_model)
            if prov_name and mod_name and find_model(prov_name, mod_name):
                final_model_name_str = group_specific_model
                logger.debug(f"群聊 {group_id} 使用特定模型: {final_model_name_str}")
            else:
                logger.warning(
                    f"群聊 {group_id} 配置的特定模型 '{group_specific_model}' 无效，将使用全局模型 '{final_model_name_str}'。"
                )

    async def invoke_model():
        try:
            from ..handlers.model_control import get_model_instance_by_name

            model = get_model_instance_by_name(final_model_name_str)
            return await model.summary_history(messages, final_prompt)
        except ModelException:
            raise
        except Exception as e:
            logger.error(
                f"生成总结失败 (invoke_model): {e}", command="messages_summary", e=e
            )
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
        img = await md_to_pic(md=summary, css_path=css_path, width=850)

        return img
    except Exception as e:
        if not isinstance(e, ImageGenerationException):
            logger.error(f"生成图片过程中发生意外错误: {e}", command="图片生成", e=e)
            raise ImageGenerationException(f"图片生成失败: {e!s}")
        else:
            raise


async def generate_help_image(_: str = "") -> bytes:
    """生成帮助文档图片

    Args:
        _: 原始的帮助文档文本，现在不再使用，保留参数仅为兼容性
    """
    if md_to_pic is None:
        raise ValueError("图片生成功能未启用或 htmlrender 未正确加载")

    try:
        styled_md = f"""
# 📖 群聊总结插件帮助文档

## 📋 核心功能

- `总结 <消息数量>` - 对当前群聊最近指定数量的消息进行总结
  - 示例: `总结 300`

- `总结 <消息数量> -p <风格>` - 指定总结的风格 (如：正式, 幽默, 锐评)
  - 示例: `总结 100 -p 幽默`

- `总结 <消息数量> @用户1 @用户2 ...` - 只总结被@用户的发言
  - 示例: `总结 500 @张三 @李四`

- `总结 <消息数量> <关键词>` - 只总结包含指定关键词的消息内容
  - 示例: `总结 200 关于项目进度`

- `总结 <消息数量> -p <风格> @用户1` - 指定风格并只总结被@用户的发言
  - 示例: `总结 300 -p 锐评 @张三`

- `总结 <消息数量> -p <风格> <关键词>` - 指定风格并只总结包含关键词的消息
  - 示例: `总结 200 -p 正式 关于项目`

- `总结 <数量> [-p 风格] [@用户] [关键词] -g <群号>` _(限 Superuser)_ - 远程总结指定群号的聊天记录
  - 示例: `总结 150 -g 12345678`
  - 示例: `总结 200 -p 锐评 @张三 -g 12345678`

## ⚙️ 配置管理 (统一入口: /总结配置)

- `/总结配置 查看 [-g 群号]` - 查看当前群（或指定群）的特定设置
  - 不带参数直接输入 `/总结配置` 效果相同
  - 示例: `/总结配置 查看` 或 `/总结配置` 或 `/总结配置 查看 -g 123456`

- `/总结配置 模型 列表` - 查看所有可用的 AI 模型列表
  - 示例: `/总结配置 模型 列表`

- `/总结配置 模型 切换 <Provider/Model>` _(仅限 Superuser)_ - 切换全局默认使用的 AI 模型
  - 示例: `/总结配置 模型 切换 DeepSeek/deepseek-chat`

- `/总结配置 模型 设置 <Provider/Model> [-g 群号]` _(仅限 Superuser)_ - 设置当前群（或指定群）使用的特定模型
  - 示例: `/总结配置 模型 设置 Gemini/gemini-pro` 或 `/总结配置 模型 设置 Gemini/gemini-pro -g 123456`

- `/总结配置 模型 移除 [-g 群号]` _(仅限 Superuser)_ - 移除当前群（或指定群）的特定模型设置，恢复使用全局模型
  - 示例: `/总结配置 模型 移除` 或 `/总结配置 模型 移除 -g 123456`

- `/总结配置 风格 设置 <风格名称> [-g 群号]` _(限 Admin/Superuser)_ - 设置当前群（或指定群）的默认总结风格
  - 示例: `/总结配置 风格 设置 简洁明了` 或 `/总结配置 风格 设置 简洁明了 -g 123456`

- `/总结配置 风格 移除 [-g 群号]` _(限 Admin/Superuser)_ - 移除当前群（或指定群）的默认风格设置
  - 示例: `/总结配置 风格 移除` 或 `/总结配置 风格 移除 -g 123456`

## ⏱️ 定时任务 (需 Admin/Superuser 权限)

- `定时总结 <时间> [消息数量] [-p 风格] [-g 群号 | -all]` - 设置定时发送总结 (HH:MM 或 HHMM 格式)
  - `-g` 指定群, `-all` 对所有群 (仅 Superuser)
  - 示例: `定时总结 22:30 500` (设置本群)
  - 示例: `定时总结 0800 -g 123456` (Superuser 设置指定群)

- `定时总结取消 [-g 群号 | -all]` - 取消定时总结任务
  - 示例: `定时总结取消` (取消本群)

## 🤖 AI 模型管理

- `总结模型列表` - 列出所有已配置可用的 AI 模型及其提供商

- `总结切换模型 <Provider/Model>` _(限 Superuser)_ - 切换全局默认使用的 AI 模型
  - 示例: `总结切换模型 DeepSeek/deepseek-chat`

- `总结密钥状态` _(限 Superuser)_ - 查看 API 密钥的状态信息
  - 显示每个密钥的成功/失败次数和可用状态

## 💏 系统管理 (仅限 Superuser)

- `总结调度状态 [-d]` - 查看所有定时任务的运行状态

- `总结健康检查` - 检查插件各组件的健康状况

- `总结系统修复` - 尝试自动修复检测到的系统问题

## ℹ️ 提示

- 消息数量范围: {base_config.get("SUMMARY_MIN_LENGTH", 1)} - {base_config.get("SUMMARY_MAX_LENGTH", 1000)}
- 冷却时间: {base_config.get("SUMMARY_COOL_DOWN", 60)} 秒
- 配置相关命令中的 `-g <群号>` 参数需要 Superuser 权限

---

_由 群聊总结插件 v{base_config.get("version", "2.0")} 生成_
        """.strip()

        css_file = "github-markdown-dark.css"
        theme = base_config.get("summary_theme", "vscode_dark")
        logger.debug(f"从配置中获取主题设置: {theme}", command="总结帮助")

        if theme == "light":
            css_file = "github-markdown-light.css"
        elif theme == "dark":
            css_file = "github-markdown-dark.css"
        elif theme == "vscode_dark":
            css_file = "vscode-dark.css"
        elif theme == "vscode_light":
            css_file = "vscode-light.css"

        css_path = (Path(__file__).parent.parent / "assert" / css_file).resolve()

        if not css_path.exists():
            logger.warning(
                f"CSS文件 {css_file} 不存在，将使用默认样式", command="总结帮助"
            )
            css_file = "github-markdown-dark.css"
            css_path = (Path(__file__).parent.parent / "assert" / css_file).resolve()

            if not css_path.exists():
                logger.warning(
                    "默认CSS文件也不存在，将不使用自定义CSS", command="总结帮助"
                )
                css_path = None

        logger.debug(
            f"使用主题 {theme or '默认'} 生成帮助文档图片，CSS路径: {css_path}",
            command="总结帮助",
        )

        if css_path and css_path.exists():
            img = await md_to_pic(md=styled_md, css_path=css_path, width=850)
        else:
            img = await md_to_pic(md=styled_md, width=850)
        return img

    except Exception as e:
        logger.error(f"生成帮助文档图片失败: {e}", command="总结帮助", e=e)
        raise ImageGenerationException(f"生成帮助文档图片失败: {e!s}")


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
