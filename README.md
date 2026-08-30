# ComfyUI H3 分镜与 Latent 续镜工具

面向 MiniMax H3 R2VA / FL2VA 的本地故事板工作台。它把参考素材、中文提示词、ComfyUI 工作流、任务队列、AV Latent 续镜和生成结果放进同一个网页界面，适合短剧、多镜头连续叙事和动作 / 音频参考迁移。

## 成果展示

> 点击封面播放轻量预览；仓库中的演示版经过压缩，原始成片未纳入版本控制。

| 短剧测试：《外星人来地球当群演》 | 小猫唱歌一镜到底 |
| --- | --- |
| [![《外星人来地球当群演》视频封面](docs/showcase/alien-extra.jpg)](docs/showcase/alien-extra.mp4) | [![小猫唱歌一镜到底视频封面](docs/showcase/cat-one-take.jpg)](docs/showcase/cat-one-take.mp4) |
| 83 秒竖屏短剧测试，验证多镜头叙事与角色 / 场景连续性。 | 30 秒竖屏连续镜头，验证参考视频动作、原声与 AV Latent 接续。 |

## 主要能力

- **R2VA 多参考生成**：按顺序管理参考图、参考视频及其原声，并自动映射为 `<Picture N>`、`<Video N>` 和 `<Audio N>`。
- **FL2VA 首尾帧生成**：首段支持首帧、尾帧与额外 Qwen 参考图。
- **AV Latent 连续续镜**：保护 39 帧上下文，自动去除成片中的重叠头部，并约束相邻镜头使用同一生成设备。
- **本机 / 远端 ComfyUI**：可切换生成设备、测试连接、上传所需素材并回收远端结果。
- **故事板与批量队列**：逐镜编辑、复制、导入导出 JSON、生成选中或按顺序全部排队。
- **结果管理**：页面内预览历史结果；每次生成新增结果，不覆盖旧视频。
- **任务控制**：展示任务状态与剩余时间，可精确取消单个排队或运行中的任务。

## 快速开始

### 1. 准备环境

- Python 3.10+
- 已安装并可访问的 ComfyUI
- MiniMax H3 所需模型与自定义节点
- Latent 续镜需要 `Herrgotts-H3-Infinite-Continuation-Suite` v1.4

安装 Python 依赖：

```powershell
pip install -r requirements.txt
```

### 2. 启动

先启动 ComfyUI，再双击 `启动工具.bat`；也可以在命令行运行：

```powershell
python start.py
```

浏览器将打开 `http://127.0.0.1:8765`。网页服务仅监听本机 `127.0.0.1`，不会直接对局域网开放。

### 3. 创建并生成故事板

1. 展开“高级参数”，选择本机或远端生成设备；远端可填写 IP 并测试连接。
2. 新增片段并选择 `R2VA 多参考` 或 `FL2VA 首尾帧`。
3. 按提示词引用顺序添加图片和参考视频，再粘贴完整 H3 提示词。
4. 设置片段号、标题、时长、随机种子、清晰度、画幅和输出名称。
5. 连续动作镜头可勾选“延续上一镜（AV Latent）”；第一行不能开启延续。
6. 保存后生成当前 / 选中片段，或用“全部排队”保证 Latent 续镜按顺序执行。
7. 在片段的“生成结果”区域直接查看每次生成的视频。

故事板自动保存在 `data/storyboard.json`，刷新页面或重启工具后会恢复；也可使用“导入 JSON”和“导出 JSON”备份或迁移项目。

## R2VA / FL2VA 素材规则

| 模式 | 素材顺序 | 说明 |
| --- | --- | --- |
| R2VA | 图片 → `<Picture N>` | 图片顺序必须与提示词一致。 |
| R2VA | 视频 → `<Video N>`，原声 → `<Audio N>` | 单段 2–15 秒，最多 3 段。 |
| FL2VA 首段 | 第 1 张为首帧，第 2 张为尾帧 | 后续图片作为 Qwen 参考图。 |
| FL2VA 续镜 | 第 1 张为新的尾帧 | 当前版本不在 FL2VA 模式接入参考视频。 |

## 数据与输出位置

| 内容 | 默认位置 |
| --- | --- |
| 故事板 | `data/storyboard.json` |
| 原始参考素材副本 | `data/uploads/` |
| 实际提交的工作流 | `data/runs/` |
| 工具管理的生成结果 | `data/results/` |
| 远端传输暂存 | `data/remote_staging/` |
| ComfyUI 输入副本 | `G:\ComfyUI\input\codex_ref2va_tool\` |
| ComfyUI 视频与 Latent | `G:\ComfyUI\output\codex_ref2va_tool\` |
| API 工作流模板 | `app/templates/minimax_h3_turbo_8step_ref2va_api.json` |

如果故事板顶层设置了绝对路径 `project_dir`，生成结果还会复制到 `<project_dir>/06_生成视频`。

## 工作流默认值

当前模板启用 Turbo 8-step LoRA 与 SageAttention，关闭 4-step LoRA 和 TeaCache；采样步数为 8，scheduler 为 `simple`，sampler 为 `res_multistep`。参考素材、提示词、时长、随机种子、清晰度、画幅和输出名称会在每次提交时动态写入工作流。

## 使用注意

- 开启续镜后，上一行的 `output_name` 决定所加载的 Latent；生成上一镜后不要随意改名或调整顺序。
- Latent 续镜必须始终使用同一台 ComfyUI，工具会拒绝跨设备接续。
- 删除网页中的生成结果会永久删除 `data/results` 内的工具副本，但不会删除 ComfyUI 输出目录中的原始视频。
- 输出名称不要包含斜杠、冒号等特殊字符。
- 若显示“ComfyUI 未连接”，请检查对应设备、网络连接和 `8188` 端口。

## 测试

```powershell
python -m pytest -q
```
