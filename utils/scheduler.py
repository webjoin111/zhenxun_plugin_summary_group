import asyncio
from datetime import datetime, time
from zhenxun.services.log import logger
from nonebot import require
from nonebot_plugin_alconna.uniseg import Target

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from zhenxun.configs.config import Config
from ..store import Store


summary_semaphore = asyncio.Semaphore(2)
summary_queue = asyncio.Queue()
task_processor_started = False


class SummaryException(Exception):
    pass


class ScheduleException(SummaryException):
    pass


async def scheduler_send_summary(
    group_id: int, least_message_count: int, style: str = None
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
            f"将群 {group_id} 的任务添加到队列失败: {str(e)}",
            command="scheduler",
            group_id=group_id,
            e=e,
        )


async def update_single_group_schedule(group_id: int, data: dict) -> tuple:
    try:

        hour = data.get("hour", 0)
        minute = data.get("minute", 0)
        least_message_count = data.get("least_message_count", 1000)
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
                f"添加定时任务时出错: {e}", command="scheduler", group_id=group_id, e=e
            )
            return False, None

        updated_job = scheduler.get_job(job_id)
        if updated_job:
            logger.debug(
                f"群 {group_id} 的定时任务已更新，下次执行时间: {updated_job.next_run_time}",
                command="scheduler",
                group_id=group_id,
            )
            return True, updated_job
        else:
            logger.error(
                f"群 {group_id} 的定时任务更新失败",
                command="scheduler",
                group_id=group_id,
            )
            return False, None

    except Exception as e:
        logger.error(
            f"更新群 {group_id} 的定时任务时出错: {str(e)}",
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


async def process_summary_queue() -> None:
    from nonebot import get_bot
    import asyncio
    import contextlib
    from datetime import datetime

    from zhenxun.models.bot_console import BotConsole
    from zhenxun.models.group_console import GroupConsole
    from zhenxun.models.ban_console import BanConsole
    from zhenxun.services.log import logger
    from zhenxun.configs.config import Config
    from zhenxun.models.statistics import Statistics

    from .summary import send_summary, messages_summary
    from .message import process_message

    logger.debug("总结任务队列处理器已启动，开始监听队列", command="队列处理器")

    concurrent_tasks = 2
    try:
        base_config = Config.get("summary_group")
        concurrent_tasks = base_config.get("CONCURRENT_TASKS", 2)
    except Exception as e:
        logger.warning(f"获取并发任务配置失败，使用默认值 2: {e}", command="队列处理器")

    semaphore = asyncio.Semaphore(concurrent_tasks)

    while True:
        try:
            queue_size = summary_queue.qsize()
            if queue_size > 0:
                logger.debug(
                    f"队列处理器等待任务，当前队列大小: {queue_size}",
                    command="队列处理器",
                )

            try:

                group_id, least_message_count, style, metadata = await asyncio.wait_for(
                    summary_queue.get(), timeout=60
                )

                task_start_time = datetime.now()
                task_id = f"summary_task_{group_id}_{task_start_time.timestamp()}"

                logger.debug(
                    f"队列处理器接收到任务 [{task_id}]："
                    f"群 {group_id}，最少消息数 {least_message_count}, 风格: {style or '默认'}",
                    command="队列处理器",
                    group_id=group_id,
                )

                group_id_str = str(group_id)
                plugin_name = "summary_group"

                async with semaphore:
                    logger.debug(
                        f"开始处理任务 [{task_id}]: 群 {group_id} 的总结",
                        command="队列处理器",
                        group_id=group_id,
                    )

                    try:

                        try:
                            bot = get_bot()
                            bot_id = bot.self_id

                            if not await BotConsole.get_bot_status(bot_id):
                                logger.info(
                                    f"Bot {bot_id} is inactive, skipping task [{task_id}].",
                                    command="队列处理器",
                                    group_id=group_id_str,
                                )
                                summary_queue.task_done()
                                continue

                            if await BotConsole.is_block_plugin(
                                bot_id, plugin_name
                            ):
                                logger.info(
                                    f"Plugin '{plugin_name}' is blocked for Bot {bot_id}, skipping task [{task_id}].",
                                    command="队列处理器",
                                    group_id=group_id_str,
                                )
                                summary_queue.task_done()
                                continue

                            if await GroupConsole.is_block_plugin(
                                group_id_str, plugin_name
                            ):
                                logger.info(
                                    f"Plugin '{plugin_name}' is blocked for Group {group_id_str}, skipping task [{task_id}].",
                                    command="队列处理器",
                                    group_id=group_id_str,
                                )
                                summary_queue.task_done()
                                continue

                            if await BanConsole.is_ban(None, group_id_str):
                                logger.info(
                                    f"Group {group_id_str} is banned, skipping task [{task_id}].",
                                    command="队列处理器",
                                    group_id=group_id_str,
                                )
                                summary_queue.task_done()
                                continue

                        except Exception as check_e:
                            logger.error(
                                f"[{task_id}] 执行任务前检查出错: {check_e}",
                                command="队列处理器",
                                group_id=group_id_str,
                                e=check_e,
                            )
                            summary_queue.task_done()
                            continue

                        logger.debug(
                            f"[{task_id}] 获取群 {group_id} 的消息历史，请求 {least_message_count} 条消息",
                            command="队列处理器",
                            group_id=group_id,
                        )
                        try:
                            response = await bot.get_group_msg_history(
                                group_id=group_id, count=least_message_count
                            )
                            messages = response.get("messages", [])
                            message_count = len(messages)
                            logger.debug(
                                f"[{task_id}] 群 {group_id} 获取到 {message_count} 条消息",
                                command="队列处理器",
                                group_id=group_id,
                            )

                            base_config = Config.get("summary_group")
                            min_len_required = base_config.get("SUMMARY_MIN_LENGTH")
                            if message_count < min_len_required:
                                logger.debug(
                                    f"[{task_id}] 群 {group_id} 消息数量不足 "
                                    f"{message_count}/{min_len_required}，跳过总结",
                                    command="队列处理器",
                                    group_id=group_id,
                                )
                                summary_queue.task_done()
                                continue
                        except Exception as e:
                            logger.error(
                                f"[{task_id}] 获取群 {group_id} 消息历史失败: {e}",
                                command="队列处理器",
                                group_id=group_id,
                                e=e,
                            )
                            summary_queue.task_done()
                            continue

                        logger.debug(
                            f"[{task_id}] 处理群 {group_id} 的消息内容",
                            command="队列处理器",
                            group_id=group_id,
                        )
                        try:

                            processed_data_tuple = await process_message(
                                messages, bot, group_id
                            )
                            processed_messages = processed_data_tuple[0]
                            user_cache = processed_data_tuple[1]

                            if not processed_messages:
                                logger.warning(
                                    f"[{task_id}] 群 {group_id} 处理后没有有效消息，跳过总结",
                                    command="队列处理器",
                                    group_id=group_id,
                                )
                                summary_queue.task_done()
                                continue

                            logger.debug(
                                f"[{task_id}] 处理得到 {len(processed_messages)} 条有效消息",
                                command="队列处理器",
                                group_id=group_id,
                            )
                        except Exception as e:
                            logger.error(
                                f"[{task_id}] 处理群 {group_id} 的消息内容失败: {e}",
                                command="队列处理器",
                                group_id=group_id,
                                e=e,
                            )
                            summary_queue.task_done()
                            continue

                        logger.debug(
                            f"[{task_id}] 开始为群 {group_id} 生成总结，"
                            f"处理 {len(processed_messages)} 条有效消息, 风格: {style or '默认'}",
                            command="队列处理器",
                            group_id=group_id,
                        )
                        try:

                            summary = await messages_summary(
                                messages=processed_messages, style=style
                            )

                            logger.debug(
                                f"[{task_id}] 群 {group_id} (风格: {style or '默认'}) 总结生成成功，长度: {len(summary)}",
                                command="队列处理器",
                                group_id=group_id,
                            )
                        except Exception as e:
                            logger.error(
                                f"[{task_id}] 为群 {group_id} 生成总结失败: {e}",
                                command="队列处理器",
                                group_id=group_id,
                                e=e,
                            )
                            summary_queue.task_done()
                            continue

                        logger.debug(
                            f"[{task_id}] 向群 {group_id} 发送总结",
                            command="队列处理器",
                            group_id=group_id,
                        )
                        try:
                            msg_target = Target.group(group_id=group_id)
                            send_success = await send_summary(bot, msg_target, summary)
                            if send_success:
                                logger.debug(
                                    f"[{task_id}] 群 {group_id} 定时总结发送完成",
                                    command="队列处理器",
                                    group_id=group_id,
                                )

                                try:
                                    await Statistics.create(
                                        user_id=str(bot_id),
                                        group_id=str(group_id),
                                        plugin_name="summary_group",
                                        bot_id=str(bot_id),
                                    )
                                    logger.debug(
                                        f"[{task_id}] 记录定时任务统计成功: group={group_id}",
                                        command="队列处理器",
                                    )
                                except Exception as stat_e:
                                    logger.error(
                                        f"[{task_id}] 记录定时任务统计失败: {stat_e}",
                                        command="队列处理器",
                                        group_id=group_id,
                                        e=stat_e,
                                    )

                            else:
                                logger.warning(
                                    f"[{task_id}] 群 {group_id} 定时总结发送失败",
                                    command="队列处理器",
                                    group_id=group_id,
                                )

                        except Exception as e:
                            logger.error(
                                f"[{task_id}] 向群 {group_id} 发送总结时发生异常: {e}",
                                command="队列处理器",
                                group_id=group_id,
                                e=e,
                            )
                    except Exception as e:
                        logger.error(
                            f"[{task_id}] 处理群 {group_id} 总结任务时出错: {str(e)}",
                            command="队列处理器",
                            group_id=group_id,
                            e=e,
                        )
                    finally:
                        task_end_time = datetime.now()
                        execution_time = (
                            task_end_time - task_start_time
                        ).total_seconds()
                        logger.debug(
                            f"[{task_id}] 任务执行完成，耗时: {execution_time:.2f}秒",
                            command="队列处理器",
                            group_id=group_id,
                        )
                        summary_queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(
                    f"从队列获取任务时出错: {str(e)}", command="队列处理器", e=e
                )
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(
                f"任务队列处理器遇到未处理异常: {str(e)}", command="队列处理器", e=e
            )
            await asyncio.sleep(10)


def set_scheduler() -> None:
    global task_processor_started
    import asyncio
    from .health import check_system_health

    try:

        if not task_processor_started:

            queue_task = asyncio.create_task(process_summary_queue())
            queue_task.set_name("summary_queue_processor")
            task_processor_started = True
            logger.debug("总结任务队列处理器已启动", command="scheduler")

            logger.debug(
                f"队列处理器任务状态: {queue_task.done() and '已完成' or '运行中'}"
            )
        else:
            logger.debug("总结任务队列处理器已在运行中", command="scheduler")

        if not scheduler.running:
            scheduler.start()
            logger.debug("调度器已启动", command="scheduler")

        processor_status = verify_processor_status()
        logger.debug(
            f"队列处理器状态检查: 发现 {processor_status} 个处理器任务",
            command="scheduler",
        )

        store = Store()

        cleaned_count = store.cleanup_invalid_groups()
        if cleaned_count > 0:
            logger.debug(
                f"自动清理了 {cleaned_count} 个无效的群配置", command="scheduler"
            )

        group_configs = store.data.items()
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
                least_message_count = data.get(
                    "least_message_count",
                    Config.get("summary_group").get("SUMMARY_MAX_LENGTH"),
                )
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

                store.remove(int(group_id_str) if group_id_str.isdigit() else 0)

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

        asyncio.create_task(check_system_health())

    except Exception as e:
        logger.error(f"设置定时任务时出错: {e}", command="scheduler")
