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
            if size <= 1024:
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
    plugin_icon = "mdi-database-arrow-up"
    plugin_version = "1.0.0"
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
        """返回原生 Vuetify 配置表单及默认配置。"""
        return [{"component": "VForm", "content": [
            {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}},
            {"component": "VTextField", "props": {
                "model": "steps_mb", "label": "分片档位（MiB）",
                "hint": "1～1024 的整数，中英文逗号分隔；过滤非法值、去重排序，全无效时回退默认档位", "persistent-hint": True}},
            {"component": "VTextField", "props": {
                "model": "target_parts", "label": "目标分片数", "type": "number", "min": 1}},
            {"component": "VAlert", "props": {"type": "warning", "variant": "tonal"},
             "text": "取不小于 文件大小÷目标分片数 的最小档位，超过最大档位时取最大值。"
                     "1 GiB 默认取 100 MiB。只影响后续计算分片的新上传，不会重新切分已有分片。"
                     "这是针对当前 115 实现的运行时补丁；升级后类名或私有方法变化时需适配。"
                     "单片越大、分片越少，但失败重传成本越高；最终大小可能由 OSS SDK 调整。"}
        ]}], {"enabled": True, "steps_mb": "100,256,512,1024", "target_parts": 96}

    def get_page(self):
        """显示补丁状态及兼容性错误，便于本地安装后排查。"""
        error = getattr(self, "_error", "")
        return [{"component": "VAlert", "props": {"type": "error" if error else "info"},
                 "text": error or ("补丁已生效" if self.get_state() else "补丁未启用")}]

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
