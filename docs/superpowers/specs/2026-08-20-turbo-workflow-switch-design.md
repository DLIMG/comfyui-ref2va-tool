# Ref2VA 工具切换 MiniMax H3 Turbo 工作流设计

## 目标

将 `comfyui-ref2va-tool` 的底层模板切换为已在本机验证过的
`G:\ComfyUI\user\default\workflows\MiniMax_H3_Turbo_8Step_LoRA_SageAttention_TeaCache_R2VA_480P.json`，同时保留工具现有的参考图、提示词、时长、随机种子、清晰度、画幅和输出名称控制。

## 约束

- 源文件是 ComfyUI 界面工作流格式，不能直接提交到 `/prompt`。
- 不修改源界面工作流。
- 8-step Turbo LoRA 保持启用。
- SageAttention 保持启用。
- Ref2V 4-step LoRA 默认旁路关闭。
- TeaCache 默认旁路关闭。
- 不在工具页面增加 LoRA、SageAttention 或 TeaCache 开关。
- 不改变故事板数据格式、结果收集方式或现有页面操作流程。

## 方案

在工具项目中保存一份由源界面工作流派生的 API 格式模板。运行时仍沿用现有流程：载入 API 模板，深拷贝后替换本次任务的动态输入，再提交给 ComfyUI。

不采用运行时通用界面工作流转换器，因为它需要复刻 ComfyUI 前端的节点序列化、旁路和动态端口规则，维护成本与兼容风险明显高于本次需求。也不要求用户手动维护额外的 API 导出文件。

## 工作流状态

派生模板必须保留源工作流中实际生效的模型链路：

1. `UNETLoader` 加载 MiniMax H3 Ref2VA 模型。
2. 节点 152（Ref2V Turbo 4-step LoRA）处于旁路状态，不出现在有效 API 执行链中。
3. 节点 150（FL2V Turbo 8-step LoRA）保持在有效模型链中。
4. 节点 142（MiniMax H3 SageAttention Patch）保持在有效模型链中。
5. 节点 141（TeaCache）处于旁路状态，不出现在有效 API 执行链中。
6. 有效模型输出直接供调度器和 guider 使用。
7. 调度器保持源工作流的 `simple`、8 steps、denoise 1；采样器保持 `res_multistep`。

## 动态输入映射

工具每次提交时只修改以下内容：

- 删除模板内示例 `LoadImage` 节点，并按用户图片顺序创建任意数量的新 `LoadImage` 节点。
- 将图片依次连接到 `MiniMaxH3ReferenceToVideo` 的 `ref_images.ref_image_N`。
- 替换完整 Ref2VA 提示词。
- 替换时长，并继续通过工作流内的帧数表达式换算为合法帧数。
- 替换随机种子。
- 根据页面清晰度映射设置目标百万像素，根据画幅设置宽高比。
- 替换 `SaveVideo.filename_prefix`，继续写入工具管理的 ComfyUI 输出目录。

除这些动态字段外，模型、LoRA、采样器、调度器、VAE、文本编码器、SageAttention 和其他节点参数保持派生模板中的值。

## 文件与代码改动

- 在项目内新增工具专用 API 模板，避免依赖旧的 `D:\Edges Downloads` 模板。
- 将 `app/main.py` 的默认模板路径指向新 API 模板。
- 调整 `app/workflow.py` 的模板节点契约，使校验与动态字段映射适配新模板。
- 更新 `tests/test_workflow.py`，验证新模板、启停状态对应的有效链路、动态字段替换和模板不变性。
- 更新 `README.md` 中的模板位置和默认加速状态说明。

## 错误处理

- 模板缺失、不是 API 格式、关键节点类型不符或关键连接缺失时，在提交前返回明确错误。
- 清晰度或画幅值不受支持时维持现有验证行为。
- ComfyUI 对派生工作流校验失败时，将其原始错误通过现有接口返回，不自动回退到旧工作流。

## 验证

1. 先新增针对新模板的失败测试，确认旧实现无法满足新节点契约。
2. 生成 API 模板并修改代码，使工作流单元测试通过。
3. 运行完整测试套件，确认页面、存储、提交和结果收集无回归。
4. 向本机 ComfyUI `/prompt` 做不入队的验证不可用，因此采用 ComfyUI 的节点定义与本地结构校验，并通过测试中的假客户端确认最终提交载荷。不得为验证而实际启动视频生成任务。

## 成功标准

- 工具健康接口显示新 API 模板路径。
- 提交载荷使用 8-step Turbo LoRA 与 SageAttention 链路。
- 4-step LoRA 和 TeaCache 不参与执行。
- 所有现有页面控制继续影响对应工作流字段。
- 完整自动化测试通过，且验证过程不产生新的视频任务。
