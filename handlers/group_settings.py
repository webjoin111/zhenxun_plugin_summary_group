from arclet.alconna import Arparma
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import CommandResult, Match, UniMessage
from nonebot_plugin_alconna.uniseg import MsgTarget

from zhenxun.configs.config import Config
from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.level_user import LevelUser
from zhenxun.services.log import logger

from ..store import store
from .model_control import (
    find_model,
    handle_list_models,
    handle_switch_model,
    parse_provider_model_string,
)


async def _check_perms(bot: Bot, event: GroupMessageEvent, target: MsgTarget) -> bool:
    """检查基本权限和状态"""
    user_id_str = event.get_user_id()
    group_id = event.group_id
    bot_id = bot.self_id
    plugin_name = "summary_group"

    try:
        if not await BotConsole.get_bot_status(bot_id):
            return False
        if await BotConsole.is_block_plugin(bot_id, plugin_name):
            return False
        if await GroupConsole.is_block_plugin(group_id, plugin_name):
            await UniMessage.text("群聊总结功能在本群已被禁用。").send(target)
            return False
        if await BanConsole.is_ban(None, group_id):
            return False
        if await BanConsole.is_ban(user_id_str, group_id):
            return False

        required_level = Config.get_config("summary_group", "SUMMARY_ADMIN_LEVEL", 10)
        is_admin = await LevelUser.check_level(
            user_id_str, str(group_id), required_level
        )
        is_superuser = await SUPERUSER(bot, event)

        if not (is_admin or is_superuser):
            await UniMessage.text("需要管理员权限才能设置本群总结配置。").send(target)
            return False
        return True
    except Exception as e:
        logger.error(
            f"检查分群设置权限时出错: {e}",
            command="分群设置",
            session=user_id_str,
            group_id=group_id,
            e=e,
        )
        await UniMessage.text("检查权限时出错，请联系管理员。").send(target)
        return False


async def handle_set_group_model(
    bot: Bot,
    event: GroupMessageEvent,
    target: MsgTarget,
    provider_model_name: Match[str],
):
    """处理设置本群默认模型"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    model_name_str = provider_model_name.result

    prov_name, mod_name = parse_provider_model_string(model_name_str)
    if not prov_name or not mod_name:
        await UniMessage.text("模型名称格式错误，应为 'ProviderName/ModelName'。").send(
            target
        )
        return

    if find_model(prov_name, mod_name):
        if await store.set_group_setting(
            group_id_str, "default_model_name", model_name_str
        ):
            logger.info(
                f"群 {group_id_str} 设置默认模型为: {model_name_str} by {event.get_user_id()}"
            )
            await UniMessage.text(f"已将本群默认总结模型设置为：{model_name_str}").send(
                target
            )
        else:
            await UniMessage.text("设置失败，请检查日志。").send(target)
    else:
        await UniMessage.text(
            f"错误：找不到模型 '{model_name_str}'，请检查名称是否正确。"
        ).send(target)


async def handle_set_group_style(
    bot: Bot, event: GroupMessageEvent, target: MsgTarget, style: Match[str]
):
    """处理设置本群默认风格"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    style_name = style.result.strip()

    if not style_name:
        await UniMessage.text("风格名称不能为空。").send(target)
        return

    if await store.set_group_setting(group_id_str, "default_style", style_name):
        logger.info(
            f"群 {group_id_str} 设置默认风格为: '{style_name}' by {event.get_user_id()}"
        )
        await UniMessage.text(f"已将本群默认总结风格设置为：'{style_name}'").send(
            target
        )
    else:
        await UniMessage.text("设置失败，请检查日志。").send(target)


async def handle_remove_group_model(
    bot: Bot, event: GroupMessageEvent, target: MsgTarget
):
    """处理移除本群默认模型"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    if await store.remove_group_setting(group_id_str, "default_model_name"):
        logger.info(f"群 {group_id_str} 移除了默认模型设置 by {event.get_user_id()}")
        await UniMessage.text("已移除本群的默认总结模型设置，将使用全局设置。").send(
            target
        )
    else:
        await UniMessage.text("移除失败或本群未设置默认模型。").send(target)


async def handle_remove_group_style(
    bot: Bot, event: GroupMessageEvent, target: MsgTarget
):
    """处理移除本群默认风格"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    if await store.remove_group_setting(group_id_str, "default_style"):
        logger.info(f"群 {group_id_str} 移除了默认风格设置 by {event.get_user_id()}")
        await UniMessage.text("已移除本群的默认总结风格设置。").send(target)
    else:
        await UniMessage.text("移除失败或本群未设置默认风格。").send(target)


async def _check_group_status(bot: Bot, target: MsgTarget, group_id: str) -> bool:
    """检查 Bot 和目标群组的基本状态（是否屏蔽插件、是否被ban）"""
    try:
        if not await BotConsole.get_bot_status(bot.self_id):
            logger.debug(f"Bot {bot.self_id} 未激活")
            return False
        if await BotConsole.is_block_plugin(bot.self_id, "summary_group"):
            logger.debug(f"Bot {bot.self_id} 屏蔽了 summary_group")
            return False
        if await GroupConsole.is_block_plugin(group_id, "summary_group"):
            msg = "群聊总结功能在本群已被禁用。"
            if target.id == group_id and not target.private:
                await UniMessage.text(msg).send(target)
            logger.debug(f"群 {group_id} 屏蔽了 summary_group")
            return False
        if await BanConsole.is_ban(None, group_id):
            logger.debug(f"群 {group_id} 被封禁")
            return False
        return True
    except Exception as e:
        logger.error(f"检查群组 {group_id} 状态时出错: {e}", e=e)
        await UniMessage.text(f"检查群组 {group_id} 状态时出错。").send(target)
        return False


async def _switch_global_model(
    target: MsgTarget, provider_model_name: str, operator_id: str
):
    """内部函数：切换全局模型"""
    success, message = handle_switch_model(provider_model_name)
    if success:
        Config.set_config(
            "summary_group",
            "CURRENT_ACTIVE_MODEL_NAME",
            provider_model_name,
            auto_save=True,
        )
        logger.info(f"全局 AI 模型已切换为: {provider_model_name} by {operator_id}")
        await UniMessage.text(f"已成功切换全局激活模型为: {provider_model_name}").send(
            target
        )
    else:
        await UniMessage.text(message).send(target)


async def _set_group_model(
    target: MsgTarget, group_id: str, model_name_str: str, operator_id: str
):
    """内部函数：设置分群模型"""
    prov_name, mod_name = parse_provider_model_string(model_name_str)
    if not prov_name or not mod_name:
        await UniMessage.text("模型名称格式错误，应为 'ProviderName/ModelName'。").send(
            target
        )
        return

    if find_model(prov_name, mod_name):
        if await store.set_group_setting(
            group_id, "default_model_name", model_name_str
        ):
            logger.info(
                f"群 {group_id} 设置默认模型为: {model_name_str} by {operator_id}"
            )
            await UniMessage.text(
                f"已将群聊 {group_id} 的默认总结模型设置为：{model_name_str}"
            ).send(target)
        else:
            await UniMessage.text("设置失败，请检查日志。").send(target)
    else:
        await UniMessage.text(
            f"错误：找不到模型 '{model_name_str}'，请检查名称是否正确。"
        ).send(target)


async def _remove_group_model(target: MsgTarget, group_id: str, operator_id: str):
    """内部函数：移除分群模型设置"""
    if await store.remove_group_setting(group_id, "default_model_name"):
        logger.info(f"群 {group_id} 移除了默认模型设置 by {operator_id}")
        await UniMessage.text(
            f"已移除群聊 {group_id} 的默认总结模型设置，将使用全局设置。"
        ).send(target)
    else:
        await UniMessage.text(f"移除失败或群聊 {group_id} 未设置默认模型。").send(
            target
        )


async def _set_group_style(
    target: MsgTarget, group_id: str, style_name: str, operator_id: str
):
    """内部函数：设置分群风格"""
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
    """内部函数：移除分群风格设置"""
    if await store.remove_group_setting(group_id, "default_style"):
        logger.info(f"群 {group_id} 移除了默认风格设置 by {operator_id}")
        await UniMessage.text(f"已移除群聊 {group_id} 的默认总结风格设置。").send(
            target
        )
    else:
        await UniMessage.text(f"移除失败或群聊 {group_id} 未设置默认风格。").send(
            target
        )


async def _show_settings(target: MsgTarget, group_id_to_show: str):
    """内部函数：显示指定群组的设置"""
    settings = store.get_all_group_settings(group_id_to_show)
    global_active_model = Config.get_config(
        "summary_group", "CURRENT_ACTIVE_MODEL_NAME"
    )

    message = f"群聊 {group_id_to_show} 的总结配置：\n"
    has_specific_settings = False

    if settings:
        model = settings.get("default_model_name")
        style = settings.get("default_style")

        if model:
            message += f"- 特定默认模型: {model}\n"
            has_specific_settings = True
        if style:
            message += f"- 特定默认风格: '{style}'\n"
            has_specific_settings = True

    if not has_specific_settings:
        message += "- 未设置特定配置，将使用全局设置。\n"

    message += f"\n当前全局激活模型: {global_active_model or '未配置'}"

    await UniMessage.text(message.strip()).send(target)


async def handle_show_group_settings(
    bot: Bot, event: GroupMessageEvent, target: MsgTarget
):
    """处理查看本群设置"""
    user_id_str = event.get_user_id()
    group_id_str = str(event.group_id)
    bot_id = bot.self_id
    plugin_name = "summary_group"
    try:
        if not await BotConsole.get_bot_status(bot_id):
            return
        if await BotConsole.is_block_plugin(bot_id, plugin_name):
            return
        if await GroupConsole.is_block_plugin(int(group_id_str), plugin_name):
            await UniMessage.text("群聊总结功能在本群已被禁用。").send(target)
            return
        if await BanConsole.is_ban(None, int(group_id_str)):
            return
    except Exception as e:
        logger.error(
            f"检查查看分群设置权限时出错: {e}",
            command="分群设置查看",
            session=user_id_str,
            group_id=group_id_str,
            e=e,
        )
        await UniMessage.text("检查权限时出错。").send(target)
        return

    await _show_settings(target, group_id_str)


async def handle_summary_config(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    cmd_result: CommandResult,
):
    """处理 '/总结配置' 命令"""
    user_id_str = event.get_user_id()
    originating_group_id = (
        event.group_id if isinstance(event, GroupMessageEvent) else None
    )
    is_superuser = await SUPERUSER(bot, event)

    arp: Arparma | None = cmd_result.result

    if not arp or not arp.matched:
        if originating_group_id:
            await _show_settings(target, str(originating_group_id))
        else:
            await UniMessage.text(
                "请在群聊中使用此命令查看或配置群组设置，或使用 '总结配置 模型 列表/切换'。"
            ).send(target)
        return

    target_group_id_from_g: int | None = arp.query[int]("g.target_group_id")
    if target_group_id_from_g and not is_superuser:
        await UniMessage.text("只有超级用户才能使用 -g 参数指定群组。").send(target)
        return

    target_group_id_str: str | None = None
    if target_group_id_from_g:
        target_group_id_str = str(target_group_id_from_g)
    elif originating_group_id:
        target_group_id_str = str(originating_group_id)

    if arp.find("模型"):
        if arp.find("模型.列表"):
            current_active = Config.get_config(
                "summary_group", "CURRENT_ACTIVE_MODEL_NAME"
            )
            list_msg = handle_list_models(current_active)
            await UniMessage.text(list_msg).send(target)

        elif arp.find("模型.切换"):
            if not is_superuser:
                await UniMessage.text("只有超级用户才能切换全局使用的模型。").send(
                    target
                )
                return
            provider_model = arp.query[str]("模型.切换.provider_model")
            await _switch_global_model(target, provider_model, user_id_str)

        elif arp.find("模型.设置"):
            if not is_superuser:
                await UniMessage.text("只有超级用户才能设置群组的默认模型。").send(
                    target
                )
                return
            if not target_group_id_str:
                await UniMessage.text(
                    "请在群内使用或使用 -g <群号> 指定要设置的群组。"
                ).send(target)
                return
            if not await _check_group_status(bot, target, target_group_id_str):
                return
            provider_model = arp.query[str]("模型.设置.provider_model")
            await _set_group_model(
                target, target_group_id_str, provider_model, user_id_str
            )

        elif arp.find("模型.移除"):
            if not is_superuser:
                await UniMessage.text("只有超级用户才能移除群组的默认模型设置。").send(
                    target
                )
                return
            if not target_group_id_str:
                await UniMessage.text(
                    "请在群内使用或使用 -g <群号> 指定要移除设置的群组。"
                ).send(target)
                return
            if not await _check_group_status(bot, target, target_group_id_str):
                return
            await _remove_group_model(target, target_group_id_str, user_id_str)

        else:
            await UniMessage.text(
                "模型操作无效，请使用 '列表', '切换', '设置', '移除'。"
            ).send(target)

    elif arp.find("风格"):
        can_proceed = False
        required_level = Config.get_config("summary_group", "SUMMARY_ADMIN_LEVEL", 10)
        if is_superuser:
            can_proceed = True
        elif originating_group_id and isinstance(event, GroupMessageEvent):
            if await LevelUser.check_level(
                user_id_str, str(originating_group_id), required_level
            ):
                can_proceed = True

        if not can_proceed:
            await UniMessage.text("需要管理员权限才能设置或移除本群风格。").send(target)
            return

        if not target_group_id_str:
            await UniMessage.text(
                "请在群内使用或使用 -g <群号> 指定要操作的群组。"
            ).send(target)
            return
        if not await _check_group_status(bot, target, target_group_id_str):
            return

        if arp.find("风格.设置"):
            style_name = arp.query[str]("风格.设置.style_name")
            await _set_group_style(target, target_group_id_str, style_name, user_id_str)
        elif arp.find("风格.移除"):
            await _remove_group_style(target, target_group_id_str, user_id_str)
        else:
            await UniMessage.text("风格操作无效，请使用 '设置', '移除'。").send(target)

    elif arp.find("查看"):
        if not target_group_id_str:
            await UniMessage.text(
                "请在群内使用或使用 -g <群号> 指定要查看的群组。"
            ).send(target)
            return
        if not await _check_group_status(bot, target, target_group_id_str):
            return
        await _show_settings(target, target_group_id_str)

    else:
        if target_group_id_str:
            if not await _check_group_status(bot, target, target_group_id_str):
                return
            await _show_settings(target, target_group_id_str)
        elif not originating_group_id:
            await UniMessage.text(
                "无效命令。请使用 '总结配置 查看/模型/风格...' 或在群聊中使用。"
            ).send(target)
        else:
            await _show_settings(target, target_group_id_str)
