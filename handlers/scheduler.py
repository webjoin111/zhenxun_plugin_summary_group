from datetime import datetime
import traceback

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent

# 备注：
# 自己把全部的event改成session获取吧
# 不要从nonebot.adapters.onebot.v11导入，而是使用nonebot.adapters
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import CommandResult
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.configs.config import Config
from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.services.log import logger

base_config = Config.get("summary_group")

from ..store import Store
from ..utils.scheduler import (
    SummaryException,
    check_scheduler_status,
    scheduler_send_summary,
    update_single_group_schedule,
    verify_processor_status,
)


class TimeParseException(SummaryException):
    pass


class SchedulerException(SummaryException):
    pass


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


async def handle_global_summary_set(
    bot: Bot, hour: int, minute: int, least_count: int, style: str | None
) -> tuple[bool, str, int]:
    from nonebot_plugin_apscheduler import scheduler

    logger.debug(
        f"执行全局定时总结设置: {hour:02d}:{minute:02d}, 最少消息数: {least_count}, 风格: {style or '默认'}",
        "全局定时总结",
    )

    try:
        store = Store()

        group_list = await bot.get_group_list()
        group_ids = [group["group_id"] for group in group_list]

        logger.debug(
            f"开始设置全局定时任务，总共 {len(group_ids)} 个群", "全局定时总结"
        )
        updated_count = 0

        data = {
            "hour": hour,
            "minute": minute,
            "least_message_count": least_count,
            "style": style,
        }

        failed_groups = []

        for group_id in group_ids:
            try:
                group_id = int(group_id)
                store.set(group_id, data)

                job_id = f"summary_group_{group_id}"
                try:
                    if scheduler.get_job(job_id):
                        scheduler.remove_job(job_id)
                except Exception as e:
                    logger.warning(
                        f"移除群 {group_id} 的现有任务时出错: {e!s}",
                        "全局定时总结",
                        group_id=group_id,
                        e=e,
                    )

                second = group_id % 60
                scheduler.add_job(
                    scheduler_send_summary,
                    "cron",
                    hour=hour,
                    minute=minute,
                    second=second,
                    args=(group_id, least_count, style),
                    id=job_id,
                    replace_existing=True,
                    timezone="Asia/Shanghai",
                )

                updated_count += 1
                logger.debug(
                    f"已设置群 {group_id} 的全局定时任务",
                    "全局定时总结",
                    group_id=group_id,
                )

            except Exception as e:
                failed_groups.append(group_id)
                logger.error(
                    f"设置群 {group_id} 的全局定时任务失败: {e!s}",
                    "全局定时总结",
                    group_id=group_id,
                    e=e,
                )

        result_msg = f"全局定时总结设置完成，每天{hour:02d}:{minute:02d}将为{updated_count}个群发送最近{least_count}条消息的内容总结{f'（风格: {style}）' if style else ''}。"

        if failed_groups:
            result_msg += (
                f"\n注意: {len(failed_groups)}个群设置失败: {failed_groups[:5]}"
            )
            if len(failed_groups) > 5:
                result_msg += f"等{len(failed_groups)}个群"

        logger.debug(f"全局设置完成，响应消息: {result_msg}", "全局定时总结")
        return True, result_msg, updated_count

    except Exception as e:
        logger.error(f"设置全局定时总结时发生异常: {e!s}", "全局定时总结", e=e)
        return False, f"设置全局定时总结失败: {e!s}", 0


async def handle_summary_set(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    time_tuple: tuple[int, int],
    least_count: int,
    style: str | None,
    target: MsgTarget,
):
    try:
        bot_id = bot.self_id
        user_id_str = event.get_user_id()

        group_id = getattr(event, "group_id", None)
        plugin_name = "summary_group"
    except Exception as e:
        logger.error(f"获取事件基础信息失败: {e}", "定时总结", e=e)
        await UniMessage.text("无法获取必要信息，请稍后重试。").send(target)
        return

    arp = result.result
    if not arp:
        logger.error("在 handle_summary_set 中 Arparma result 为 None", "定时总结")
        await UniMessage.text("命令解析内部错误。").send(target)
        return

    target_group_id_match = arp.query("g.target_group_id")
    all_enabled = arp.find("all")
    style_value = style

    is_superuser = await SUPERUSER(bot, event)
    action_type = "unknown"

    can_proceed = True
    try:
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping.",
                "定时总结",
                session=user_id_str,
                group_id=group_id,
            )
            can_proceed = False
        if can_proceed and await BotConsole.is_block_plugin(bot_id, plugin_name):
            logger.info(
                f"Plugin '{plugin_name}' is blocked for Bot {bot_id}.",
                "定时总结",
                session=user_id_str,
            )
            can_proceed = False

        if can_proceed and await BanConsole.is_ban(user_id_str, None):
            logger.info(
                f"User {user_id_str} is globally banned.",
                "定时总结",
                session=user_id_str,
            )
            can_proceed = False

        if group_id and not is_superuser:
            if can_proceed and await BanConsole.is_ban(user_id_str, str(group_id)):
                logger.info(
                    f"User {user_id_str} is banned in group {group_id}.",
                    "定时总结",
                    session=user_id_str,
                    group_id=group_id,
                )
                can_proceed = False
            # GroupConsole.get_group_status(str(group_id)) 没看懂你的意图
            # if can_proceed and not await GroupConsole.get_group_status(str(group_id)):
            #     logger.info(
            #         f"Group {group_id} is inactive.",
            #         "定时总结",
            #         group_id=group_id,
            #     )
            #     can_proceed = False
            if can_proceed and await GroupConsole.is_block_plugin(
                str(group_id), plugin_name
            ):
                logger.info(
                    f"Plugin '{plugin_name}' is blocked in group {group_id}.",
                    "定时总结",
                    group_id=group_id,
                )
                can_proceed = False
    except Exception as e:
        logger.error(f"获取权限或状态时出错: {e}", "定时总结", e=e)
        await UniMessage.text(f"内部错误，无法检查权限: {e!s}").send(target)
        return

    if not can_proceed:
        await UniMessage.text(
            "当前环境不允许执行此命令。请检查Bot、群聊或用户状态。"
        ).send(target)
        return

    hour, minute = time_tuple

    if (
        not isinstance(event, GroupMessageEvent)
        and not target_group_id_match
        and not all_enabled
    ):
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> / -all 参数指定目标"
        ).send(target)
        return

    if all_enabled:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能使用 -all 参数").send(target)
            return

        logger.info(f"超级用户 {user_id_str} 触发全局定时总结设置", "定时总结")
        action_type = "all"
        target_group_id = 0

    elif target_group_id_match:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能使用 -g 参数").send(target)
            return

        target_group_id = int(target_group_id_match)
        logger.info(
            f"超级用户 {user_id_str} 触发对群 {target_group_id} 的定时总结设置",
            "定时总结",
        )
        action_type = "specific_group_by_superuser"
    elif isinstance(event, GroupMessageEvent):
        target_group_id = event.group_id
        logger.info(
            f"用户 {user_id_str} 触发对本群 {target_group_id} 的定时总结设置",
            "定时总结",
        )
        action_type = "current_group_by_admin"
    else:
        logger.error("逻辑错误: 无法确定目标群组", "定时总结")
        await UniMessage.text("内部错误：无法确定要设置的群组。").send(target)
        return
    logger.debug(
        f"最终确定的操作类型: {action_type}, "
        f"目标群ID (如果适用): {target_group_id if 'group' in action_type else 'N/A'}",
        "定时总结",
    )

    try:
        if action_type == "all":
            success, message, count = await handle_global_summary_set(
                bot, hour, minute, least_count, style_value
            )
            if success:
                await UniMessage.text(message).send(target)
                logger.info(f"全局定时总结设置成功，影响 {count} 个群", "定时总结")
            else:
                await UniMessage.text(f"全局设置失败: {message}").send(target)
                logger.error(f"全局定时总结设置失败: {message}", "定时总结")

        elif action_type in {
            "specific_group_by_superuser",
            "current_group_by_admin",
        }:
            data = {
                "hour": hour,
                "minute": minute,
                "least_message_count": least_count,
                "style": style_value,
            }
            success, message = await update_single_group_schedule(target_group_id, data)

            if success:
                response_msg = f"已成功为群 {target_group_id} 设置定时总结任务: \n每天 {hour:02d}:{minute:02d} 发送，最少消息数 {least_count}{f'，风格：{style_value}' if style_value else ''}"
                await UniMessage.text(response_msg).send(target)
                logger.info(f"群 {target_group_id} 的定时总结设置成功", "定时总结")
            else:
                await UniMessage.text(f"设置群 {target_group_id} 失败: {message}").send(
                    target
                )
                logger.error(
                    f"群 {target_group_id} 的定时总结设置失败: {message}",
                    "定时总结",
                )
        else:
            logger.error(f"未知的操作类型: {action_type}", "定时总结")
            await UniMessage.text("内部错误: 未知的操作类型").send(target)

    except SchedulerException as e:
        logger.error(f"定时任务调度异常: {e!s}", "定时总结", e=e)
        await UniMessage.text(f"定时任务调度时出错: {e!s}").send(target)
    except Exception as e:
        logger.error(
            f"处理定时总结设置命令时发生未预料的异常: {e!s}",
            "定时总结",
            e=e,
        )
        logger.error(traceback.format_exc(), "定时总结")
        await UniMessage.text(f"处理命令时发生意外错误: {e!s} 请检查日志").send(target)


async def handle_global_summary_remove(store: Store) -> tuple[bool, str, int, int]:
    from nonebot_plugin_apscheduler import scheduler

    logger.debug("执行取消所有群组的定时总结", "全局定时总结")

    try:
        group_ids = store.get_all_groups()
        group_count = len(group_ids)

        if group_count == 0:
            logger.debug("当前没有任何群设置了定时总结", "全局定时总结")
            return True, "当前没有任何群设置了定时总结。", 0, 0

        removed_count = 0
        failed_groups = []

        for group_id_str in group_ids:
            try:
                group_id = int(group_id_str)
                job_id = f"summary_group_{group_id}"
                try:
                    if scheduler.get_job(job_id):
                        scheduler.remove_job(job_id)
                        removed_count += 1
                        logger.debug(
                            f"已从调度器中移除群 {group_id} 的定时任务",
                            "全局定时总结",
                            group_id=group_id,
                        )
                    else:
                        logger.warning(
                            f"调度器中未找到群 {group_id} 的定时任务",
                            "全局定时总结",
                            group_id=group_id,
                        )
                except Exception as e:
                    failed_groups.append(group_id)
                    logger.warning(
                        f"移除群 {group_id} 的定时任务时出错: {e!s}",
                        "全局定时总结",
                        group_id=group_id,
                        e=e,
                    )
            except ValueError:
                logger.warning(f"无效的群号: {group_id_str}", "全局定时总结")

        store.remove_all()
        logger.debug("已清空所有群组的定时总结设置", "全局定时总结")

        if remaining_jobs := [
            job
            for job in scheduler.get_jobs()
            if job.id.startswith("summary_group_")
        ]:
            logger.warning(
                f"清除后仍有 {len(remaining_jobs)} 个总结任务在调度器中: {[job.id for job in remaining_jobs]}",
                "全局定时总结",
            )

            for job in remaining_jobs:
                try:
                    scheduler.remove_job(job.id)
                    logger.debug(f"强制移除调度器中的任务: {job.id}", "全局定时总结")
                except Exception as e:
                    logger.error(
                        f"强制移除任务 {job.id} 失败: {e!s}",
                        "全局定时总结",
                        e=e,
                    )

        result_msg = f"已取消所有群的定时总结，共影响 {group_count} 个群组，从调度器中移除了 {removed_count} 个任务。"

        if failed_groups:
            result_msg += (
                f"\n注意: {len(failed_groups)}个群取消失败: {failed_groups[:5]}"
            )
            if len(failed_groups) > 5:
                result_msg += f"等{len(failed_groups)}个群"

        logger.debug(f"全局取消完成，响应消息: {result_msg}", "全局定时总结")
        return True, result_msg, group_count, removed_count

    except Exception as e:
        logger.error(
            f"取消所有群组定时总结时发生异常: {e!s}",
            "全局定时总结",
        )
        return False, f"取消全局定时总结失败: {e!s}", 0, 0


async def handle_summary_remove(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    target: MsgTarget,
):
    try:
        bot_id = bot.self_id
        user_id_str = event.get_user_id()
        group_id = getattr(event, "group_id", None)
        plugin_name = "summary_group"
    except Exception as e:
        logger.error(f"获取事件基础信息失败: {e}", "定时总结取消", e=e)
        await UniMessage.text("无法获取必要信息，请稍后重试。").send(target)
        return

    arp = result.result
    if not arp:
        logger.error(
            "在 handle_summary_remove 中 Arparma result 为 None", "定时总结取消"
        )
        await UniMessage.text("命令解析内部错误。").send(target)
        return

    target_group_id_match = arp.query("g.target_group_id")
    all_enabled = arp.find("all")

    is_superuser = await SUPERUSER(bot, event)
    action_type = "unknown"

    can_proceed = True
    try:
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping.",
                "定时总结取消",
                session=user_id_str,
                group_id=group_id,
            )
            can_proceed = False
        if can_proceed and await BotConsole.is_block_plugin(bot_id, plugin_name):
            logger.info(
                f"Plugin '{plugin_name}' is blocked for Bot {bot_id}.",
                "定时总结取消",
                session=user_id_str,
            )
            can_proceed = False

        if can_proceed and await BanConsole.is_ban(user_id_str, None):
            logger.info(
                f"User {user_id_str} is globally banned.",
                "定时总结取消",
                session=user_id_str,
            )
            can_proceed = False

        if group_id and not is_superuser:
            if can_proceed and await BanConsole.is_ban(user_id_str, str(group_id)):
                logger.info(
                    f"User {user_id_str} is banned in group {group_id}.",
                    "定时总结取消",
                    session=user_id_str,
                    group_id=group_id,
                )
                can_proceed = False
            # GroupConsole.get_group_status(str(group_id)) 没看懂你的意图
            # if can_proceed and not await GroupConsole.get_group_status(str(group_id)):
            #     logger.info(
            #         f"Group {group_id} is inactive.",
            #         "定时总结取消",
            #         group_id=group_id,
            #     )
            #     can_proceed = False
            if can_proceed and await GroupConsole.is_block_plugin(
                str(group_id), plugin_name
            ):
                logger.info(
                    f"Plugin '{plugin_name}' is blocked in group {group_id}.",
                    "定时总结取消",
                    group_id=group_id,
                )
                can_proceed = False
    except Exception as e:
        logger.error(f"获取权限或状态时出错: {e}", "定时总结取消", e=e)
        await UniMessage.text(f"内部错误，无法检查权限: {e!s}").send(target)
        return

    if not can_proceed:
        await UniMessage.text(
            "当前环境不允许执行此命令。请检查Bot、群聊或用户状态。"
        ).send(target)
        return

    if (
        not isinstance(event, GroupMessageEvent)
        and not target_group_id_match
        and not all_enabled
    ):
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> / -all 参数指定目标"
        ).send(target)
        return

    if all_enabled:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能使用 -all 参数").send(target)
            return

        logger.info(f"超级用户 {user_id_str} 触发全局定时总结取消", "定时总结取消")
        action_type = "all"
        tar

    elif target_group_id_match:
        if not is_superuser:
            await UniMessage.text("需要超级用户权限才能使用 -g 参数").send(target)
            return

        target_group_id = int(target_group_id_match)
        logger.info(
            f"超级用户 {user_id_str} 触发对群 {target_group_id} 的定时总结取消",
            "定时总结取消",
        )
        action_type = "specific_group_by_superuser"

    elif isinstance(event, GroupMessageEvent):
        target_group_id = event.group_id
        logger.info(
            f"用户 {user_id_str} 触发对本群 {target_group_id} 的定时总结取消",
            "定时总结取消",
        )
        action_type = "current_group_by_admin"
    else:
        logger.error("逻辑错误: 无法确定目标群组", "定时总结取消")
        await UniMessage.text("内部错误：无法确定要取消的群组。").send(target)
        return

    logger.debug(
        f"最终确定的操作类型: {action_type}, "
        f"目标群ID (如果适用): {target_group_id if 'group' in action_type else 'N/A'}",
        "定时总结取消",
    )

    try:
        if action_type == "all":
            (
                success,
                message,
                removed_count,
                total_count,
            ) = await handle_global_summary_remove(Store())
            if success:
                await UniMessage.text(message).send(target)
                logger.info(
                    f"全局定时总结取消成功，移除了 {removed_count}/{total_count} 个群的任务",
                    "定时总结取消",
                )
            else:
                await UniMessage.text(f"全局取消失败: {message}").send(target)
                logger.error(f"全局定时总结取消失败: {message}", "定时总结取消")

        elif action_type in {
            "specific_group_by_superuser",
            "current_group_by_admin",
        }:
            # 这一块代码不可用，没有正确的导入路径，不明白你的意图
            from ..utils.scheduler import remove_schedule_for_group

            if removed := remove_schedule_for_group(target_group_id):
                response_msg = f"已成功取消群 {target_group_id} 的定时总结任务。"
                await UniMessage.text(response_msg).send(target)
                logger.info(f"群 {target_group_id} 的定时总结取消成功", "定时总结取消")
            else:
                response_msg = f"群 {target_group_id} 未设置定时总结任务，无需取消。"
                await UniMessage.text(response_msg).send(target)
                logger.info(
                    f"群 {target_group_id} 未设置定时任务，取消操作跳过",
                    "定时总结取消",
                )
        else:
            logger.error(f"未知的操作类型: {action_type}", "定时总结取消")
            await UniMessage.text("内部错误: 未知的操作类型").send(target)

    except SchedulerException as e:
        logger.error(f"定时任务调度异常: {e!s}", "定时总结取消", e=e)
        await UniMessage.text(f"定时任务调度时出错: {e!s}").send(target)
    except Exception as e:
        logger.error(
            f"处理定时总结取消命令时发生未预料的异常: {e!s}",
            "定时总结取消",
            e=e,
        )
        logger.error(traceback.format_exc(), "定时总结取消")
        await UniMessage.text(f"处理命令时发生意外错误: {e!s} 请检查日志").send(target)


async def check_scheduler_status_handler(
    bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget
):
    from nonebot_plugin_apscheduler import scheduler

    from ..store import Store

    try:
        store = Store()
        group_ids = store.get_all_groups()
        group_count = len(group_ids)

        if group_count == 0:
            await UniMessage.text("当前没有任何群设置了定时总结。").send(target)
            return

        scheduler_status_list = check_scheduler_status()
        processor_status = verify_processor_status()

        status_msg = "定时总结系统状态：\n\n"
        status_msg += f"调度器状态：{'运行中' if scheduler.running else '已停止'}\n"
        status_msg += f"处理器状态：{'正常' if processor_status else '异常'}\n\n"

        if not scheduler.running or not processor_status:
            status_msg += "⚠️ 系统存在异常，建议使用'总结系统修复'命令尝试修复。\n\n"

        status_msg += f"当前共有 {group_count} 个群设置了定时总结：\n"

        all_jobs = {
            job.id: job
            for job in scheduler_status_list
            if job.id.startswith("summary_group_")
        }

        for group_id_str in group_ids:
            try:
                group_id_int = int(group_id_str)
            except ValueError:
                logger.warning(f"存储中发现无效的 group_id: {group_id_str}", "调度状态")
                continue

            if data := store.get(group_id_int):
                hour = data.get("hour", 0)
                minute = data.get("minute", 0)
                least_count = data.get(
                    "least_message_count",
                    base_config.get("SUMMARY_MAX_LENGTH", 1000),
                )
                style = data.get("style")

                job_id = f"summary_group_{group_id_int}"
                job = all_jobs.get(job_id)

                next_run = "未调度"
                if job and job.next_run_time:
                    try:
                        local_tz = datetime.now().astimezone().tzinfo
                        next_run_local = job.next_run_time.astimezone(local_tz)
                        next_run = next_run_local.strftime("%Y-%m-%d %H:%M:%S %Z")
                    except Exception as tz_e:
                        logger.warning(
                            f"格式化下次运行时间时出错: {tz_e}",
                            "调度状态",
                            e=tz_e,
                        )
                        next_run = job.next_run_time.strftime(
                            "%Y-%m-%d %H:%M:%S (原始时区)"
                        )

                style_info = f"，风格：{style}" if style else ""
                status_msg += (
                    f"群 {group_id_int}：每天 {hour:02d}:{minute:02d}，"
                    f"最少 {least_count} 条消息{style_info}，下次执行：{next_run}\n"
                )

        await UniMessage.text(status_msg).send(target)

    except Exception as e:
        logger.error(f"检查调度器状态时发生异常: {e!s}", "全局定时总结")
        await UniMessage.text(f"检查调度器状态失败: {e!s}").send(target)


async def handle_summary_status(
    bot: Bot, event: GroupMessageEvent | PrivateMessageEvent
):
    if not isinstance(event, GroupMessageEvent):
        await bot.send(event, "此命令只能在群聊中使用。")
        return

    group_id = event.group_id
    user_id = event.get_user_id()
    logger.debug(f"用户 {user_id} 在群 {group_id} 查询总结状态", "总结状态")

    store = Store()
    if data := store.get(group_id):
        hour = data["hour"]
        minute = data["minute"]
        least_count = data["least_message_count"]
        style = data.get("style")
        # 这一块代码不可用，没有正确的导入路径，不明白你的意图
        from ..utils.scheduler import get_next_run_time_for_group

        next_run_time = get_next_run_time_for_group(group_id)

        status_msg = (
            f"本群已设置定时总结任务:\n"
            f"  执行时间: 每天 {hour:02d}:{minute:02d}\n"
            f"  最少消息数: {least_count}\n"
            f"  总结风格: {style if style else '默认'}\n"
            f"  下次执行时间: {next_run_time.strftime('%Y-%m-%d %H:%M:%S') if next_run_time else '未知或未调度'}"
        )
    else:
        status_msg = "本群当前未设置定时总结任务。"

    await bot.send(event, status_msg)


async def handle_summary_cancel(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
):
    try:
        bot_id = bot.self_id
        user_id = event.get_user_id()
        group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else None

        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping command.",
                "取消定时",
                session=user_id,
            )
            return

        if await BotConsole.is_block_plugin(bot_id, "summary_group"):
            logger.info(
                f"Plugin 'summary_group' is blocked for Bot {bot_id}.",
                "取消定时",
                session=user_id,
            )
            return

        if group_id and await GroupConsole.is_block_plugin(group_id, "summary_group"):
            logger.info(
                f"Plugin 'summary_group' is blocked for Group {group_id}.",
                "取消定时",
                session=user_id,
                group_id=group_id,
            )
            await bot.send(event, "群聊总结功能在本群已被禁用。")
            return

        if group_id and await BanConsole.is_ban(None, group_id):
            logger.info(f"Group {group_id} is banned.", "取消定时", group_id=group_id)
            return

        if group_id and await BanConsole.is_ban(user_id, group_id):
            logger.info(
                f"User {user_id} is banned in Group {group_id}.",
                "取消定时",
                session=user_id,
                group_id=group_id,
            )
            return

        logger.debug(
            f"用户 {user_id} 触发了取消定时命令",
            "取消定时",
            session=user_id,
            group_id=group_id,
        )

    except Exception as e:
        logger.error(
            f"执行命令前检查出错: {e}",
            "取消定时",
            session=event.get_user_id(),
            group_id=getattr(event, "group_id", None),
            e=e,
        )
        await bot.send(event, "执行命令前检查出错，请联系管理员。")
        return
