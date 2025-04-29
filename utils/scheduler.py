import asyncio
from datetime import datetime

from nonebot import get_bot, require
from nonebot.adapters import Bot
from nonebot_plugin_alconna.uniseg import Target

from zhenxun.services.log import logger

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.statistics import Statistics

from .. import base_config
from ..store import store
from .exceptions import (
    MessageFetchException,
    MessageProcessException,
    ModelException,
)
from .health import check_system_health
from .message import process_message
from .summary import messages_summary, send_summary

summary_semaphore = asyncio.Semaphore(base_config.get("CONCURRENT_TASKS", 2))
summary_queue = asyncio.Queue()
task_processor_started = False


async def scheduler_send_summary(
    group_id: int, least_message_count: int, style: str | None = None
) -> None:
    try:
        logger.debug(
            f"正在将群 {group_id} 的总结任务添加到队列，消息数量: {least_message_count}, 风格: {style or '默认'}",
            command="scheduler",
            group_id=group_id,
        )

        task_metadata = {
            "group_id": group_id,
            "least_message_count": least_message_count,
            "style": style,
            "scheduled_time": datetime.now().isoformat(),
        }

        await summary_queue.put((group_id, least_message_count, style, task_metadata))
        logger.debug(
            f"群 {group_id} 的总结任务已成功加入队列",
            command="scheduler",
            group_id=group_id,
        )

        processor_status = verify_processor_status()
        if processor_status == 0:
            logger.warning("未发现队列处理器，正在尝试启动...", command="scheduler")

    except Exception as e:
        logger.error(
            f"将群 {group_id} 的任务添加到队列失败: {e!s}",
            command="scheduler",
            group_id=group_id,
            e=e,
        )


async def update_single_group_schedule(group_id: int, data: dict) -> tuple:
    try:
        hour = data.get("hour", 0)
        minute = data.get("minute", 0)

        default_least_count = base_config.get("SUMMARY_MAX_LENGTH", 1000)
        least_message_count = data.get("least_message_count", default_least_count)
        style = data.get("style", None)

        second = group_id % 60

        job_id = f"summary_group_{group_id}"

        existing_job = scheduler.get_job(job_id)
        if existing_job:
            logger.debug(
                f"更新群 {group_id} 的定时总结任务: {hour:02d}:{minute:02d}:{second:02d}, 风格: {style or '默认'}",
                command="scheduler",
                group_id=group_id,
            )
        else:
            logger.debug(
                f"创建群 {group_id} 的定时总结任务: {hour:02d}:{minute:02d}:{second:02d}, 风格: {style or '默认'}",
                command="scheduler",
                group_id=group_id,
            )

        try:
            scheduler.add_job(
                scheduler_send_summary,
                "cron",
                hour=hour,
                minute=minute,
                second=second,
                args=(group_id, least_message_count, style),
                id=job_id,
                replace_existing=True,
                timezone="Asia/Shanghai",
            )
        except Exception as e:
            logger.error(
                f"添加/更新定时任务时出错: {e}",
                command="scheduler",
                group_id=group_id,
                e=e,
            )
            return False, None

        updated_job = scheduler.get_job(job_id)
        if updated_job:
            try:
                save_data = {
                    "hour": hour,
                    "minute": minute,
                    "least_message_count": least_message_count,
                    "style": style,
                }
                if not await store.set(group_id, save_data):
                    logger.error(
                        f"群 {group_id} 的定时任务设置保存失败",
                        command="scheduler",
                        group_id=group_id,
                    )
                else:
                    logger.debug(
                        f"群 {group_id} 的定时任务设置已保存",
                        command="scheduler",
                        group_id=group_id,
                    )
            except Exception as store_e:
                logger.error(
                    f"保存群 {group_id} 设置时出错: {store_e!s}",
                    command="scheduler",
                    group_id=group_id,
                    e=store_e,
                )

            logger.debug(
                f"群 {group_id} 的定时任务已更新/创建，下次执行时间: {updated_job.next_run_time}",
                command="scheduler",
                group_id=group_id,
            )
            return True, updated_job
        else:
            logger.error(
                f"群 {group_id} 的定时任务更新/创建后未能找到",
                command="scheduler",
                group_id=group_id,
            )
            return False, None

    except Exception as e:
        logger.error(
            f"更新群 {group_id} 的定时任务时出错: {e!s}",
            command="scheduler",
            group_id=group_id,
            e=e,
        )
        return False, None


def verify_processor_status() -> int:
    global task_processor_started
    import asyncio

    all_tasks = asyncio.all_tasks()
    processor_tasks = [
        t for t in all_tasks if t.get_name() == "summary_queue_processor"
    ]

    logger.debug(f"当前队列处理器任务数量: {len(processor_tasks)}", command="scheduler")

    running_tasks = 0
    for task in processor_tasks:
        if task.done():
            if task.exception():
                logger.error(
                    f"队列处理器异常: {task.exception()}",
                    command="scheduler",
                    group_id=task.get_name(),
                )
            else:
                logger.warning(
                    "队列处理器已完成但无异常",
                    command="scheduler",
                    group_id=task.get_name(),
                )

            pass
        else:
            running_tasks += 1
            logger.debug(
                "队列处理器正在运行中", command="scheduler", group_id=task.get_name()
            )

    if running_tasks == 0:
        logger.warning("未找到运行中的队列处理器任务，正在创建...", command="scheduler")
        try:
            new_task = asyncio.create_task(process_summary_queue())
            new_task.set_name("summary_queue_processor")
            task_processor_started = True
            logger.debug("队列处理器已创建", command="scheduler")
            running_tasks = 1
        except Exception as e:
            logger.error(f"创建队列处理器任务失败: {e}", command="scheduler", e=e)

    return running_tasks


def check_scheduler_status() -> list:
    jobs = scheduler.get_jobs()
    logger.debug(f"当前调度器中的任务数量: {len(jobs)}", command="scheduler")
    for job in jobs:
        logger.debug(
            f"任务ID: {job.id}, 下次运行时间: {job.next_run_time}", command="scheduler"
        )
    return jobs


async def _perform_task_pre_checks(bot: Bot, group_id_str: str, task_id: str) -> bool:
    """执行任务前的 Bot 和群组状态检查"""
    plugin_name = "summary_group"
    bot_id = bot.self_id
    try:
        if not await BotConsole.get_bot_status(bot_id):
            logger.info(
                f"Bot {bot_id} 未激活, 跳过任务 [{task_id}].", group_id=group_id_str
            )
            return False
        if await BotConsole.is_block_plugin(bot_id, plugin_name):
            logger.info(
                f"插件 '{plugin_name}' 被 Bot {bot_id} 屏蔽, 跳过任务 [{task_id}].",
                group_id=group_id_str,
            )
            return False
        if await GroupConsole.is_block_plugin(group_id_str, plugin_name):
            logger.info(
                f"插件 '{plugin_name}' 被群 {group_id_str} 屏蔽, 跳过任务 [{task_id}].",
                group_id=group_id_str,
            )
            return False
        if await BanConsole.is_ban(None, group_id_str):
            logger.info(
                f"群 {group_id_str} 被封禁, 跳过任务 [{task_id}].",
                group_id=group_id_str,
            )
            return False
        return True
    except Exception as check_e:
        logger.error(
            f"[{task_id}] 执行任务前检查出错: {check_e}",
            group_id=group_id_str,
            e=check_e,
        )
        return False


async def _fetch_and_process_task_messages(
    bot: Bot, group_id: int, least_message_count: int, task_id: str
) -> tuple[list[dict[str, str]] | None, int]:
    """获取、过滤和处理消息"""
    logger.debug(
        f"[{task_id}] 获取群 {group_id} 的消息历史，请求 {least_message_count} 条消息",
        group_id=group_id,
    )
    message_count = 0
    try:
        response = await bot.get_group_msg_history(
            group_id=group_id, count=least_message_count
        )
        messages = response.get("messages", [])
        message_count = len(messages)
        logger.debug(
            f"[{task_id}] 群 {group_id} 获取到 {message_count} 条消息",
            group_id=group_id,
        )

        min_len_required = base_config.get("SUMMARY_MIN_LENGTH", 50)
        if message_count < min_len_required:
            logger.debug(
                f"[{task_id}] 群 {group_id} 消息数量不足 {message_count}/{min_len_required}，跳过总结",
                group_id=group_id,
            )
            return None, message_count

        logger.debug(f"[{task_id}] 处理群 {group_id} 的消息内容", group_id=group_id)
        processed_data_tuple = await process_message(messages, bot, group_id)
        processed_messages = processed_data_tuple[0]

        if not processed_messages:
            logger.warning(
                f"[{task_id}] 群 {group_id} 处理后没有有效消息，跳过总结",
                group_id=group_id,
            )
            return None, message_count

        logger.debug(
            f"[{task_id}] 处理得到 {len(processed_messages)} 条有效消息",
            group_id=group_id,
        )
        return processed_messages, message_count

    except (MessageFetchException, MessageProcessException) as e:
        logger.error(
            f"[{task_id}] 获取或处理群 {group_id} 消息失败: {e}", group_id=group_id, e=e
        )
        return None, message_count
    except Exception as e:
        logger.error(
            f"[{task_id}] 获取或处理群 {group_id} 消息时发生未知错误: {e}",
            group_id=group_id,
            e=e,
        )
        return None, message_count


async def _generate_and_send_task_summary(
    bot: Bot,
    group_id: int,
    processed_messages: list[dict[str, str]],
    style: str | None,
    task_id: str,
) -> bool:
    """生成并发送总结"""
    logger.debug(
        f"[{task_id}] 开始为群 {group_id} 生成总结，处理 {len(processed_messages)} 条有效消息, 风格: {style or '默认'}",
        group_id=group_id,
    )
    try:
        msg_target = Target.group(group_id=group_id)
        summary = await messages_summary(
            target=msg_target,
            messages=processed_messages,
            style=style,
        )
        logger.debug(
            f"[{task_id}] 群 {group_id} (风格: {style or '默认'}) 总结生成成功，长度: {len(summary)}",
            group_id=group_id,
        )

        logger.debug(f"[{task_id}] 向群 {group_id} 发送总结", group_id=group_id)
        send_success = await send_summary(bot, msg_target, summary)
        if send_success:
            logger.debug(
                f"[{task_id}] 群 {group_id} 定时总结发送完成", group_id=group_id
            )
            return True
        else:
            logger.warning(
                f"[{task_id}] 群 {group_id} 定时总结发送失败", group_id=group_id
            )
            return False

    except ModelException as e:
        logger.error(
            f"[{task_id}] 为群 {group_id} 生成总结失败 (模型错误): {e}",
            group_id=group_id,
            e=e,
        )
        return False
    except Exception as e:
        logger.error(
            f"[{task_id}] 生成或发送群 {group_id} 总结时发生未知错误: {e}",
            group_id=group_id,
            e=e,
        )
        return False


async def _record_task_statistics(
    metadata: dict,
    group_id: int,
    message_count: int,
    style: str | None,
    status: str,
    error_message: str | None = None,
):
    """记录任务统计信息"""
    bot_id_str = "N/A"
    try:
        bot = get_bot()
        bot_id_str = bot.self_id
    except Exception:
        logger.warning("无法获取 Bot 实例以记录 Bot ID")

    task_id = (
        f"summary_task_{group_id}_{metadata.get('scheduled_time', 'unknown_time')}"
    )
    try:
        stat_data = {
            "user_id": str(metadata.get("user_id", "scheduler")),
            "group_id": str(group_id),
            "plugin_name": "summary_group_scheduler",
            "bot_id": bot_id_str,
            "message_count": message_count,
            "style": style,
            "target_users": [],
            "content_filter": None,
            "status": status,
        }
        if error_message:
            stat_data["error_message"] = error_message[:250]

        await Statistics.create(**stat_data)
        logger.debug(
            f"记录统计 ({status}): group={group_id}, task={task_id}",
            command="队列处理器",
        )
    except Exception as stat_e:
        logger.error(
            f"记录统计失败 for group {group_id}: {stat_e}, task={task_id}",
            command="队列处理器",
            e=stat_e,
        )


async def process_summary_queue() -> None:
    """处理待执行的总结任务队列 (重构版)"""
    logger.debug("总结任务队列处理器已启动，开始监听队列", command="队列处理器")
    concurrent_tasks = base_config.get("CONCURRENT_TASKS", 2)
    semaphore = asyncio.Semaphore(concurrent_tasks)

    while True:
        group_id = None
        task_id = "unknown"
        metadata = {}
        processed_messages = None
        message_count = 0
        style = None

        try:
            queue_size = summary_queue.qsize()
            if queue_size > 0:
                logger.debug(
                    f"队列处理器等待任务，当前队列大小: {queue_size}",
                    command="队列处理器",
                )

            try:
                group_id, least_message_count, style, metadata = await asyncio.wait_for(
                    summary_queue.get(), timeout=60.0
                )
            except asyncio.TimeoutError:
                continue

            task_start_time = datetime.now()
            task_id = f"summary_task_{group_id}_{task_start_time.timestamp()}"
            group_id_str = str(group_id)

            logger.debug(
                f"队列处理器接收到任务 [{task_id}]：群 {group_id}，最少消息数 {least_message_count}, 风格: {style or '默认'}",
                group_id=group_id,
            )

            async with semaphore:
                logger.debug(
                    f"开始处理任务 [{task_id}]: 群 {group_id} 的总结", group_id=group_id
                )
                task_status = "failed_unknown"
                error_msg = None

                try:
                    try:
                        bot = get_bot()
                    except Exception as e:
                        logger.error(
                            f"[{task_id}] 获取 Bot 实例失败: {e}, 跳过任务",
                            group_id=group_id,
                            e=e,
                        )
                        task_status = "failed_get_bot"
                        error_msg = f"获取 Bot 实例失败: {e!s}"
                        await _record_task_statistics(
                            metadata, group_id, 0, style, task_status, error_msg
                        )
                        continue

                    if not await _perform_task_pre_checks(bot, group_id_str, task_id):
                        task_status = "skipped_precheck"
                        await _record_task_statistics(
                            metadata, group_id, 0, style, task_status
                        )
                        continue

                    (
                        processed_messages,
                        message_count,
                    ) = await _fetch_and_process_task_messages(
                        bot, group_id, least_message_count, task_id
                    )
                    if processed_messages is None:
                        if (
                            message_count < base_config.get("SUMMARY_MIN_LENGTH", 50)
                            and message_count > 0
                        ):
                            task_status = "skipped_msg_count"
                        else:
                            task_status = "failed_fetch_process"
                            error_msg = "获取或处理消息失败"
                        await _record_task_statistics(
                            metadata,
                            group_id,
                            message_count,
                            style,
                            task_status,
                            error_msg,
                        )
                        continue

                    send_success = await _generate_and_send_task_summary(
                        bot, group_id, processed_messages, style, task_id
                    )
                    if send_success:
                        task_status = "success"
                    else:
                        task_status = "failed_generate_send"
                        error_msg = "生成或发送总结失败"

                    await _record_task_statistics(
                        metadata,
                        group_id,
                        message_count,
                        style,
                        task_status,
                        error_msg if not send_success else None,
                    )

                except Exception as task_e:
                    logger.error(
                        f"处理任务 [{task_id}] 时发生意外错误: {task_e}",
                        group_id=group_id,
                    )
                    task_status = "failed_unexpected"
                    error_msg = f"意外错误: {task_e!s}"
                    await _record_task_statistics(
                        metadata, group_id, message_count, style, task_status, error_msg
                    )

                finally:
                    task_end_time = datetime.now()
                    duration = (task_end_time - task_start_time).total_seconds()
                    logger.debug(
                        f"任务 [{task_id}] (状态: {task_status}) 执行耗时: {duration:.2f} 秒",
                        command="队列处理器",
                    )
                    summary_queue.task_done()
                    logger.debug(
                        f"任务 [{task_id}] 处理完成，释放信号量，当前信号量值: {semaphore._value}",
                        command="队列处理器",
                    )

        except Exception as loop_e:
            logger.error(
                f"队列处理器主循环出错: {loop_e!s}", command="队列处理器"
            )
            await asyncio.sleep(10)
        finally:
            if group_id is not None:
                try:
                    summary_queue.task_done()
                except ValueError:
                    logger.warning(
                        f"任务 [{task_id}] 可能已被标记完成", command="队列处理器"
                    )
                except Exception as td_e:
                    logger.error(
                        f"标记任务 [{task_id}] 完成时出错: {td_e}",
                        command="队列处理器",
                        e=td_e,
                    )


async def set_scheduler() -> None:
    import asyncio

    global task_processor_started
    if not task_processor_started:
        logger.info(
            "初始化调度器: 启动 summary_group 队列处理器...", command="scheduler"
        )
        try:
            _task = asyncio.create_task(process_summary_queue())
            _task.set_name("summary_queue_processor")
            task_processor_started = True
            logger.info("summary_group 队列处理器已成功启动", command="scheduler")
        except Exception as e:
            logger.error(
                f"启动 summary_group 队列处理器失败: {e}", command="scheduler", e=e
            )
    else:
        logger.debug("summary_group 队列处理器已在运行", command="scheduler")

    if not scheduler.running:
        try:
            scheduler.start()
            logger.info("APScheduler 调度器已启动", command="scheduler")
        except Exception as e:
            logger.error(f"启动 APScheduler 失败: {e}", command="scheduler", e=e)

    _health_check_task = asyncio.create_task(check_system_health())
    _background_tasks.add(_health_check_task)
    _health_check_task.add_done_callback(_background_tasks.discard)

    processor_status = verify_processor_status()
    logger.debug(
        f"队列处理器状态检查: 发现 {processor_status} 个处理器任务",
        command="scheduler",
    )

    cleaned_count = await store.cleanup_invalid_groups()
    if cleaned_count > 0:
        logger.debug(f"自动清理了 {cleaned_count} 个无效的群配置", command="scheduler")

    group_configs = store.schedule_data.items()
    logger.debug(
        f"加载了 {len(group_configs)} 个群组的定时总结配置", command="scheduler"
    )

    successful_count = 0
    failed_count = 0

    for group_id_str, data in group_configs:
        try:
            group_id = int(group_id_str)

            hour = data.get("hour", 0)
            minute = data.get("minute", 0)

            default_least_count = base_config.get("SUMMARY_MAX_LENGTH", 1000)
            least_message_count = data.get("least_message_count", default_least_count)
            style = data.get("style", None)

            second = group_id % 60

            job_id = f"summary_group_{group_id}"

            existing_job = scheduler.get_job(job_id)
            if existing_job:
                logger.debug(
                    f"更新群 {group_id} 的定时总结任务: {hour:02d}:{minute:02d}:{second:02d}, 风格: {style or '默认'}",
                    command="scheduler",
                    group_id=group_id,
                )
                scheduler.remove_job(job_id)

            scheduler.add_job(
                scheduler_send_summary,
                "cron",
                hour=hour,
                minute=minute,
                second=second,
                args=(group_id, least_message_count, style),
                id=job_id,
                replace_existing=True,
                timezone="Asia/Shanghai",
            )

            successful_count += 1
            logger.debug(
                f"已设置群 {group_id} 的定时总结任务: {hour:02d}:{minute:02d}:{second:02d}, 风格: {style or '默认'}",
                command="scheduler",
                group_id=group_id,
            )

        except ValueError as e:
            logger.error(f"群号 {group_id_str} 无效: {e}", command="scheduler")
            failed_count += 1

        except Exception as e:
            logger.error(
                f"为群 {group_id_str} 设置定时任务失败: {e}", command="scheduler"
            )
            failed_count += 1

    if successful_count > 0:
        logger.debug(
            f"成功设置了 {successful_count} 个群组的定时总结任务",
            command="scheduler",
        )
    if failed_count > 0:
        logger.warning(
            f"有 {failed_count} 个群组的定时任务设置失败", command="scheduler"
        )


def remove_scheduler(group_id: int) -> bool:
    job_id = f"summary_group_{group_id}"
    try:
        scheduler.remove_job(job_id)
        logger.info(f"已移除群 {group_id} 的定时总结任务", command="scheduler")
        return True
    except Exception as e:
        logger.error(f"移除群 {group_id} 的定时任务失败: {e}", command="scheduler", e=e)
        return False


_background_tasks = set()


async def stop_tasks() -> None:
    global task_processor_started
    logger.info("正在停止所有后台任务...", command="shutdown")

    processor_tasks = [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "summary_queue_processor"
    ]
    for task in processor_tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("队列处理器已取消", command="shutdown")
            except Exception as e:
                logger.error(f"取消队列处理器时发生错误: {e}", command="shutdown", e=e)
    task_processor_started = False
    logger.debug("所有队列处理器任务已处理完毕", command="shutdown")

    if _background_tasks:
        logger.debug(f"开始取消 {len(_background_tasks)} 个其他后台任务...")
        for task in list(_background_tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug(f"任务 {task.get_name()} 已取消")
                except Exception as e:
                    logger.error(f"取消任务 {task.get_name()} 时出错: {e}", e=e)
            _background_tasks.discard(task)
        logger.debug("所有其他后台任务已取消")
    else:
        logger.debug("没有其他后台任务需要取消")

    logger.info("所有后台任务停止完成", command="shutdown")


@scheduler.scheduled_job("interval", seconds=600, id="check_health_job")
async def run_health_check() -> None:
    try:
        health_status = await check_system_health()
        logger.debug(f"系统健康检查完成: {health_status}", command="health_check")

    except Exception as e:
        logger.error(f"执行健康检查时出错: {e!s}", command="health_check", e=e)
