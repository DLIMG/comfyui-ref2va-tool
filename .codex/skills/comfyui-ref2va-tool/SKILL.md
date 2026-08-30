---
name: comfyui-ref2va-tool
description: 当需要使用、启动、配置或排查 comfyui-ref2va-tool 与 ComfyUI，整理短剧角色/场景/道具资产，创建、优化、导入、检查或提交 MiniMax H3 R2VA/FL2VA 故事板和提示词，以及处理 Masked AV latent 续镜、长参考视频分段、音画/嘴型错位、H3帧格、精确时长、镜头衔接和时间冻结等连续性要求时使用。
---

# ComfyUI Ref2VA 工具

## 用途

使用本地网页工具管理 MiniMax H3 R2VA/FL2VA 分镜、Masked AV latent续镜、ComfyUI任务、生成结果和连续预览。故事板JSON同时包含项目配置和本地运行状态，处理时必须区分二者。

## 固定位置

- 工具目录：`G:\AI短剧生成\comfyui-ref2va-tool`
- 启动方式：运行 `启动工具.bat`，或执行 `python start.py --no-browser --port 8765`
- 默认网页：`http://127.0.0.1:8765/`
- ComfyUI：`http://127.0.0.1:8188`
- 当前故事板：`data\storyboard.json`
- 工作流模板：`app\templates\minimax_h3_turbo_8step_ref2va_api.json`
- Latent节点包：`G:\ComfyUI\custom_nodes\Herrgotts-H3-Infinite-Continuation-Suite`
- Latent输出：`G:\ComfyUI\output\codex_ref2va_tool\latents`

## 使用规则

1. 先启动 ComfyUI，再启动网页工具，并确认页面显示 ComfyUI 已连接。
2. 故事板一行代表一个最终视频片段；`id`和`output_name`必须唯一。
3. 每镜必须明确`generation_mode`。R2VA的`references`按`<Picture N>`排列，`reference_videos`按`<Video N>`排列并自动把同序号原声接为`<Audio N>`；参考视频每段2–15秒、最多3段。FL2VA首段前两张依次为首帧、尾帧，续镜第一张为新尾帧，其余为Qwen参考图；当前软件不在FL2VA模式接入参考视频。
4. 提示词默认严格采用`h3-prompt-writing`规范并按模式分流：R2VA优先使用Ref2VA六段式；普通FL2VA优先使用首尾帧对齐说明和三核心字段；latent续镜FL2VA使用L2VA尾帧对齐说明和三核心字段。只有用户明确要求自由文本，或是在导入、兼容、快速试验场景中，才原样保留非空自由文本。软件不得因自由文本缺少结构化标题而阻止保存或提交。对白只放进明确的对白标签，避免人物朗读控制说明。
5. 提交前先保存。使用“生成选中”提交勾选片段，或用“全部排队”按故事板顺序提交。
6. 每次生成都会新增结果，不覆盖旧视频；不要为了重新生成而删除仍可用的旧结果。
7. 需要把视频保存进具体项目时，在JSON顶层设置绝对路径`project_dir`。结果将复制到`<project_dir>\06_生成视频`；未设置时使用工具的`data\results`。
8. 重新导入JSON时，项目配置和片段顺序以导入文件为准；同ID片段在导入结果为空时保留当前运行状态和视频结果。生成后不要随意修改片段ID。
9. 网页删除操作会永久删除工具管理的视频副本，但不会删除ComfyUI输出目录中的原始文件。
10. 除非用户明确要求生成，否则不得调用`/api/submit`或把任务加入ComfyUI队列。
11. `continue_from_previous=true`只允许用于非首行片段。它隐式读取紧邻上一镜`output_name`对应的AV latent；勾选延续时，界面必须自动强制打开上一镜的`save_latent`。
12. R2VA和FL2VA共享H3 AV latent格式。R2VA续镜保留R2VA conditioning并使用`H3ContinuousContinueV14`产生的Masked AV目标latent；FL2VA续镜同时使用该节点的conditioning和latent。
13. Latent文件和handover元数据是本地运行状态，不写入干净故事板JSON，也不要伪造路径或假定仅有MP4即可恢复原latent。
14. 只有`queued`或`running`状态显示“取消生成”。取消必须按`prompt_id`精确调用ComfyUI job cancel API：排队任务从队列移除，正在运行的任务发送中断，不得清空或中断其他分镜。取消后状态记为`cancelled`，已生成的旧结果不删除。

## 短剧资产、提示词与镜头连续性

当任务涉及从剧本和分镜表整理资产、编写或打磨提示词、首帧/尾帧、人物一致性、场景方位、景别选择、时间冻结或相邻镜头衔接时，必须阅读[短剧Ref2VA制作规范](references/short-drama-production.md)。该规范吸收 MiniMax Design 中适用于本项目的素材角色、身份锁定、空间骨架和可执行时间轴原则，并针对叙事短剧与本地 Ref2VA 工作流做了收敛。

编写、改写或审核结构化提示词时，还必须完整读取`D:\.codex\skills\h3-prompt-writing\SKILL.md`及其按模式指定的指南：R2VA读取`references/ref-en.txt`，FL2VA读取`references/base-en.txt`。H3规范规定的字段名、字段顺序、引用标签、镜头时间、说话者ID和对白标签优先于本技能中的简化示例；本技能只追加本地工作流、短剧连续性和帧格约束。

## 启动与故障排查

启动、修改启动脚本，或遇到网页无法连接、`uvicorn`缺失、ComfyUI数据库锁、端口占用和重复启动时，必须阅读[启动与诊断规范](references/startup-troubleshooting.md)。

## JSON工作

创建、修改、检查或解释可导入JSON前，必须阅读[故事板JSON规范](references/storyboard-json.md)，遵守字段定义、提示词规则、导入合并逻辑和运行状态边界。

## 分段参考视频与帧对齐

当任务涉及长参考视频切段、R2VA参考音频、第二镜起声音或嘴型崩坏、实际输出短于请求时长、精确总时长，或Masked AV续镜与参考视频同时使用时，必须阅读[R2VA分段参考与Latent帧对齐规范](references/r2va-segmented-alignment.md)。不得把用户填写的秒数直接当作最终视频时长；必须按H3合法帧格、隐藏接续头和安全尾部计算参考素材、提示词与预计可见帧数。

## 工作流默认设置

R2VA和FL2VA均启用Turbo 8步LoRA和SageAttention，关闭4步LoRA与TeaCache；采样步数为8，scheduler为`simple`，sampler为`res_multistep`。R2VA参考视频通过`LoadVideo -> GetVideoComponents`把画面帧和原声音轨接入`MiniMaxH3ReferenceToVideo`。`save_latent`默认为`false`，用户可逐镜开启；若下一镜开启延续，上一镜必须自动保存完整AV latent与handover元数据。续镜使用39帧（约1.625秒）原生Masked AV上下文，输出时移除重叠头部。剩余时间优先读取ComfyUI `progress_state`中与CMD tqdm同源的采样步进度，按实际步耗时估算；排队任务再累加前方任务和自身预估。尚未收到实时步进度时，才回退到时长和分辨率经验值；解码和保存收尾仍不是精确倒计时。

## 交付前验证

交付JSON前必须确认：JSON可解析；片段ID和输出名唯一；生成模式受支持；参考图路径与模式顺序正确；首行未开启延续；每个续镜都有紧邻上一镜；提示词非空；时长、清晰度与画幅受支持。默认结构化提示词必须按模式检查：R2VA六段齐全且顺序正确；FL2VA首尾帧对齐说明准确、三核心字段齐全且顺序正确。若用户明确选择自由文本，只检查非空、引用不冲突、时序可执行和对白安全，不得擅自改写为结构化格式；`validate_shot`不强制提示词格式。分段参考任务还必须用`ffprobe`核实每段实际帧数、fps、音频采样率和真实时长，并用节点采用的帧格函数计算预计可见总帧数；不得仅检查JSON中的`duration`之和。
