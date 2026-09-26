# 115上传分片调节 · MoviePilot V2

本地插件，无额外 Python 依赖，不修改 MoviePilot 核心文件。插件 ID：`U115ChunkSizer`。

## 安装到本地仓库

适用于支持 `PLUGIN_LOCAL_REPO_PATHS` 的 MoviePilot V2。先确认安装版本存在 `app.modules.filemanager.storages.u115.U115Pan` 及其 `__get_upload_part_size(file_size)` 静态方法；旧版本缺少该方法时插件会报错，不会强行替换。

1. 解压，将整个 `MoviePilot-Plugins` 目录存入宿主机持久化目录。
2. 将它映射到容器中的独立目录，例如 `/local-plugins/u115`。这里是插件源仓库，不能覆盖 `/app/app/plugins` 整个目录。
3. 设置 `PLUGIN_LOCAL_REPO_PATHS=/local-plugins/u115`。若已有路径，用逗号追加，保留原值。
4. 重建或重启容器让环境变量生效，打开插件市场，安装“115上传分片调节”，进入配置并启用。

Docker Compose 片段（合并到现有服务，保留其他挂载和配置）：

```yaml
environment:
  PLUGIN_LOCAL_REPO_PATHS: /local-plugins/u115
volumes:
  - /你的持久化目录/MoviePilot-Plugins:/local-plugins/u115:ro
```

如果当前 V2 不支持本地插件仓库，请升级到支持该功能的版本，或使用下方 GitHub 插件源方式。仅复制文件到运行目录可能不会登记为已安装插件。

## 配置及行为

默认启用：`enabled=true`，`steps_mb="100,256,512,1024"`，`target_parts=96`。
档位单位为 MiB，过滤 1～1024 范围以外及非整数值，支持中文逗号，自动排序去重；全部非法时回退默认档位。目标分片数非正整数时回退到 96。
默认移除 10/16/32/64 MiB 档位，确保中小文件从 100 MiB 起步。单片变大可减少分片数量，但失败时重传成本也会上升。

计算时使用整数向上取整，选取不小于 `文件字节数 / 目标分片数` 的最小档位；目标超过最大档位时取最大档位，零、负数或异常文件大小返回最小档位，与核心方法的边界处理一致。

| 文件/配置 | 首选分片大小 |
|---|---:|
| 1 GiB，默认配置 | 100 MiB |
| 1 GiB，添加 64 档位 | 64 MiB |
| 1 GiB，默认档位，目标改为 15 | 100 MiB |
| 10 GiB，默认配置 | 256 MiB |

目标分片数越大，计算的目标大小越小。要让 1 GiB 选择 100 MiB，可以删除 64 档位，或将目标分片数降低到 11～15。

这是运行时猴子补丁。只影响本进程内后续调用该方法的上传；已经计算好分片大小的上传不变，但已启动、尚未计算分片的任务也可能受到影响。秒传不受影响。核心会将返回值交给 `oss2.determine_part_size`，SDK 可能进一步调整，目标分片数不是硬性上限。

停用、正常卸载或插件服务停止时恢复原始静态方法。重复初始化和模块热重载不会把本插件旧补丁当作原始方法。如果其他代码随后替换了同一方法，停止时不会覆盖它；不建议同时启用操作同一方法的插件。直接删除源码不会触发生命周期，请先停用/卸载，必要时重启 MoviePilot。

非法配置按上述规则过滤或回退；接口不兼容时，插件详情及日志显示错误，补丁不生效。只在当前进程生效；若部署多个后端进程，需要各进程正常加载插件。

## GitHub 发布

将本目录内容提交至目标仓库 `main` 分支。仓库根目录应包含 `package.v2.json` 与 `plugins.v2/u115chunksizer/__init__.py`。
已有插件仓库需将本包的 `U115ChunkSizer` 条目合并到现有 JSON 中，**不要用本包的索引覆盖现有索引**。只复制本插件目录，不覆盖其他插件目录。

发布后在 MoviePilot 插件市场添加该 GitHub 仓库地址并安装。插件源仓库：`https://github.com/sakezerto/MoviePilot-Plugins`。将该地址加入 MoviePilot 插件市场，搜索“115上传分片调节”并安装。

压缩包以明确文件清单生成，只包含源码、索引和说明；不包含配置、令牌、数据库、日志或缓存。发布已有仓库时仍应审查暂存文件，`.gitignore` 不会移除已被 Git 跟踪的敏感文件。

## 验证

测试代码单独提供在交付目录 `tests/test_u115chunksizer.py`，GitHub 发布压缩包不包含测试。将测试放在仓库 `tests/` 下，运行 `python -B -m unittest discover -s tests -v`。
语法检查：`python -m py_compile plugins.v2/u115chunksizer/__init__.py`。
测试使用 MoviePilot 模块替身，覆盖档位边界、配置更新、错误配置、启停恢复、模块重载及其他补丁冲突。未进行真实 MoviePilot 容器或 115 上传联调。

核对依据（2026-09-27，V2 分支可能继续变更）：

- [115 存储实现](https://github.com/jxxghp/MoviePilot/blob/v2/app/modules/filemanager/storages/u115.py)
- [插件基类](https://github.com/jxxghp/MoviePilot/blob/v2/app/plugins/__init__.py)
- [本地仓库加载](https://github.com/jxxghp/MoviePilot/blob/v2/app/helper/plugin.py)
- [插件生命周期](https://github.com/jxxghp/MoviePilot/blob/v2/app/core/plugin.py)

## 升级与卸载

升级前保存现有配置并停用插件；更新持久化源仓库中的本插件源码及索引条目，然后在 MoviePilot 中重新安装/重载插件并核对配置。GitHub 源安装时发布新版本并同步提高源码及索引版本号，再通过插件市场升级。卸载使用 MoviePilot 插件界面，先停用可立即恢复原始逻辑；容器重建时保留持久化插件源及 MoviePilot 配置卷，必要时从本地或 GitHub 源重新安装。

## 发布目录结构

```text
MoviePilot-Plugins/
├── package.v2.json
├── README.md
└── plugins.v2/
    └── u115chunksizer/
        └── __init__.py
```

## 1.0.1 界面更新

配置页采用主题色卡片、响应式双列输入和折叠提示；增加固定计算示例，避免将示例误当作当前配置预览。状态页区分已生效、未启用与兼容性错误。字段名、默认配置及分片算法保持不变。实际 MoviePilot 界面仍需宿主验证。
