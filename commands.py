from arclet.alconna import Alconna, Args, CommandMeta, Field, MultiVar, Option
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import At, Text, on_alconna

from zhenxun.builtin_plugins.llm_manager import llm_cmd
from zhenxun.builtin_plugins.superuser.plugin_config_manager import pconf_cmd
from zhenxun.configs.config import Config
from zhenxun.utils.rules import is_allowed_call

base_config = Config.get("summary_group")


summary_group = on_alconna(
    Alconna(
        "总结",
        Args[
            "message_count",
            [int, "当天"],
            Field(
                completion=lambda: (
                    f"输入消息数量 ({base_config.get('SUMMARY_MIN_LENGTH', 1)}-"
                    f"{base_config.get('SUMMARY_MAX_LENGTH', 1000)})"
                ),
            ),
        ],
        Option(
            "-p|--prompt",
            Args["style", str],
            help_text="指定总结风格，如：锐评, 正式",
        ),
        Option(
            "-g",
            Args["target_group_id", int],
            help_text="指定群号 (需要超级用户权限)",
        ),
        Args[
            "parts?",
            MultiVar(At | Text),
        ],
        meta=CommandMeta(
            compact=True,
            strict=False,
            description="生成群聊总结",
            usage=(
                "总结 <消息数量> [-p|--prompt 风格] [-g 群号] [@用户/内容过滤...]\n"
                "消息数量范围: "
                f"{base_config.get('SUMMARY_MIN_LENGTH', 1)} - "
                f"{base_config.get('SUMMARY_MAX_LENGTH', 1000)}\n"
                "说明: -g 仅限超级用户"
            ),
        ),
    ),
    rule=is_allowed_call(),
    priority=15,
    block=True,
)

summary_config_cmd = on_alconna(
    Alconna("总结配置"),
    permission=SUPERUSER,
    priority=5,
    block=True,
)

llm_cmd.shortcut("总结模型 列表", command="llm list", prefix=True)

pconf_cmd.shortcut(
    r"总结模型 设置 (?P<model_name>\S+)",
    command="pconf",
    arguments=[
        "set",
        "SUMMARY_MODEL_NAME={model_name}",
        "--global",
        "-p",
        "summary_group",
    ],
    prefix=True,
)

pconf_cmd.shortcut(
    r"总结模型 移除",
    command="pconf",
    arguments=["reset", "SUMMARY_MODEL_NAME", "--global", "-p", "summary_group"],
    prefix=True,
)

pconf_cmd.shortcut(
    r"总结风格 设置 (?P<style_name>\"[^\"]*\"|\S+)",
    command="pconf",
    arguments=[
        "set",
        "SUMMARY_DEFAULT_STYLE={style_name}",
        "--global",
        "-p",
        "summary_group",
    ],
    prefix=True,
)
pconf_cmd.shortcut(
    r"总结风格 移除",
    command="pconf",
    arguments=["reset", "SUMMARY_DEFAULT_STYLE", "--global", "-p", "summary_group"],
    prefix=True,
)

pconf_cmd.shortcut(
    r"总结配置 模型 设置 (?P<model_name>\S+)\s*(?P<targets>.*)",
    command="pconf",
    arguments=[
        "set",
        "default_model_name={model_name}",
        "-p",
        "summary_group",
        "{targets}",
    ],
    prefix=True,
)
pconf_cmd.shortcut(
    r"总结配置 模型 移除\s*(?P<targets>.*)",
    command="pconf",
    arguments=["reset", "default_model_name", "-p", "summary_group", "{targets}"],
    prefix=True,
)

pconf_cmd.shortcut(
    r"总结配置 风格 设置 (?P<style_name>\"[^\"]*\"|\S+)\s*(?P<targets>.*)",
    command="pconf",
    arguments=["set", "default_style={style_name}", "-p", "summary_group", "{targets}"],
    prefix=True,
)
pconf_cmd.shortcut(
    r"总结配置 风格 移除\s*(?P<targets>.*)",
    command="pconf",
    arguments=["reset", "default_style", "-p", "summary_group", "{targets}"],
    prefix=True,
)
