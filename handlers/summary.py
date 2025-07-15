from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import At, CommandResult, Match, Text
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.models.statistics import Statistics
from zhenxun.services.log import logger

from ..services import SummaryParameters, SummaryService


async def handle_summary(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    message_count: int,
    style: Match[str],
    parts: Match[list[At | Text]],
    target: MsgTarget,
):
    user_id_str = event.get_user_id()
    originating_group_id = (
        event.group_id if isinstance(event, GroupMessageEvent) else None
    )
    is_superuser = await SUPERUSER(bot, event)

    arp = result.result
    target_group_id_match = arp.query("g.target_group_id") if arp else None

    if target_group_id_match and is_superuser:
        target_group_id_to_fetch = int(target_group_id_match)
    else:
        target_group_id_to_fetch = originating_group_id

    if target_group_id_to_fetch is None:
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> 参数指定目标群聊。 (仅限超级用户)"
        ).send(target)
        return

    target_user_ids: set[str] = set()
    content_parts: list[str] = []

    if parts.available:
        for part in parts.result:
            if isinstance(part, At) and part.target:
                target_user_ids.add(str(part.target))
        for part in parts.result:
            if isinstance(part, Text):
                stripped_text = part.text.strip()
                if stripped_text:
                    content_parts.append(stripped_text)

    arp = result.result
    if arp and "$extra" in arp.main_args:
        extra_args = arp.main_args.get("$extra", [])
        if extra_args:
            for arg in extra_args:
                if isinstance(arg, At) and arg.target:
                    target_user_ids.add(str(arg.target))
            for arg in extra_args:
                if isinstance(arg, Text):
                    stripped_text = arg.text.strip()
                    if stripped_text:
                        content_parts.append(stripped_text)

    content_value = " ".join(content_parts)

    logger.debug(
        f"总结参数: 目标群={target_group_id_to_fetch}, 消息数量={message_count}, ...",
        command="总结",
    )

    feedback_target_group_part = (
        f"群聊 {target_group_id_to_fetch} 的"
        if (target_group_id_match and is_superuser)
        else "群聊"
    )
    feedback = f"正在生成{feedback_target_group_part}总结"
    if style.available:
        feedback += f"（风格: {style.result}）"
    feedback += f"{'（指定用户）' if target_user_ids else ''}，请稍候..."
    await UniMessage.text(feedback).send(target)

    params = SummaryParameters(
        bot=bot,
        target_group_id=target_group_id_to_fetch,
        message_count=message_count,
        style=style.result if style.available else None,
        content_filter=content_value,
        target_user_ids=target_user_ids,
        response_target=target,
    )

    service = SummaryService(params)
    success = await service.execute()

    if success:
        logger.debug(
            f"总结命令成功完成 (Group: {target_group_id_to_fetch})", command="总结"
        )
        try:
            await Statistics.create(
                user_id=str(user_id_str),
                group_id=(str(originating_group_id) if originating_group_id else None),
                plugin_name="summary_group",
                bot_id=str(bot.self_id),
                message_count=message_count,
                style=style.result if style.available else None,
                target_users=list(target_user_ids),
                content_filter=content_value,
            )
        except Exception as stat_e:
            logger.error(f"记录统计失败: {stat_e}", command="总结", e=stat_e)
