from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot_plugin_alconna import CommandResult, UniMessage
from nonebot_plugin_alconna.uniseg import Target

from zhenxun.services import group_settings_service

from .. import base_config
from ..config import GroupSettings


async def handle_group_specific_config(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    target: Target,
    cmd_result: CommandResult,
):
    """仅处理 `总结配置` (无参数) 的情况，用于显示当前群组的配置"""
    if isinstance(event, PrivateMessageEvent):
        await UniMessage.text(
            "请在群聊中使用此命令查看群组配置，或使用 -g <群号> 指定。"
        ).send(target)
        return
    await _show_settings(target, str(event.group_id))


async def _show_settings(target: Target, group_id_to_show: str):
    """内部函数：显示指定群组和全局的配置"""
    group_config: GroupSettings = await group_settings_service.get_all_for_plugin(
        group_id_to_show, "summary_group", parse_model=GroupSettings
    )

    plugin_model = base_config.get("SUMMARY_MODEL_NAME")
    plugin_style = base_config.get("SUMMARY_DEFAULT_STYLE")

    group_model = group_config.default_model_name
    group_style = group_config.default_style

    message = f"群聊 {group_id_to_show} 的总结配置：\n"
    message += "------\n"
    message += "生效配置:\n"
    message += f"  - 模型: {group_model or plugin_model or 'LLM核心服务默认'}"
    if group_model:
        message += " (本群特定)\n"
    else:
        message += " (全局默认)\n"

    message += f"  - 风格: {group_style or plugin_style or '无特定风格'}"
    if group_style:
        message += " (本群特定)\n"
    else:
        message += " (全局默认)\n"

    message += "------\n"
    message += "提示: 可使用 '总结配置 模型/风格 设置/移除 <值>' 来修改配置。"

    await UniMessage.text(message.strip()).send(target)
