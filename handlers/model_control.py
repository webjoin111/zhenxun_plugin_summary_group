from typing import TYPE_CHECKING

from zhenxun.configs.config import Config
from zhenxun.services.log import logger

from .. import ai_config, base_config, summary_config
from ..model import ModelConfig, ModelDetail, ProviderConfig
from ..utils.core import key_status_store

if TYPE_CHECKING:
    from ..model import Model


def parse_provider_model_string(name_str: str | None) -> tuple[str | None, str | None]:
    """解析 'Provider/Model' 格式的字符串"""
    if not name_str or "/" not in name_str:
        return None, None
    parts = name_str.split("/", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None, None


def get_configured_providers() -> list[ProviderConfig]:
    """从配置中安全地获取 Provider 列表"""
    providers_raw = ai_config.get("PROVIDERS", [])
    if not isinstance(providers_raw, list):
        logger.error("配置项 AI.PROVIDERS 不是一个列表，将使用空列表。")
        return []

    providers = []
    for i, item in enumerate(providers_raw):
        if isinstance(item, dict):
            try:
                provider_conf = ProviderConfig(**item)

                if not all(
                    [
                        provider_conf.name,
                        provider_conf.api_key,
                        provider_conf.api_base,
                        provider_conf.models,
                    ]
                ):
                    logger.warning(
                        f"配置文件中第 {i + 1} 个 Provider 缺少必要的字段 (name, api_key, api_base, models)，已跳过。"
                    )
                    continue
                if not provider_conf.api_key or (
                    isinstance(provider_conf.api_key, list) and not any(provider_conf.api_key)
                ):
                    logger.warning(
                        f"配置文件中第 {i + 1} 个 Provider 的 api_key 无效 (为空或空列表)，已跳过。"
                    )
                    continue
                if not all(detail.model_name for detail in provider_conf.models):
                    logger.warning(
                        f"配置文件中第 {i + 1} 个 Provider 的 models 列表包含无效的模型详情 (model_name 为空)，已跳过。"
                    )
                    continue

                providers.append(provider_conf)
            except Exception as e:
                logger.warning(f"解析配置文件中第 {i + 1} 个 Provider 时出错: {e}，已跳过。配置: {item}")
        else:
            logger.warning(f"配置文件 AI.PROVIDERS 中第 {i + 1} 项不是字典格式，已跳过。")
    return providers


def find_model(provider_name: str, model_detail_name: str) -> tuple[ProviderConfig, ModelDetail] | None:
    """在配置中查找指定的 Provider 和 ModelDetail"""
    providers = get_configured_providers()
    for provider in providers:
        if provider.name.lower() == provider_name.lower():
            for model_detail in provider.models:
                if model_detail.model_name.lower() == model_detail_name.lower():
                    return provider, model_detail
    return None


def get_configured_models() -> list[ModelConfig]:
    """从 Provider 配置中生成 ModelConfig 列表（仅用于兼容旧代码）"""
    providers = get_configured_providers()
    models = []

    for provider in providers:
        for model_detail in provider.models:
            model_conf = ModelConfig(
                name=f"{provider.name}/{model_detail.model_name}",
                api_key=provider.api_key,
                model_name=model_detail.model_name,
                api_base=provider.api_base,
                api_type=provider.api_type,
                openai_compat=provider.openai_compat,
                max_tokens=model_detail.max_tokens
                if model_detail.max_tokens is not None
                else provider.max_tokens,
                temperature=model_detail.temperature
                if model_detail.temperature is not None
                else provider.temperature,
            )
            models.append(model_conf)

    return models


def get_default_model_name() -> str | None:
    """获取默认模型名称"""
    return base_config.get("SUMMARY_DEFAULT_MODEL_NAME")


def init_current_model() -> str | None:
    """初始化当前模型名称"""
    models = get_configured_models()
    default_name = get_default_model_name()

    if not models:
        logger.warning("未配置任何 AI 模型 (SUMMARY_MODELS 为空)。")
        return None

    if default_name:
        if any(m.name == default_name for m in models):
            logger.info(f"默认模型 '{default_name}' 已加载。")
            return default_name
        else:
            logger.warning(f"配置的默认模型 '{default_name}' 在模型列表中未找到，将使用第一个可用模型。")
            return models[0].name
    else:
        logger.info("未指定默认模型，将使用第一个可用模型。")
        return models[0].name


def handle_switch_model(provider_model_name: str) -> tuple[bool, str]:
    """验证切换的模型名称格式和是否存在"""
    provider_name, model_detail_name = parse_provider_model_string(provider_model_name)

    if not provider_name or not model_detail_name:
        return False, "错误：模型名称格式应为 'ProviderName/ModelName'。"

    if find_model(provider_name, model_detail_name):
        return True, f"模型 '{provider_model_name}' 存在。"
    else:
        providers = get_configured_providers()
        if not any(p.name.lower() == provider_name.lower() for p in providers):
            available_providers = ", ".join([p.name for p in providers])
            return (
                False,
                f"错误：未找到名为 '{provider_name}' 的 Provider。\n可用 Providers 有: {available_providers}",
            )
        else:
            target_provider = next(p for p in providers if p.name.lower() == provider_name.lower())
            available_models = ", ".join([m.model_name for m in target_provider.models])
            return (
                False,
                f"错误：在 Provider '{provider_name}' 中未找到名为 '{model_detail_name}' 的模型。\n'{provider_name}' 下可用模型有: {available_models}",
            )


def validate_active_model_on_startup():
    """在启动时验证并设置当前激活的模型名称配置"""
    current_active_name_str = base_config.get("CURRENT_ACTIVE_MODEL_NAME")
    default_name_str = get_default_model_name()
    providers = get_configured_providers()

    final_name_to_set = None
    validated = False

    if current_active_name_str:
        prov_name, mod_name = parse_provider_model_string(current_active_name_str)
        if prov_name and mod_name and find_model(prov_name, mod_name):
            logger.info(f"启动时确认当前激活模型: {current_active_name_str}")
            final_name_to_set = current_active_name_str
            validated = True

    if not validated and default_name_str:
        prov_name, mod_name = parse_provider_model_string(default_name_str)
        if prov_name and mod_name and find_model(prov_name, mod_name):
            logger.warning(
                f"当前激活模型 '{current_active_name_str}' 无效或未设置，回退到默认模型: {default_name_str}"
            )
            final_name_to_set = default_name_str
            validated = True
        else:
            logger.warning(f"配置的默认模型 '{default_name_str}' 也无效或格式错误。")

    if not validated and providers and providers[0].models:
        first_provider_name = providers[0].name
        first_model_name = providers[0].models[0].model_name
        fallback_name = f"{first_provider_name}/{first_model_name}"
        logger.warning(f"当前激活模型和默认模型均无效或未设置，回退到第一个可用模型: {fallback_name}")
        final_name_to_set = fallback_name
        validated = True

    if not validated:
        logger.error("启动错误：未配置任何有效模型 (AI.PROVIDERS)，无法设置激活模型。")
        final_name_to_set = None

    if final_name_to_set != current_active_name_str:
        Config.set_config("summary_group", "CURRENT_ACTIVE_MODEL_NAME", final_name_to_set, True)
        if final_name_to_set:
            logger.info(f"已将当前激活模型配置更新为: {final_name_to_set}")
        else:
            logger.info("已将当前激活模型配置设置为空 (无可用模型)。")


def handle_list_models(current_active_name_str: str | None) -> str:
    """处理列出模型的逻辑"""
    providers = get_configured_providers()
    default_name_str = get_default_model_name()

    if not providers:
        return "尚未配置任何 AI 模型提供商 (Provider)。"

    message = "可用 AI 模型列表 (格式: ProviderName/ModelName)：\n"
    current_prov, current_mod = parse_provider_model_string(current_active_name_str)
    default_prov, default_mod = parse_provider_model_string(default_name_str)

    for provider in providers:
        message += f"\nProvider: {provider.name}"
        if default_prov and provider.name.lower() == default_prov.lower() and not default_mod:
            message += " [默认 Provider]"
        message += "\n"

        key_info = ""
        if isinstance(provider.api_key, list):
            key_count = len(provider.api_key)
            key_info = f" [{key_count} 个密钥]" if key_count > 1 else ""
        if key_info:
            message += f"  API Keys: {key_info}\n"

        for model_detail in provider.models:
            message += f"  - {model_detail.model_name}"
            if (
                current_prov
                and current_mod
                and provider.name.lower() == current_prov.lower()
                and model_detail.model_name.lower() == current_mod.lower()
            ):
                message += " [当前激活]"
            if (
                default_prov
                and default_mod
                and provider.name.lower() == default_prov.lower()
                and model_detail.model_name.lower() == default_mod.lower()
            ):
                message += " [默认]"
            message += "\n"

    if current_active_name_str and not (
        current_prov and current_mod and find_model(current_prov, current_mod)
    ):
        message += f"\n⚠️警告：当前激活的模型 '{current_active_name_str}' 无效或不在配置列表中！"

    message += "\n使用 '总结切换模型 ProviderName/ModelName' 来切换当前激活模型 (仅限超级用户)。"
    return message.strip()


def get_model_instance_by_name(active_model_name_str: str | None) -> "Model":
    """根据指定的 ProviderName/ModelName 字符串实例化模型"""
    from ..model import LLMModel
    from ..utils.core import ModelException

    logger.debug(f"[get_model_instance_by_name] 尝试实例化模型: {active_model_name_str}")

    selected_provider = None
    selected_model_detail = None

    prov_name, mod_name = parse_provider_model_string(active_model_name_str)

    if prov_name and mod_name:
        found = find_model(prov_name, mod_name)
        if found:
            selected_provider, selected_model_detail = found
        else:
            logger.warning(f"[get_model_instance_by_name] 无法找到模型 '{active_model_name_str}' 的配置。")
            raise ModelException(f"无法找到指定的模型配置: {active_model_name_str}")

    if not selected_provider:
        providers = get_configured_providers()
        if providers and providers[0].models:
            selected_provider = providers[0]
            selected_model_detail = providers[0].models[0]
            fallback_name = f"{selected_provider.name}/{selected_model_detail.model_name}"
            logger.warning(
                f"[get_model_instance_by_name] 接收到无效或None的模型名，回退到第一个模型: {fallback_name}"
            )
        else:
            logger.warning("[get_model_instance_by_name] 无法找到任何可用模型配置！")
            raise ModelException("错误：未配置任何有效的 AI 模型。")

    final_api_keys = selected_provider.api_key
    final_api_base = selected_provider.api_base
    final_model_name = selected_model_detail.model_name
    final_api_type = selected_provider.api_type
    final_openai_compat = selected_provider.openai_compat
    final_temperature = (
        selected_model_detail.temperature
        if selected_model_detail.temperature is not None
        else selected_provider.temperature
    )
    final_max_tokens = (
        selected_model_detail.max_tokens
        if selected_model_detail.max_tokens is not None
        else selected_provider.max_tokens
    )

    logger.debug(
        f"[get_model_instance_by_name] 最终选定 Provider: {selected_provider.name}, Model: {final_model_name}"
    )

    proxy = base_config.get("PROXY")
    timeout = summary_config.get_timeout()
    max_retries = summary_config.get_max_retries()
    retry_delay = summary_config.get_retry_delay()

    try:
        return LLMModel(
            api_keys=final_api_keys,
            api_base=final_api_base,
            summary_model=final_model_name,
            api_type=final_api_type,
            openai_compat=final_openai_compat,
            temperature=final_temperature,
            max_tokens=final_max_tokens,
            proxy=proxy,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
    except Exception as e:
        logger.error(f"[get_model_instance_by_name] 实例化 LLMModel 时出错: {e}")
        raise ModelException(f"初始化模型时发生错误: {e}")


async def handle_key_status() -> str:
    """处理查询 API Key 状态的逻辑"""
    summary = await key_status_store.get_key_status_summary()

    message = "API Key 状态摘要：\n"
    message += f"总计 Key 数量: {summary['total_keys']}\n"
    message += f"可用 Key 数量: {summary['available_keys']}\n"
    message += f"不可用 Key 数量: {summary['unavailable_keys']}\n\n"

    if summary["keys"]:
        message += "Key 详情：\n"
        for key_id, data in summary["keys"].items():
            status_text = "正常" if data["status"] == "normal" else "不可用"
            message += f"- Key {key_id}: {status_text}\n"
            message += f"  成功次数: {data['success_count']}, 失败次数: {data['failure_count']}\n"

            if data["status"] != "normal":
                recovery_in_seconds = data.get("recovery_in_seconds", 0)
                if recovery_in_seconds > 0:
                    minutes = int(recovery_in_seconds // 60)
                    seconds = int(recovery_in_seconds % 60)
                    message += f"  预计恢复时间: {minutes}分{seconds}秒后\n"
                else:
                    message += "  状态: 即将恢复\n"

            message += "\n"
    else:
        message += "尚未记录任何 Key 的使用情况。"

    current_model_name = get_default_model_name()
    message += f"\n当前活跃模型: {current_model_name}"

    return message.strip()


__all__ = [
    "ModelConfig",
    "find_model",
    "get_configured_models",
    "get_configured_providers",
    "get_default_model_name",
    "get_model_instance_by_name",
    "handle_key_status",
    "handle_list_models",
    "handle_switch_model",
    "parse_provider_model_string",
    "validate_active_model_on_startup",
]
