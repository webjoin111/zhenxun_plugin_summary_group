from arclet.alconna import Arparma
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import CommandResult, UniMessage
from nonebot_plugin_alconna.uniseg import MsgTarget

from zhenxun.configs.config import Config
from zhenxun.models.level_user import LevelUser
from zhenxun.services.llm import list_available_models
from zhenxun.services.log import logger

from .. import base_config
from ..store import store


async def handle_global_model_setting(
    operator_id: str, target: MsgTarget, cmd_result: CommandResult
):
    """处理 /总结模型 命令"""
    arp: Arparma | None = cmd_result.result
    if not arp or not arp.matched:
        return

    if arp.find("列表"):
        plugin_default_model = base_config.get("SUMMARY_MODEL_NAME")
        available_models = list_available_models()
        if not available_models:
            await UniMessage.text("尚未配置任何 AI 模型。").send(target)
            return

        msg = "可用 AI 模型列表 (格式: ProviderName/ModelName)：\n"
        for model in available_models:
            msg += f"  - {model['full_name']}"
            if model["full_name"] == plugin_default_model:
                msg += " [当前插件默认]"
            msg += "\n"
        msg += "\n使用 '总结模型 设置 <名称>' 切换本插件默认模型。"
        await UniMessage.text(msg.strip()).send(target)

    elif "设置" in arp.subcommands:
        sub = arp.subcommands["设置"]
        provider_model = sub.args["provider_model"]
        available_model_names = [m["full_name"] for m in list_available_models()]
        if provider_model not in available_model_names:
            await UniMessage.text(
                f"切换失败，模型 '{provider_model}' 不存在或无效。"
            ).send(target)
            return

        Config.set_config(
            "summary_group", "SUMMARY_MODEL_NAME", provider_model, auto_save=True
        )
        logger.info(f"群聊总结插件默认模型已切换为: {provider_model} by {operator_id}")
        await UniMessage.text(f"已成功切换本插件默认模型为: {provider_model}").send(
            target
        )


async def handle_global_style_setting(
    operator_id: str, target: MsgTarget, cmd_result: CommandResult
):
    """处理 /总结风格 命令"""
    arp: Arparma | None = cmd_result.result
    if not arp or not arp.matched:
        return

    if "设置" in arp.subcommands:
        sub = arp.subcommands["设置"]
        style_name = sub.args["style_name"].strip()
        if not style_name:
            await UniMessage.text("风格名称不能为空。").send(target)
            return
        Config.set_config(
            "summary_group", "SUMMARY_DEFAULT_STYLE", style_name, auto_save=True
        )
        logger.info(
            f"群聊总结插件全局默认风格已设置为: '{style_name}' by {operator_id}"
        )
        await UniMessage.text(f"已设置全局默认总结风格为：'{style_name}'").send(target)
    elif "移除" in arp.subcommands:
        Config.set_config(
            "summary_group", "SUMMARY_DEFAULT_STYLE", None, auto_save=True
        )
        logger.info(f"群聊总结插件全局默认风格已移除 by {operator_id}")
        await UniMessage.text("已移除全局默认总结风格。").send(target)


async def handle_group_specific_config(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    cmd_result: CommandResult,
):
    """处理 /总结配置 命令 (分群配置)"""
    user_id_str = event.get_user_id()
    is_superuser = await SUPERUSER(bot, event)
    arp: Arparma | None = cmd_result.result

    target_group_id_str: str | None = None
    if arp and (gid := arp.query[int]("g.target_group_id")):
        if not is_superuser:
            await UniMessage.text("只有超级用户才能使用 -g 参数指定群组。").send(target)
            return
        target_group_id_str = str(gid)
    elif isinstance(event, GroupMessageEvent):
        target_group_id_str = str(event.group_id)

    if not arp or not arp.matched:
        if target_group_id_str:
            await _show_settings(target, target_group_id_str)
        else:
            await UniMessage.text(
                "请在群聊中使用此命令查看群组配置，或使用 -g <群号> 指定。"
            ).send(target)
        return

    if not target_group_id_str:
        await UniMessage.text("请在群聊中操作或使用 -g <群号> 指定群组。").send(target)
        return

    can_set_model = is_superuser
    can_set_style = is_superuser
    if not is_superuser:
        required_level = base_config.get("SUMMARY_ADMIN_LEVEL", 10)
        is_admin = await LevelUser.check_level(
            user_id_str, target_group_id_str, required_level
        )
        if is_admin:
            can_set_style = True

    if "模型" in arp.subcommands:
        if not can_set_model:
            await UniMessage.text("需要超级用户权限才能为群组设置特定模型。").send(
                target
            )
            return

        model_arp = arp.subcommands["模型"]
        if "设置" in model_arp.subcommands:
            model_name = model_arp.subcommands["设置"].args["provider_model"]
            await _set_group_model(target, target_group_id_str, model_name, user_id_str)
        elif "移除" in model_arp.subcommands:
            await _remove_group_model(target, target_group_id_str, user_id_str)

    elif "风格" in arp.subcommands:
        if not can_set_style:
            await UniMessage.text("需要管理员权限才能设置或移除本群风格。").send(target)
            return

        style_arp = arp.subcommands["风格"]
        if "设置" in style_arp.subcommands:
            style_name = style_arp.subcommands["设置"].args["style_name"]
            await _set_group_style(target, target_group_id_str, style_name, user_id_str)
        elif "移除" in style_arp.subcommands:
            await _remove_group_style(target, target_group_id_str, user_id_str)
    else:
        await _show_settings(target, target_group_id_str)


async def _show_settings(target: MsgTarget, group_id_to_show: str):
    """内部函数：显示指定群组和全局的配置"""
    group_settings = store.get_all_group_settings(group_id_to_show)
    plugin_model = base_config.get("SUMMARY_MODEL_NAME")
    plugin_style = base_config.get("SUMMARY_DEFAULT_STYLE")

    group_model = group_settings.get("default_model_name") if group_settings else None
    group_style = group_settings.get("default_style") if group_settings else None

    message = f"群聊 {group_id_to_show} 的总结配置：\n"
    message += "------\n"
    message += "生效配置:\n"
    message += f"  - 模型: {group_model or plugin_model or '未配置'}"
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
    message += "详细设置:\n"
    message += f"  - 全局模型: {plugin_model or '未设置'}\n"
    message += f"  - 全局风格: {plugin_style or '未设置'}\n"
    message += f"  - 本群模型: {group_model or '未设置'}\n"
    message += f"  - 本群风格: {group_style or '未设置'}\n"

    await UniMessage.text(message.strip()).send(target)


async def _set_group_model(
    target: MsgTarget, group_id: str, model_name: str, operator_id: str
):
    available_model_names = [m["full_name"] for m in list_available_models()]
    if model_name not in available_model_names:
        await UniMessage.text(f"设置失败，模型 '{model_name}' 不存在或无效。").send(
            target
        )
        return
    if await store.set_group_setting(group_id, "default_model_name", model_name):
        logger.info(f"群 {group_id} 设置默认模型为: '{model_name}' by {operator_id}")
        await UniMessage.text(
            f"已将群聊 {group_id} 的默认总结模型设置为：'{model_name}'"
        ).send(target)
    else:
        await UniMessage.text("设置失败，请检查日志。").send(target)


async def _remove_group_model(target: MsgTarget, group_id: str, operator_id: str):
    if await store.remove_group_setting(group_id, "default_model_name"):
        logger.info(f"群 {group_id} 移除了默认模型设置 by {operator_id}")
        await UniMessage.text(f"已移除群聊 {group_id} 的默认总结模型设置。").send(
            target
        )
    else:
        await UniMessage.text(f"移除失败或群聊 {group_id} 未设置默认模型。").send(
            target
        )


async def _set_group_style(
    target: MsgTarget, group_id: str, style_name: str, operator_id: str
):
    style_name = style_name.strip()
    if not style_name:
        await UniMessage.text("风格名称不能为空。").send(target)
        return
    if await store.set_group_setting(group_id, "default_style", style_name):
        logger.info(f"群 {group_id} 设置默认风格为: '{style_name}' by {operator_id}")
        await UniMessage.text(
            f"已将群聊 {group_id} 的默认总结风格设置为：'{style_name}'"
        ).send(target)
    else:
        await UniMessage.text("设置失败，请检查日志。").send(target)


async def _remove_group_style(target: MsgTarget, group_id: str, operator_id: str):
    if await store.remove_group_setting(group_id, "default_style"):
        logger.info(f"群 {group_id} 移除了默认风格设置 by {operator_id}")
        await UniMessage.text(f"已移除群聊 {group_id} 的默认总结风格设置。").send(
            target
        )
    else:
        await UniMessage.text(f"移除失败或群聊 {group_id} 未设置默认风格。").send(
            target
        )
