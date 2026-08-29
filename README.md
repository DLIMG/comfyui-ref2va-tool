# ComfyUI H3 分镜与 Latent 续镜工具

## 使用方法

1. 启动本机或远端 ComfyUI。远端模式默认连接 `http://192.168.11.103:8188`。
2. 双击 `启动工具.bat`。
3. 浏览器会自动打开 `http://127.0.0.1:8765`。
4. 展开“高级参数”，在“生成设备”中选择本机或远端；远端可填写 IP 并点击“测试连接”。
5. 故事板一行代表一个最终视频片段。点击“新增片段”或“复制片段”。
6. 点击表格中的片段行，展开编辑区。
7. 为每个片段选择“R2VA 多参考”或“FL2VA 首尾帧”。R2VA 图片按顺序成为 `<Picture N>`；FL2VA 首段的前两张依次为首帧、尾帧，其余为 Qwen 参考图。
8. 连续动作镜头可勾选“延续上一镜（AV Latent）”。软件按故事板顺序加载上一镜保存的 latent，保护39帧上下文并在输出时移除重叠头部。第一行不能开启延续。
9. 点击“读取 TXT”或直接粘贴完整 H3 提示词。
10. 选择清晰度和画幅，再填写片段号、标题、时长、随机种子和输出名称。
11. 单独提交当前片段，或勾选多行后点击“生成选中”；latent续镜建议使用“全部排队”，保证上一镜先保存latent。
12. 生成完成后，展开对应片段，在“生成结果”区域直接播放视频；每次生成都会新增视频结果。

故事板自动保存在 `data\storyboard.json`。页面刷新或工具重启后会恢复所有片段。可使用“导入JSON”和“导出JSON”备份或转移项目。

本机模式直接使用 `http://127.0.0.1:8188`。远端模式下，故事板 JSON、原始参考图和提示词仍保存在本机；提交时软件自动把当前分镜所需素材上传到远端 ComfyUI，完成后再把视频下载回本机项目结果目录。任务状态、取消和高清放大也会自动指向任务原来的设备。

## 文件位置

- ComfyUI 输入副本：`G:\ComfyUI\input\codex_ref2va_tool\`
- ComfyUI 视频输出：`G:\ComfyUI\output\codex_ref2va_tool\`
- H3 AV latent：`G:\ComfyUI\output\codex_ref2va_tool\latents\`
- 每次实际提交的工作流：本工具目录下 `data\runs\`
- 工具管理的全部生成结果：本工具目录下 `data\results\`
- 故事板数据：本工具目录下 `data\storyboard.json`
- 网页选择或拖入的原始图片：本工具目录下 `data\uploads\`
- 远端传输暂存（可重复使用）：本工具目录下 `data\remote_staging\`
- API 工作流模板：`app\templates\minimax_h3_turbo_8step_ref2va_api.json`

当前模板派生自 `MiniMax_H3_Turbo_8Step_LoRA_SageAttention_TeaCache_R2VA_480P.json`：启用 Turbo 8-step LoRA 与 SageAttention，关闭 4-step LoRA 与 TeaCache，调度器使用 8 steps。参考图、提示词、时长、随机种子、清晰度、画幅和输出名称仍由每次提交动态写入。

Latent续镜依赖 `G:\ComfyUI\custom_nodes\Herrgotts-H3-Infinite-Continuation-Suite` v1.4。安装或更新节点包后必须重启ComfyUI。R2VA续镜保留R2VA参考条件并使用Masked AV目标latent；FL2VA续镜使用FL2VA条件与同一套Masked AV上下文。

## 注意

- 页面中的图片顺序必须与提示词的 `<Picture N>` 一致。
- 勾选延续后，上一行的`output_name`决定要加载的latent文件；不要在生成上一镜后随意改名。
- Latent 续镜必须始终使用同一台 ComfyUI；软件会拒绝跨设备续镜。
- 删除生成结果会永久删除 `data\results` 中的视频副本和故事板记录，无法恢复；ComfyUI 输出目录中的原始视频不会被本工具删除。
- 输出名称不要包含斜杠、冒号等特殊字符。
- 工具只在本机 `127.0.0.1` 上运行，不对局域网开放。
- 如果显示“ComfyUI 未连接”，先检查对应设备是否运行、网线是否连接，以及远端 `8188` 端口是否可访问。
