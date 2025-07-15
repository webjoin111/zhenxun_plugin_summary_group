from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import CommandResult
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.services.log import logger
from zhenxun.services.scheduler import scheduler_manager


def parse_time(time_str: str) -> tuple[int, int]:
    logger.debug(f"parse_time called with input: {time_str!r}")

    if not isinstance(time_str, str):
        raise ValueError(f"输入必须是字符串，而不是 {type(time_str)}")

    time_str = time_str.strip()
    if not time_str:
        raise ValueError("时间字符串不能为空")

    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError("冒号格式必须为 HH:MM")

        hour_str, minute_str = parts

        if not (hour_str.isdigit() and minute_str.isdigit()):
            raise ValueError("HH:MM 格式中包含非数字或空部分")

        try:
            hour = int(hour_str)
            minute = int(minute_str)
        except ValueError:
            raise ValueError("无法将时间部分转换为数字")

    elif time_str.isdigit():
        if len(time_str) == 4:
            try:
                hour = int(time_str[:2])
                minute = int(time_str[2:])
            except ValueError:
                raise ValueError("HHMM 格式解析失败")
        elif len(time_str) == 3:
            try:
                hour = int(time_str[0])
                minute = int(time_str[1:])
            except ValueError:
                raise ValueError("HMM 格式解析失败")
        elif len(time_str) <= 2:
            try:
                hour = int(time_str)
                minute = 0
            except ValueError:
                raise ValueError("H/HH 格式解析失败")
        else:
            raise ValueError("纯数字格式必须为 HHMM、HMM 或 H/HH")
    else:
        raise ValueError("时间格式无法识别，请使用 HH:MM 或 HHMM")

    if not (0 <= hour <= 23):
        raise ValueError(f"小时 {hour} 超出有效范围 (0-23)")
    if not (0 <= minute <= 59):
        raise ValueError(f"分钟 {minute} 超出有效范围 (0-59)")

    logger.debug(f"parse_time successful: {hour:02d}:{minute:02d}")
    return hour, minute


async def handle_summary_set(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    time_tuple: tuple[int, int],
    least_count: int,
    style: str | None,
    target: MsgTarget,
):
    hour, minute = time_tuple
    arp = result.result
    is_superuser = await SUPERUSER(bot, event)

    target_group_id_match = arp.query("g.target_group_id")
    all_enabled = arp.find("all")

    job_kwargs = {
        "least_message_count": least_count,
        "style": style,
    }

    if all_enabled:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能对所有群组进行操作。").send(
                target
            )
            return

        schedule = await scheduler_manager.add_daily_task(
            plugin_name="summary_group",
            group_id=scheduler_manager.ALL_GROUPS,
            hour=hour,
            minute=minute,
            job_kwargs=job_kwargs,
            bot_id=bot.self_id,
        )
        msg = (
            f"已为所有群组设置全局定时总结，时间：每天 {hour:02d}:{minute:02d}。"
            if schedule
            else "设置全局定时总结失败。"
        )
        await UniMessage.text(msg).send(target)
        return

    target_group_id = None
    if target_group_id_match:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能指定群组。").send(target)
            return
        target_group_id = str(target_group_id_match)
    elif isinstance(event, GroupMessageEvent):
        target_group_id = str(event.group_id)
    else:
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> / -all 参数指定目标。"
        ).send(target)
        return

    schedule = await scheduler_manager.add_daily_task(
        plugin_name="summary_group",
        group_id=target_group_id,
        hour=hour,
        minute=minute,
        job_kwargs=job_kwargs,
    )

    if schedule:
        response_msg = (
            f"已成功为群 {target_group_id} 设置定时总结任务: \n"
            f"每天 {hour:02d}:{minute:02d} 发送"
        )
        await UniMessage.text(response_msg).send(target)
    else:
        await UniMessage.text(f"为群 {target_group_id} 设置定时任务失败。").send(target)


async def handle_summary_remove(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    target: MsgTarget,
):
    arp = result.result
    is_superuser = await SUPERUSER(bot, event)
    target_group_id_match = arp.query("g.target_group_id")
    all_enabled = arp.find("all")

    if all_enabled:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能操作所有群组。").send(target)
            return
        targeter = scheduler_manager.target(plugin_name="summary_group")
    elif target_group_id_match:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能指定群组。").send(target)
            return
        targeter = scheduler_manager.target(
            plugin_name="summary_group", group_id=str(target_group_id_match)
        )
    elif isinstance(event, GroupMessageEvent):
        targeter = scheduler_manager.target(
            plugin_name="summary_group", group_id=str(event.group_id)
        )
    else:
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> / -all 参数。"
        ).send(target)
        return

    removed_count, message = await targeter.remove()

    if removed_count > 0:
        await UniMessage.text(message).send(target)
    else:
        await UniMessage.text("没有找到匹配的定时总结任务来取消。").send(target)
