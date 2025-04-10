
from typing import Union, Tuple
from datetime import datetime
from zhenxun.services.log import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.exception import FinishedException
from nonebot_plugin_alconna import CommandResult, Args, on_alconna
import traceback
from nonebot.permission import SUPERUSER
from zhenxun.configs.config import Config
from nonebot_plugin_alconna.uniseg import UniMessage, Target, MsgTarget
from ..store import Store
from ..utils.scheduler import (
    check_scheduler_status,
    verify_processor_status,
    update_single_group_schedule,
    scheduler_send_summary,
    SummaryException,
)

from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.ban_console import BanConsole


class TimeParseException(SummaryException):

    pass


class SchedulerException(SummaryException):

    pass


def parse_time(time_str: str) -> tuple[int, int]:
    logger.debug(f"parse_time called with input: {repr(time_str)}")

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
    bot: Bot, hour: int, minute: int, least_count: int
) -> Tuple[bool, str, int]:
    from nonebot_plugin_apscheduler import scheduler

    logger.debug(
        f"执行全局定时总结设置: {hour:02d}:{minute:02d}, 最少消息数: {least_count}",
        command="全局定时总结",
    )

    try:
        store = Store()

        group_list = await bot.get_group_list()
        group_ids = [group["group_id"] for group in group_list]

        logger.debug(
            f"开始设置全局定时任务，总共 {len(group_ids)} 个群", command="全局定时总结"
        )
        updated_count = 0

        data = {
            "hour": hour,
            "minute": minute,
            "least_message_count": least_count,
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
                        f"移除群 {group_id} 的现有任务时出错: {str(e)}",
                        command="全局定时总结",
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
                    args=(group_id, least_count),
                    id=job_id,
                    replace_existing=True,
                    timezone="Asia/Shanghai",
                )

                updated_count += 1
                logger.debug(
                    f"已设置群 {group_id} 的全局定时任务",
                    command="全局定时总结",
                    group_id=group_id,
                )

            except Exception as e:
                failed_groups.append(group_id)
                logger.error(
                    f"设置群 {group_id} 的全局定时任务失败: {str(e)}",
                    command="全局定时总结",
                    group_id=group_id,
                    e=e,
                )

        result_msg = f"全局定时总结设置完成，每天{hour:02d}:{minute:02d}将为{updated_count}个群发送最近{least_count}条消息的内容总结。"

        if failed_groups:
            result_msg += (
                f"\n注意: {len(failed_groups)}个群设置失败: {failed_groups[:5]}"
            )
            if len(failed_groups) > 5:
                result_msg += f"等{len(failed_groups)}个群"

        logger.debug(f"全局设置完成，响应消息: {result_msg}", command="全局定时总结")
        return True, result_msg, updated_count

    except Exception as e:
        logger.error(
            f"设置全局定时总结时发生异常: {str(e)}", command="全局定时总结", e=e
        )
        return False, f"设置全局定时总结失败: {str(e)}", 0


async def handle_summary_set(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    result: CommandResult,
    time_tuple: Tuple[int, int],  
    least_count: int,  
    target: MsgTarget,
):
    
    try:
        bot_id = bot.self_id
        user_id = event.get_user_id()
        group_id = event.group_id if isinstance(event, GroupMessageEvent) else None

        if not group_id:
            logger.warning(
                "定时总结命令在非群聊环境被触发", command="定时总结", session=user_id
            )
            await UniMessage.text("定时总结命令只能在群聊中使用。").send(target)
            return

        
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping command.",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )
            return

        
        if await BotConsole.is_block_plugin(bot_id, "summary_group"):
            logger.info(
                f"Plugin 'summary_group' is blocked for Bot {bot_id}.",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )
            return

        
        if await GroupConsole.is_block_plugin(group_id, "summary_group"):
            logger.info(
                f"Plugin 'summary_group' is blocked for Group {group_id}.",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )
            await UniMessage.text("群聊总结功能在本群已被禁用。").send(target)
            return

        
        if await BanConsole.is_ban(None, group_id):
            logger.info(
                f"Group {group_id} is banned.", command="定时总结", group_id=group_id
            )
            return

        
        if await BanConsole.is_ban(user_id, group_id):
            logger.info(
                f"User {user_id} is banned in Group {group_id}.",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )
            return

        logger.debug(
            f"用户 {user_id} 在群 {group_id} 触发了定时总结命令",
            command="定时总结",
            session=user_id,
            group_id=group_id,
        )

    except Exception as e:
        logger.error(
            f"执行命令前检查出错: {e}",
            command="定时总结",
            session=event.get_user_id(),
            group_id=getattr(event, "group_id", None),
            e=e,
        )
        await UniMessage.text("执行命令前检查出错，请联系管理员。").send(target)
        return

    try:
        
        arp = result.result
        target_group_id = arp.query("g.target_group_id", None)
        all_enabled = "all" in arp.options

        logger.debug(
            f"命令解析：time={time_tuple}, least_message_count={least_count}, "
            f"all_enabled={all_enabled}, target_group_id={target_group_id}, "
            f"options={list(arp.options.keys())}",
            command="定时总结",
            session=user_id,
            group_id=group_id,
        )

        
        is_superuser = await SUPERUSER(bot, event)

        
        if all_enabled or target_group_id is not None:
            if not is_superuser:
                logger.warning(
                    f"用户 {user_id} 尝试使用超级用户特权",
                    command="定时总结",
                    session=user_id,
                    group_id=group_id,
                )
                await UniMessage.text("使用 -all 或 -g 选项需要超级用户权限。").send(
                    target
                )
                return

        
        hour, minute = time_tuple

        if all_enabled:
            logger.debug(
                "检测到-all参数，准备设置全局定时任务",
                command="定时总结",
                session=user_id,
            )

            try:
                success, result_msg, _ = await handle_global_summary_set(
                    bot, hour, minute, least_count
                )
                await UniMessage.text(result_msg).send(target)
                return

            except FinishedException:
                logger.debug("处理被正常终止", command="定时总结", session=user_id)
                return
            except Exception as e:
                logger.error(
                    f"设置全局定时总结时发生异常: {str(e)}",
                    command="定时总结",
                    session=user_id,
                    e=e,
                )
                await UniMessage.text(f"设置全局定时总结失败: {str(e)}").send(target)
                return

        logger.debug(
            "执行单群设置流程", command="定时总结", session=user_id, group_id=group_id
        )

        target_id = None

        if target_group_id is not None:
            target_id = target_group_id
            logger.debug(
                f"从-g参数获取到群号: {target_id}",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )
        else:
            target_id = group_id
            logger.debug(
                f"使用当前群号: {target_id}",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )

        try:
            logger.debug(
                f"验证群 {target_id} 是否存在",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )
            group_info = await bot.get_group_info(group_id=target_id)
            if not group_info:
                logger.warning(
                    f"群 {target_id} 不存在或Bot不在该群中",
                    command="定时总结",
                    session=user_id,
                    group_id=group_id,
                )
                await UniMessage.text(f"群 {target_id} 不存在或Bot不在该群中。").send(
                    target
                )
                return
        except Exception as e:
            logger.error(
                f"获取群 {target_id} 信息失败: {str(e)}",
                command="定时总结",
                session=user_id,
                group_id=group_id,
                e=e,
            )
            await UniMessage.text(f"获取群信息失败: {str(e)}").send(target)
            return

        data = {
            "hour": hour,
            "minute": minute,
            "least_message_count": least_count,
        }

        logger.debug(
            f"为群 {target_id} 保存定时设置: {data}",
            command="定时总结",
            session=user_id,
            group_id=group_id,
        )
        store = Store()
        store.set(target_id, data)
        success, job = await update_single_group_schedule(target_id, data)
        logger.debug(
            f"更新调度任务结果: success={success}, job_id={job.id if job else None}",
            command="定时总结",
            session=user_id,
            group_id=group_id,
        )

        response_msg = f"已设置定时总结，将在每天{hour:02d}:{minute:02d}发送群 {target_id} 最近{least_count}条消息的内容总结。"

        if success and job and hasattr(job, "next_run_time") and job.next_run_time:
            next_time = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            response_msg += f"\n下次执行时间: {next_time}"

        logger.debug(
            f"单群设置完成，响应消息: {response_msg}",
            command="定时总结",
            session=user_id,
            group_id=group_id,
        )
        await UniMessage.text(response_msg).send(target)
    except Exception as e:
        logger.error(
            f"处理定时总结设置命令时发生异常: {str(e)}",
            command="定时总结",
            session=user_id,
            group_id=group_id,
            e=e,
        )
        try:
            await UniMessage.text(f"设置定时总结失败: {str(e)}").send(target)
        except Exception:
            logger.error(
                "发送错误消息失败",
                command="定时总结",
                session=user_id,
                group_id=group_id,
            )


async def handle_global_summary_remove(store: Store) -> Tuple[bool, str, int, int]:
    from nonebot_plugin_apscheduler import scheduler

    logger.debug("执行取消所有群组的定时总结", command="全局定时总结")

    try:
        group_ids = store.get_all_groups()
        group_count = len(group_ids)

        if group_count == 0:
            logger.debug("当前没有任何群设置了定时总结", command="全局定时总结")
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
                            command="全局定时总结",
                            group_id=group_id,
                        )
                    else:
                        logger.warning(
                            f"调度器中未找到群 {group_id} 的定时任务",
                            command="全局定时总结",
                            group_id=group_id,
                        )
                except Exception as e:
                    failed_groups.append(group_id)
                    logger.warning(
                        f"移除群 {group_id} 的定时任务时出错: {str(e)}",
                        command="全局定时总结",
                        group_id=group_id,
                        e=e,
                    )
            except ValueError:
                logger.warning(f"无效的群号: {group_id_str}", command="全局定时总结")

        store.remove_all()
        logger.debug(f"已清空所有群组的定时总结设置", command="全局定时总结")

        remaining_jobs = [
            job for job in scheduler.get_jobs() if job.id.startswith("summary_group_")
        ]

        if remaining_jobs:
            logger.warning(
                f"清除后仍有 {len(remaining_jobs)} 个总结任务在调度器中: {[job.id for job in remaining_jobs]}",
                command="全局定时总结",
            )

            for job in remaining_jobs:
                try:
                    scheduler.remove_job(job.id)
                    logger.debug(
                        f"强制移除调度器中的任务: {job.id}", command="全局定时总结"
                    )
                except Exception as e:
                    logger.error(
                        f"强制移除任务 {job.id} 失败: {str(e)}",
                        command="全局定时总结",
                        e=e,
                    )

        result_msg = f"已取消所有群的定时总结，共影响 {group_count} 个群组，从调度器中移除了 {removed_count} 个任务。"

        if failed_groups:
            result_msg += (
                f"\n注意: {len(failed_groups)}个群取消失败: {failed_groups[:5]}"
            )
            if len(failed_groups) > 5:
                result_msg += f"等{len(failed_groups)}个群"

        logger.debug(f"全局取消完成，响应消息: {result_msg}", command="全局定时总结")
        return True, result_msg, group_count, removed_count

    except Exception as e:
        logger.error(
            f"取消所有群组定时总结时发生异常: {str(e)}",
            command="全局定时总结",
            exc_info=True,
        )
        return False, f"取消全局定时总结失败: {str(e)}", 0, 0


async def handle_summary_remove(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    result: CommandResult,
):

    summary_remove = on_alconna("定时总结取消")

    try:
        all_enabled = "all" in result.result.options
        target_group_id = result.result.query("target_group_id", None)

        logger.debug(
            f"处理取消定时总结命令: all_enabled={all_enabled}, target_group_id={target_group_id}, options={list(result.result.options.keys())}",
            command="定时总结",
        )

        store = Store()

        if all_enabled:
            logger.debug(
                "检测到-all参数，准备取消所有群组的定时总结", command="定时总结"
            )

            try:
                success, result_msg, _, _ = await handle_global_summary_remove(store)
                await bot.send(event, result_msg)
                return

            except FinishedException:
                logger.debug("处理被正常终止", command="定时总结")
                return
            except Exception as e:
                logger.error(
                    f"取消全局定时总结时发生异常: {str(e)}",
                    command="定时总结",
                    exc_info=True,
                )
                await bot.send(event, f"取消全局定时总结失败: {str(e)}")
                return

        logger.debug("执行单群取消流程", command="定时总结")

        group_id = None
        if target_group_id is not None:
            group_id = target_group_id
            logger.debug(
                f"从-g参数获取到群号: {group_id}", command="定时总结", group_id=group_id
            )
        else:
            if isinstance(event, GroupMessageEvent):
                group_id = event.group_id
                logger.debug(
                    f"使用当前群号: {group_id}", command="定时总结", group_id=group_id
                )
            else:
                logger.warning("私聊取消但未指定有效群号", command="定时总结")
                await bot.send(
                    event,
                    "私聊取消定时总结时，必须通过 -g 选项指定目标群号。",
                    command="定时总结",
                )
                return

        try:
            logger.debug(
                f"验证群 {group_id} 是否存在", command="定时总结", group_id=group_id
            )
            group_info = await bot.get_group_info(group_id=group_id)
            if not group_info:
                logger.warning(
                    f"群 {group_id} 不存在或Bot不在该群中",
                    command="定时总结",
                    group_id=group_id,
                )
                await bot.send(
                    event, f"群 {group_id} 不存在或Bot不在该群中。", command="定时总结"
                )
                return
        except Exception as e:
            logger.error(
                f"获取群 {group_id} 信息失败: {str(e)}",
                command="定时总结",
                group_id=group_id,
            )
            await bot.send(event, f"获取群信息失败: {str(e)}", command="定时总结")
            return

        if not store.get(group_id):
            logger.warning(
                f"群 {group_id} 未设置定时总结", command="定时总结", group_id=group_id
            )
            await bot.send(event, f"群 {group_id} 未设置定时总结。", command="定时总结")
            return

        store.remove(group_id)
        logger.debug(
            f"已从存储中移除群 {group_id} 的定时总结设置",
            command="定时总结",
            group_id=group_id,
        )

        job_id = f"summary_group_{group_id}"
        try:
            from nonebot_plugin_apscheduler import scheduler

            scheduler.remove_job(job_id)
            logger.debug(
                f"已从调度器中移除群 {group_id} 的定时任务",
                command="定时总结",
                group_id=group_id,
            )
        except Exception as e:
            logger.warning(
                f"移除群 {group_id} 的定时任务时出错: {str(e)}",
                command="定时总结",
                group_id=group_id,
                e=e,
            )

        result_msg = (
            f"'已取消群 {group_id} 的定时总结。', command='定时总结', group_id=group_id"
        )
        logger.debug(
            f"单群取消完成，响应消息: {result_msg}",
            command="定时总结",
            group_id=group_id,
        )
        await bot.send(event, result_msg, command="定时总结")
    except Exception as e:

        logger.error(
            f"处理取消定时总结命令时发生异常: {str(e)}",
            command="定时总结",
            exc_info=True,
        )
        logger.error(traceback.format_exc())
        await bot.send(event, f"取消定时总结失败: {str(e)}", command="定时总结")


async def check_scheduler_status_handler(
    bot: Bot, event: Union[GroupMessageEvent, PrivateMessageEvent], target: MsgTarget
):
    from nonebot_plugin_apscheduler import scheduler
    from ..store import Store
    import traceback

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
                logger.warning(
                    f"存储中发现无效的 group_id: {group_id_str}", command="调度状态"
                )
                continue

            data = store.get(group_id_int)
            if data:
                hour = data.get("hour", 0)
                minute = data.get("minute", 0)
                least_count = data.get(
                    "least_message_count",
                    Config.get("summary_group").get("SUMMARY_MAX_LENGTH"),
                )

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
                            command="调度状态",
                            e=tz_e,
                        )
                        next_run = job.next_run_time.strftime(
                            "%Y-%m-%d %H:%M:%S (原始时区)"
                        )

                status_msg += f"群 {group_id_int}：每天 {hour:02d}:{minute:02d}，最少 {least_count} 条消息，下次执行：{next_run}\n"

        await UniMessage.text(status_msg).send(target)

    except Exception as e:
        logger.error(
            f"检查调度器状态时发生异常: {str(e)}", command="全局定时总结", exc_info=True
        )
        await UniMessage.text(f"检查调度器状态失败: {str(e)}").send(target)


async def handle_summary_status(
    bot: Bot, event: Union[GroupMessageEvent, PrivateMessageEvent]
):
    from nonebot_plugin_apscheduler import scheduler

    try:
        is_superuser = await SUPERUSER(bot, event)
        store = Store()
        group_count = len(store.get_all_groups())

        if group_count == 0:
            await bot.send(event, "当前没有任何群设置了定时总结。")
            return

        status_msg = f"当前共有 {group_count} 个群设置了定时总结：\n"

        if not is_superuser and isinstance(event, GroupMessageEvent):
            group_id = event.group_id
            settings = store.get(group_id)
            if settings:
                hour = settings.get("hour", 0)
                minute = settings.get("minute", 0)
                least_count = settings.get("least_message_count", 200)
                job_id = f"summary_group_{group_id}"
                job = scheduler.get_job(job_id)
                next_run = job.next_run_time if job else "未调度"
                status_msg = f"本群（{group_id}）的定时总结设置：\n每天 {hour:02d}:{minute:02d}，最少 {least_count} 条消息，下次执行：{next_run}"
            else:
                status_msg = "本群未设置定时总结。"

        elif is_superuser:

            all_jobs = {
                job.id: job
                for job in scheduler.get_jobs()
                if job.id.startswith("summary_group_")
            }

            count = 0
            for group_id in store.get_all_groups():
                if count >= 10:
                    status_msg += f"...等更多群组（共 {group_count} 个）\n"
                    break

                settings = store.get(int(group_id))
                if not settings:
                    continue

                hour = settings.get("hour", 0)
                minute = settings.get("minute", 0)
                least_count = settings.get("least_message_count", 200)
                job_id = f"summary_group_{group_id}"
                job = all_jobs.get(job_id)
                next_run = job.next_run_time if job else "未调度"
                status_msg += f"群 {group_id}：每天 {hour:02d}:{minute:02d}，最少 {least_count} 条消息，下次执行：{next_run}\n"
                count += 1

        await bot.send(event, status_msg)

    except Exception as e:
        logger.error(f"检查调度器状态时发生异常: {str(e)}", command="全局定时总结", e=e)
        logger.error(traceback.format_exc(), command="全局定时总结")
        await bot.send(event, f"检查调度器状态失败: {str(e)}")


async def handle_summary_cancel(
    bot: Bot,
    event: Union[GroupMessageEvent, PrivateMessageEvent],
    result: CommandResult,
):
    
    try:
        bot_id = bot.self_id
        user_id = event.get_user_id()
        group_id = event.group_id if isinstance(event, GroupMessageEvent) else None

        
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} is inactive, skipping command.",
                command="取消定时",
                session=user_id,
            )
            return  

        
        if await BotConsole.is_block_plugin(bot_id, "summary_group"):
            logger.info(
                f"Plugin 'summary_group' is blocked for Bot {bot_id}.",
                command="取消定时",
                session=user_id,
            )
            return  

        
        if group_id and await GroupConsole.is_block_plugin(group_id, "summary_group"):
            logger.info(
                f"Plugin 'summary_group' is blocked for Group {group_id}.",
                command="取消定时",
                session=user_id,
                group_id=group_id,
            )
            await bot.send(event, "群聊总结功能在本群已被禁用。")
            return

        
        if group_id and await BanConsole.is_ban(None, group_id):
            logger.info(
                f"Group {group_id} is banned.", command="取消定时", group_id=group_id
            )
            return  

        
        if group_id and await BanConsole.is_ban(user_id, group_id):
            logger.info(
                f"User {user_id} is banned in Group {group_id}.",
                command="取消定时",
                session=user_id,
                group_id=group_id,
            )
            return  

        
        logger.debug(
            f"用户 {user_id} 触发了取消定时命令",
            command="取消定时",
            session=user_id,
            group_id=group_id,
        )

    except Exception as e:
        logger.error(
            f"执行命令前检查出错: {e}",
            command="取消定时",
            session=event.get_user_id(),
            group_id=getattr(event, "group_id", None),
            e=e,
        )
        await bot.send(event, "执行命令前检查出错，请联系管理员。")
        return
