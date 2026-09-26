"""通过运行时补丁配置 MoviePilot V2 的 115 首选上传分片大小。"""
import inspect
import re
from threading import RLock

from app.log import logger
from app.plugins import _PluginBase

_METHOD = "_U115Pan__get_upload_part_size"
_MARKER = "_u115chunksizer_original_descriptor"
_LOCK = RLock()
_MIB = 1024 * 1024


def _positive_int(value, label):
    """读取正整数，拒绝布尔值、小数和非数字。"""
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise ValueError(f"{label}必须是正整数")
    result = int(value)
    if result < 1:
        raise ValueError(f"{label}必须大于 0")
    return result


def _parse_config(config):
    """过滤非法档位并排序去重；无有效配置时使用默认值。"""
    config = config if isinstance(config, dict) else {}
    raw = config.get("steps_mb", "100,256,512,1024")
    values = set()
    for value in raw.replace("，", ",").split(",") if isinstance(raw, str) else []:
        try:
            size = _positive_int(value.strip(), "分片档位")
            values.add(size)
        except (ValueError, TypeError):
            continue
    values = sorted(values or {100, 256, 512, 1024})
    try:
        target = _positive_int(config.get("target_parts", 96), "目标分片数")
    except (ValueError, TypeError):
        target = 96
    return tuple(v * _MIB for v in values), target


class U115ChunkSizer(_PluginBase):
    """在插件生命周期内替换 115 分片选择方法，并在停止时恢复。"""
    plugin_name = "115上传分片调节"
    plugin_desc = "按文件大小、目标分片数和自定义档位调整 115 首选上传分片大小。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.2"
    plugin_author = "sakezerto"
    author_url = "https://github.com/sakezerto"
    plugin_config_prefix = "u115chunksizer_"
    plugin_order = 30
    auth_level = 1

    def init_plugin(self, config=None):
        """先移除旧补丁，再按最新配置安装静态分片选择方法。"""
        with _LOCK:
            self.stop_service()
            self._error = ""
            config = config if isinstance(config, dict) else {}
            if config.get("enabled", True) is not True:
                return
            try:
                sizes, target = _parse_config(config)
                from app.modules.filemanager.storages.u115 import U115Pan

                current = inspect.getattr_static(U115Pan, _METHOD)
                if not isinstance(current, staticmethod):
                    raise RuntimeError("目标方法已不是静态方法，需要适配当前 MoviePilot")
                # Carry the original descriptor across plugin module reloads.
                original = getattr(current.__func__, _MARKER, current)
                params = list(inspect.signature(original.__func__).parameters.values())
                if (len(params) != 1 or params[0].name != "file_size"
                        or params[0].kind != inspect.Parameter.POSITIONAL_OR_KEYWORD):
                    raise RuntimeError("目标方法签名已变化，需要适配当前 MoviePilot")

                def preferred_part_size(file_size: int) -> int:
                    """返回首选分片字节数；异常或非正文件大小取最小档位。"""
                    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size <= 0:
                        return sizes[0]
                    required = (file_size + target - 1) // target
                    return next((size for size in sizes if size >= required), sizes[-1])

                setattr(preferred_part_size, _MARKER, original)
                replacement = staticmethod(preferred_part_size)
                self._storage = U115Pan
                self._original = original
                self._replacement = replacement
                setattr(U115Pan, _METHOD, replacement)
                logger.info(f"[U115ChunkSizer] 已启用：档位 {[s // _MIB for s in sizes]} MiB，目标 {target} 片")
            except Exception as exc:
                self._error = (f"无法应用 115 分片补丁（{type(exc).__name__}），"
                               "请检查 U115Pan 是否可导入，以及私有静态方法及签名是否兼容。")
                logger.error(f"[U115ChunkSizer] 启用失败：{self._error}")

    def stop_service(self):
        """恢复原始描述符并释放引用；不覆盖其他代码随后安装的补丁。"""
        with _LOCK:
            storage = getattr(self, "_storage", None)
            replacement = getattr(self, "_replacement", None)
            if storage is not None and replacement is not None:
                if inspect.getattr_static(storage, _METHOD, None) is replacement:
                    setattr(storage, _METHOD, self._original)
                    logger.info("[U115ChunkSizer] 已恢复原始分片方法")
                else:
                    logger.warning("[U115ChunkSizer] 方法已被其他代码替换，未覆盖该方法")
            self._storage = None
            self._replacement = None
            self._original = None

    def get_state(self):
        """返回本实例的补丁当前是否生效。"""
        storage = getattr(self, "_storage", None)
        return (storage is not None and
                inspect.getattr_static(storage, _METHOD, None) is self._replacement)

    def get_form(self):
        """返回分区卡片式配置页，使用主题配色并适配窄屏。"""
        return [{"component": "VForm", "content": [
            {"component": "VCard", "props": {
                "variant": "tonal", "color": "primary", "rounded": "lg", "class": "mb-4"},
             "content": [{"component": "VCardText", "content": [
                 {"component": "div", "props": {"class": "text-h6 font-weight-bold mb-1"},
                  "text": "115 上传分片"},
                 {"component": "div", "props": {"class": "text-body-2 mb-3"},
                  "text": "设置分片档位，让不同大小的文件自动选择合适的上传分片。"},
                 {"component": "VSwitch", "props": {
                     "model": "enabled", "label": "启用自定义分片", "color": "primary",
                     "inset": True, "hide-details": True, "class": "mt-0"}}
             ]}]},
            {"component": "VCard", "props": {
                "variant": "outlined", "rounded": "lg", "class": "mb-4"},
             "content": [{"component": "VCardText", "content": [
                 {"component": "div", "props": {"class": "text-subtitle-1 font-weight-bold mb-1"},
                  "text": "分片策略"},
                 {"component": "div", "props": {"class": "text-body-2 text-medium-emphasis mb-5"},
                  "text": "按“文件大小 ÷ 目标分片数”计算，再向上匹配一个档位。"},
                 {"component": "VRow", "content": [
                     {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                         {"component": "VTextField", "props": {
                             "model": "steps_mb", "label": "分片档位", "suffix": "MiB",
                             "variant": "outlined", "density": "comfortable", "color": "primary",
                             "placeholder": "100,256,512,1024", "prepend-inner-icon": "mdi-layers-outline",
                             "hint": "填写正整数 MiB，插件不设上限；支持中英文逗号，自动排序、去重。",
                             "persistent-hint": True}}
                     ]},
                     {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                         {"component": "VTextField", "props": {
                             "model": "target_parts", "label": "目标分片数", "suffix": "片",
                             "type": "number", "min": 1, "step": 1, "variant": "outlined",
                             "density": "comfortable", "color": "primary",
                             "hint": "默认 96；数值越小，通常分片越大。", "persistent-hint": True}}
                     ]}
                 ]},
                 {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-4"},
                  "text": "可追加 2048、4096 等档位。无有效档位时使用默认值；无效目标数回退为 96。超过最大配置档位时取最大值。"}
             ]}]},
            {"component": "VAlert", "props": {
                "type": "info", "variant": "tonal", "rounded": "lg", "class": "mb-4",
                "title": "计算示例 · 不是当前配置预览",
                "text": "档位为 100 / 256 / 512 / 1024 MiB 时：6 GiB ÷ 16 = 384 MiB，"
                        "向上选 512 MiB，约 12 片。目标分片数是参考值，不是固定片数。"}},
            {"component": "VAlert", "props": {
                "type": "warning", "variant": "tonal", "rounded": "lg", "class": "mb-4",
                "title": "配置无上限，不代表服务端无上限",
                "text": "OSS 官方单片上限为 5 GiB（5120 MiB）；超过服务端限制可能上传失败。"
                        "115 实际限制以服务端为准，大分片会增加失败重传成本。"}},
            {"component": "VExpansionPanels", "props": {"variant": "accordion"}, "content": [
                {"component": "VExpansionPanel", "content": [
                    {"component": "VExpansionPanelTitle", "text": "使用提示与兼容性"},
                    {"component": "VExpansionPanelText", "content": [
                        {"component": "div", "props": {"class": "text-body-2 mb-2"},
                         "text": "保存后影响后续计算分片的上传，已经确定的分片不会重新切分；停用后恢复原始策略。"},
                        {"component": "div", "props": {"class": "text-body-2 mb-2"},
                         "text": "单片越大，分片数量越少，但失败时的重传成本也更高。OSS SDK 可能进一步调整实际大小。"},
                        {"component": "div", "props": {"class": "text-body-2 text-medium-emphasis"},
                         "text": "插件使用运行时补丁。MoviePilot 升级后如 115 类名或私有方法发生变化，需要适配。"}
                    ]}
                ]}
            ]}
        ]}], {"enabled": True, "steps_mb": "100,256,512,1024", "target_parts": 96}

    def get_page(self):
        """显示补丁状态及兼容性错误，便于本地安装后排查。"""
        error = getattr(self, "_error", "")
        active = self.get_state()
        return [{"component": "VAlert", "props": {
            "type": "error" if error else ("success" if active else "info"),
            "variant": "tonal", "rounded": "lg",
            "title": "需要检查兼容性" if error else ("自定义分片已生效" if active else "自定义分片未启用"),
            "text": error or ("后续计算分片的 115 上传将使用已保存的分片策略。" if active
                              else "可在插件配置中启用，并设置分片档位与目标分片数。")}}]

    def get_api(self):
        """本插件不注册 API。"""
        return []

    @staticmethod
    def get_command():
        """本插件不注册远程命令。"""
        return []

    def get_service(self):
        """本插件不注册定时服务。"""
        return []
