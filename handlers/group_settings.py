# 不再需要 Optional 导入，使用 | None 语法
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Match, UniMessage, CommandResult
from nonebot_plugin_alconna.uniseg import MsgTarget
from arclet.alconna import Arparma

from zhenxun.configs.config import Config
from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.services.log import logger
from zhenxun.utils.rules import admin_check

from ..store import Store
from .model_control import find_model, handle_list_models, handle_switch_model, parse_provider_model_string

store = Store()

async def _check_perms(bot: Bot, event: GroupMessageEvent, target: MsgTarget) -> bool:
    """检查基本权限和状态"""
    user_id_str = event.get_user_id()
    group_id = event.group_id
    bot_id = bot.self_id
    plugin_name = "summary_group"  # 或特定的设置命令名称

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
        # 检查是否为管理员或超级用户
        is_admin = await admin_check("summary_group", "SUMMARY_ADMIN_LEVEL")(bot, event)
        is_superuser = await SUPERUSER(bot, event)
        if not (is_admin or is_superuser):
            await UniMessage.text("需要管理员权限才能设置本群总结配置。").send(target)
            return False
        return True
    except Exception as e:
        logger.error(f"检查分群设置权限时出错: {e}", command="分群设置", session=user_id_str, group_id=group_id, e=e)
        await UniMessage.text("检查权限时出错，请联系管理员。").send(target)
        return False


async def handle_set_group_model(bot: Bot, event: GroupMessageEvent, target: MsgTarget, provider_model_name: Match[str]):
    """处理设置本群默认模型"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    model_name_str = provider_model_name.result

    prov_name, mod_name = parse_provider_model_string(model_name_str)
    if not prov_name or not mod_name:
        await UniMessage.text("模型名称格式错误，应为 'ProviderName/ModelName'。").send(target)
        return

    if find_model(prov_name, mod_name):
        if store.set_group_setting(group_id_str, "default_model_name", model_name_str):
            logger.info(f"群 {group_id_str} 设置默认模型为: {model_name_str} by {event.get_user_id()}")
            await UniMessage.text(f"已将本群默认总结模型设置为：{model_name_str}").send(target)
        else:
            await UniMessage.text("设置失败，请检查日志。").send(target)
    else:
        await UniMessage.text(f"错误：找不到模型 '{model_name_str}'，请检查名称是否正确。").send(target)


async def handle_set_group_style(bot: Bot, event: GroupMessageEvent, target: MsgTarget, style: Match[str]):
    """处理设置本群默认风格"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    style_name = style.result.strip()

    if not style_name:
        await UniMessage.text("风格名称不能为空。").send(target)
        return

    if store.set_group_setting(group_id_str, "default_style", style_name):
        logger.info(f"群 {group_id_str} 设置默认风格为: '{style_name}' by {event.get_user_id()}")
        await UniMessage.text(f"已将本群默认总结风格设置为：'{style_name}'").send(target)
    else:
        await UniMessage.text("设置失败，请检查日志。").send(target)

async def handle_remove_group_model(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """处理移除本群默认模型"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    if store.remove_group_setting(group_id_str, "default_model_name"):
        logger.info(f"群 {group_id_str} 移除了默认模型设置 by {event.get_user_id()}")
        await UniMessage.text("已移除本群的默认总结模型设置，将使用全局设置。").send(target)
    else:
        # remove_group_setting 在 key 不存在时也返回 True，所以这里理论上不会执行
        await UniMessage.text("移除失败或本群未设置默认模型。").send(target)


async def handle_remove_group_style(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """处理移除本群默认风格"""
    if not await _check_perms(bot, event, target):
        return

    group_id_str = str(event.group_id)
    if store.remove_group_setting(group_id_str, "default_style"):
        logger.info(f"群 {group_id_str} 移除了默认风格设置 by {event.get_user_id()}")
        await UniMessage.text("已移除本群的默认总结风格设置。").send(target)
    else:
        await UniMessage.text("移除失败或本群未设置默认风格。").send(target)


# --- 辅助函数 ---

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
             # 只有当回复目标就是该群时才发送提示
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


async def _switch_global_model(target: MsgTarget, provider_model_name: str, operator_id: str):
    """内部函数：切换全局模型"""
    success, message = handle_switch_model(provider_model_name) # 验证模型有效性
    if success:
        Config.set_config("summary_group", "CURRENT_ACTIVE_MODEL_NAME", provider_model_name, auto_save=True)
        logger.info(f"全局 AI 模型已切换为: {provider_model_name} by {operator_id}")
        await UniMessage.text(f"已成功切换全局激活模型为: {provider_model_name}").send(target)
    else:
        await UniMessage.text(message).send(target) # 发送验证失败的消息

async def _set_group_model(target: MsgTarget, group_id: str, model_name_str: str, operator_id: str):
    """内部函数：设置分群模型"""
    prov_name, mod_name = parse_provider_model_string(model_name_str)
    if not prov_name or not mod_name:
        await UniMessage.text("模型名称格式错误，应为 'ProviderName/ModelName'。").send(target)
        return

    if find_model(prov_name, mod_name):
        if store.set_group_setting(group_id, "default_model_name", model_name_str):
            logger.info(f"群 {group_id} 设置默认模型为: {model_name_str} by {operator_id}")
            await UniMessage.text(f"已将群聊 {group_id} 的默认总结模型设置为：{model_name_str}").send(target)
        else:
            await UniMessage.text("设置失败，请检查日志。").send(target)
    else:
        await UniMessage.text(f"错误：找不到模型 '{model_name_str}'，请检查名称是否正确。").send(target)

async def _remove_group_model(target: MsgTarget, group_id: str, operator_id: str):
    """内部函数：移除分群模型设置"""
    if store.remove_group_setting(group_id, "default_model_name"):
        logger.info(f"群 {group_id} 移除了默认模型设置 by {operator_id}")
        await UniMessage.text(f"已移除群聊 {group_id} 的默认总结模型设置，将使用全局设置。").send(target)
    else:
        await UniMessage.text(f"移除失败或群聊 {group_id} 未设置默认模型。").send(target)

async def _set_group_style(target: MsgTarget, group_id: str, style_name: str, operator_id: str):
    """内部函数：设置分群风格"""
    style_name = style_name.strip()
    if not style_name:
        await UniMessage.text("风格名称不能为空。").send(target)
        return

    if store.set_group_setting(group_id, "default_style", style_name):
        logger.info(f"群 {group_id} 设置默认风格为: '{style_name}' by {operator_id}")
        await UniMessage.text(f"已将群聊 {group_id} 的默认总结风格设置为：'{style_name}'").send(target)
    else:
        await UniMessage.text("设置失败，请检查日志。").send(target)

async def _remove_group_style(target: MsgTarget, group_id: str, operator_id: str):
    """内部函数：移除分群风格设置"""
    if store.remove_group_setting(group_id, "default_style"):
        logger.info(f"群 {group_id} 移除了默认风格设置 by {operator_id}")
        await UniMessage.text(f"已移除群聊 {group_id} 的默认总结风格设置。").send(target)
    else:
        await UniMessage.text(f"移除失败或群聊 {group_id} 未设置默认风格。").send(target)

async def _show_settings(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget, group_id_to_show: str):
    """内部函数：显示指定群组的设置"""
    # 注意：这里的 bot 和 event 参数只是为了保持函数签名一致，实际上并不使用
    settings = store.get_all_group_settings(group_id_to_show)
    global_active_model = Config.get_config("summary_group", "CURRENT_ACTIVE_MODEL_NAME")

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
    # 可以考虑显示全局默认风格（如果需要）

    await UniMessage.text(message.strip()).send(target)


async def handle_show_group_settings(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """处理查看本群设置"""
    # 权限检查可以放宽，普通成员也能看
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
        # if await BanConsole.is_ban(user_id_str, int(group_id_str)): # 查看设置通常不需要检查用户ban
    except Exception as e:
        logger.error(f"检查查看分群设置权限时出错: {e}", command="分群设置查看", session=user_id_str, group_id=group_id_str, e=e)
        await UniMessage.text("检查权限时出错。").send(target)
        return

    await _show_settings(bot, event, target, group_id_str)


async def handle_summary_config(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget, cmd_result: CommandResult):
    """处理 '/总结配置' 命令"""
    user_id_str = event.get_user_id()
    originating_group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    is_superuser = await SUPERUSER(bot, event)

    arp: Arparma | None = cmd_result.result

    if not arp or not arp.matched:
        # 默认或错误时显示当前群设置（如果不在群聊中，提示错误）
        if originating_group_id:
            await _show_settings(bot, event, target, str(originating_group_id))
        else:
            await UniMessage.text("请在群聊中使用此命令查看或配置群组设置，或使用 '总结配置 模型 列表/切换'。").send(target)
        return

    # --- 解析全局 -g 参数 ---
    target_group_id_from_g: int | None = arp.query[int]("g.target_group_id")
    if target_group_id_from_g and not is_superuser:
        await UniMessage.text("只有超级用户才能使用 -g 参数指定群组。").send(target)
        return

    # --- 确定操作目标群组 ID ---
    # 优先使用 -g 参数指定的群组（如果用户是 Superuser）
    # 否则使用命令发起的群组（如果存在）
    # 对于全局操作（列表、切换），target_group_id 可以是 None
    target_group_id_str: str | None = None
    if target_group_id_from_g:
        target_group_id_str = str(target_group_id_from_g)
    elif originating_group_id:
        target_group_id_str = str(originating_group_id)
    # else: target_group_id_str is None (私聊且未使用 -g)

    # --- 模型子命令处理 ---
    if model_cmd := arp.query[Arparma]("模型"):
        if model_cmd.find("列表"):
            # 列出模型，无需权限
            current_active = Config.get_config("summary_group", "CURRENT_ACTIVE_MODEL_NAME")
            list_msg = handle_list_models(current_active) # 使用 model_control 中的函数
            await UniMessage.text(list_msg).send(target)

        elif switch_cmd := model_cmd.query[Arparma]("切换"):
            # 切换全局模型，需要 Superuser
            if not is_superuser:
                await UniMessage.text("只有超级用户才能切换全局使用的模型。").send(target)
                return
            provider_model = switch_cmd.query[str]("provider_model")
            await _switch_global_model(target, provider_model, user_id_str)

        elif set_cmd := model_cmd.query[Arparma]("设置"):
            # 设置分群模型，需要 Superuser
            if not is_superuser:
                await UniMessage.text("只有超级用户才能设置群组的默认模型。").send(target)
                return
            if not target_group_id_str:
                 await UniMessage.text("请在群内使用或使用 -g <群号> 指定要设置的群组。").send(target)
                 return
            # --- 权限检查（Bot、群组状态等） ---
            if not await _check_group_status(bot, target, target_group_id_str):
                 return
            provider_model = set_cmd.query[str]("provider_model")
            await _set_group_model(target, target_group_id_str, provider_model, user_id_str)

        elif model_cmd.find("移除"):
            # 移除分群模型，需要 Superuser
            if not is_superuser:
                await UniMessage.text("只有超级用户才能移除群组的默认模型设置。").send(target)
                return
            if not target_group_id_str:
                 await UniMessage.text("请在群内使用或使用 -g <群号> 指定要移除设置的群组。").send(target)
                 return
            # --- 权限检查 ---
            if not await _check_group_status(bot, target, target_group_id_str):
                 return
            await _remove_group_model(target, target_group_id_str, user_id_str)

        else:
             await UniMessage.text("模型操作无效，请使用 '列表', '切换', '设置', '移除'。").send(target)

    # --- 风格子命令处理 ---
    elif style_cmd := arp.query[Arparma]("风格"):
        # 设置和移除都需要 Admin 或 Superuser，且需要目标群组
        is_admin = False
        if originating_group_id: # 检查发起群的管理员权限
            is_admin = await admin_check("summary_group", "SUMMARY_ADMIN_LEVEL")(bot, event)

        if not target_group_id_str:
            await UniMessage.text("请在群内使用或使用 -g <群号> 指定要操作的群组。").send(target)
            return
        # 检查权限
        if not (is_admin or is_superuser):
            await UniMessage.text("需要管理员权限才能设置或移除本群风格。").send(target)
            return
        # 检查目标群组状态
        if not await _check_group_status(bot, target, target_group_id_str):
             return

        if set_cmd := style_cmd.query[Arparma]("设置"):
            style_name = set_cmd.query[str]("style_name")
            await _set_group_style(target, target_group_id_str, style_name, user_id_str)
        elif style_cmd.find("移除"):
            await _remove_group_style(target, target_group_id_str, user_id_str)
        else:
             await UniMessage.text("风格操作无效，请使用 '设置', '移除'。").send(target)

    # --- 查看子命令处理 ---
    elif arp.find("查看"):
        if not target_group_id_str:
             await UniMessage.text("请在群内使用或使用 -g <群号> 指定要查看的群组。").send(target)
             return
        # 检查目标群组状态
        if not await _check_group_status(bot, target, target_group_id_str):
             return
        await _show_settings(bot, event, target, target_group_id_str) # 调用查看逻辑

    else:
        # 主命令不带子命令，且带了 -g 参数 (Superuser)
        if target_group_id_str:
            if not await _check_group_status(bot, target, target_group_id_str):
                return
            await _show_settings(bot, event, target, target_group_id_str)
        # 如果在群聊中且不带 -g，已经在函数开头处理了
        elif not originating_group_id: # 在私聊中，不带 -g 且无子命令
             await UniMessage.text("无效命令。请使用 '总结配置 查看/模型/风格...' 或在群聊中使用。").send(target)
