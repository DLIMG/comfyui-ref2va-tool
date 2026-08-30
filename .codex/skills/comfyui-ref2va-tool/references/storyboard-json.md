# comfyui-ref2va-tool 故事板 JSON 规范

## 一、顶层结构

```json
{
  "name": "项目名称",
  "project_dir": "G:\\AI短剧生成\\项目目录",
  "advanced_settings": {
    "turbo_lora_enabled": true,
    "sage_attention_enabled": true,
    "generation_target": "local",
    "comfy_url": "http://192.168.3.200:8188"
  },
  "shots": []
}
```

| 字段 | 必需 | 类型 | 规则 |
|---|---|---|---|
| `name` | 是 | 字符串 | 网页显示的项目名称。 |
| `project_dir` | 建议 | 字符串 | 项目绝对路径。结果保存到`<project_dir>\06_生成视频`；为空时使用工具的`data\results`。 |
| `advanced_settings` | 否 | 对象 | 全局生成加速设置；缺失时两项均默认为`true`，以保持旧JSON行为。 |
| `shots` | 是 | 数组 | 按播放和排队顺序排列的分镜。每项必须是对象，并具有唯一、非空的字符串`id`。 |

`advanced_settings.generation_target`取值为`local`或`remote`；本机固定使用`http://127.0.0.1:8188`，远端地址由`advanced_settings.comfy_url`指定。远端模式会自动上传当前分镜素材并把输出视频下载回本机结果目录。`advanced_settings.turbo_lora_enabled=false`时，工作流跳过Turbo LoRA，并从8步恢复为15步基础采样。`advanced_settings.sage_attention_enabled=false`时，工作流跳过SageAttention节点。

导入文件中的`shots`决定最终片段成员和排列顺序。导入文件未包含的片段不会保留在导入后的故事板中。

## 二、片段对象

完整、可移植的片段使用以下字段：

| 字段 | 类型 | 说明与限制 |
|---|---|---|
| `id` | 字符串 | 稳定且唯一的片段号，例如`01A`；也是导入时保留视频结果的匹配键。 |
| `title` | 字符串 | 网页显示的片段标题。 |
| `references` | 字符串数组 | 真实存在的绝对图片路径，顺序对应`<Picture N>`；提交时至少一张。 |
| `reference_videos` | 字符串数组 | R2VA参考视频的绝对路径，顺序对应`<Video N>`，同序号原声对应`<Audio N>`；每段2–15秒，最多3段。可与图片同时使用；当前FL2VA不支持。 |
| `generation_mode` | 字符串 | `r2va`或`fl2va`。缺失时按兼容规则视为`r2va`。 |
| `continue_from_previous` | 布尔值 | 是否使用紧邻上一镜保存的Masked AV latent上下文；第一镜必须为`false`。 |
| `save_latent` | 布尔值 | 是否保存当前镜的AV latent与handover，默认`false`；若下一镜开启延续则软件自动强制保存。 |
| `prompt` | 字符串 | 非空视频提示词。默认按模式使用H3结构化格式：R2VA六段式，FL2VA首尾帧对齐说明加三核心字段；也兼容自由文本。 |
| `duration` | 数字 | 视频秒数，必须大于零，并符合当前模型和工作流支持范围。 |
| `seed` | 整数 | 写入工作流的随机种子。 |
| `resolution` | 字符串 | 网页支持`480p`、`720p`、`1080p`。 |
| `aspect_ratio` | 字符串 | 网页支持`16:9`、`9:16`、`4:3`、`3:4`、`1:1`。 |
| `output_name` | 字符串 | 唯一输出名前缀；可用中英文、数字、下划线、点和连字符，不能包含斜杠、冒号或路径语法。 |
| `selected` | 布尔值 | 网页勾选状态；干净交付文件通常为`false`。 |
| `status` | 字符串 | `draft`、`invalid`、`queued`、`running`、`completed`或`failed`；干净交付使用`draft`。 |
| `prompt_id` | 字符串 | ComfyUI任务ID；干净交付留空，不得伪造。 |
| `run_dir` | 字符串 | 本次提交记录目录；干净交付留空。 |
| `comfy_url` | 字符串 | 运行时记录该分镜实际使用的ComfyUI地址；干净交付可留空。续镜必须与上一镜一致。 |
| `error` | 字符串 | 最近一次运行错误；干净交付留空。 |
| `results` | 数组 | 工具管理的视频结果；干净交付为空数组，不得伪造记录。 |

## 三、H3提示词规定

新建、自动改写和正式交付的提示词默认严格采用`h3-prompt-writing`规范；只有用户明确要求，或导入、兼容、快速试验已有内容时使用自由文本。软件接受任何非空自由文本，不以缺少结构化字段为由阻止保存或提交。

### R2VA

严格按照以下顺序使用六个段落名：

1. `subject_definitions:`
2. `summary:`
3. `retention_analysis:`
4. `detailed_description:`
5. `overall_soundscape:`
6. `non_diegetic_music:`

六段正文使用英文；只有`<d>`内的对白/歌词和画面内可见文字保留原语言。`detailed_description`使用`[Shot 1]`以及后续`[Shot N] At MM:SS.mmm, ...`格式，并保持说话者`(Sx)`、引用标签和时间点全程一致。

### FL2VA

严格使用`h3-prompt-writing/references/base-en.txt`的格式：第一行是帧对齐说明，空一行后依次为：

1. `integrated_multimodal_description:`
2. `overall_soundscape:`
3. `non_diegetic_music:`

- `continue_from_previous=false`：使用FL2VA对齐句，`<Picture 1>`对齐0.00秒首帧，`<Picture 2>`对齐有效视频时长的尾帧。
- `continue_from_previous=true`：开头由上一镜Masked AV latent提供，使用L2VA对齐句；`<Picture 1>`只对齐有效视频时长的尾帧，不得虚构一个图片首帧。

主体、姿态、物体状态、构图和镜头必须沿连续可见路径收敛到尾帧。除非用户明确指定切镜，FL2VA优先单镜连续运动。

### 自由文本兼容

自由文本不要求上述标题，但仍必须非空，并满足参考编号不冲突、时间不超出有效时长、动作可执行、对白与控制说明分离。不得仅因其不是结构化格式而自动改写或拒绝提交。

图片顺序由生成模式决定：

- `r2va`：`references[0]`对应`<Picture 1>`，依次连续编号。即使开启latent续镜，参考图片仍按R2VA Picture规则使用。
- `r2va`视频：`reference_videos[0]`对应`<Video 1>`，视频原声对应`<Audio 1>`，依次独立编号；Picture与Video编号互不占位。
- `fl2va`且不延续：前两张依次为首帧、尾帧，其余图片按顺序作为Qwen参考图。
- `fl2va`且延续：开头由上一镜Masked AV latent提供；第一张是当前镜头的新尾帧，其余图片作为Qwen参考图。

R2VA续镜同时使用R2VA参考条件和上一镜Masked AV目标latent。上一镜latent不是`<Video 1>`，无需在提示词中把它声明为Picture或Video。

原生音频对白应放入明确标签，例如`<d>[Chinese] 台词。</d>`。不要把“说话者为谁”“必须先说完”等制作说明写成容易被模型朗读的自然对白。若片段只有一句话，应明确整个片段只有该对白标签内部文字允许被说出。

## 四、干净导入示例

```json
{
  "name": "《示例项目》",
  "project_dir": "G:\\AI短剧生成\\示例项目",
  "shots": [
    {
      "id": "01A",
      "title": "开场",
      "references": [
        "G:\\AI短剧生成\\示例项目\\03_角色资产\\主角.png",
        "G:\\AI短剧生成\\示例项目\\04_场景资产\\开场.png"
      ],
      "reference_videos": [],
      "generation_mode": "r2va",
      "continue_from_previous": false,
      "save_latent": true,
      "prompt": "subject_definitions:\n<Subject 1> is the protagonist in <Picture 1>, preserving the referenced face, hairstyle, build, and clothing.\n<Subject 2> is the environment in <Picture 2>, preserving its spatial layout, key objects, perspective, and lighting direction.\nsummary:\n[reference generation] The target video is a restrained live-action opening in which <Subject 1> performs one clear action inside <Subject 2>.\nretention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - the referenced identity, hairstyle, build, and clothing remain unchanged.\n<Subject 2> (appears in [Shot 1]): fully_preserved - the referenced layout, key objects, perspective, and lighting direction remain unchanged.\ndetailed_description:\nThe target video uses a restrained cinematic live-action style with natural lighting.\n[Shot 1] A medium shot frames <Subject 1> inside <Subject 2>, preserving the referenced spatial relationships and screen direction. The camera pushes in with small amplitude at slow speed as <Subject 1> completes one clearly visible action, then settles into a stable final pose without introducing additional characters or objects.\noverall_soundscape:\nLow room tone continues beneath the soft sound produced by the subject's single action.\nnon_diegetic_music:\nSparse low piano notes at a slow tempo remain quiet throughout.\n",
      "duration": 7,
      "seed": 101001,
      "resolution": "480p",
      "aspect_ratio": "9:16",
      "output_name": "01A_开场",
      "selected": false,
      "status": "draft",
      "prompt_id": "",
      "run_dir": "",
      "error": "",
      "results": []
    }
  ]
}
```

JSON使用UTF-8保存，中文可直接保留，不要求转成ASCII转义。

## 五、导入与运行状态合并

导入按照片段ID匹配：

- 项目名称、配置、片段成员和顺序以导入文件为准。
- 导入文件包含非空`project_dir`时使用导入值；为空或缺失时沿用当前项目值。
- 相同ID的片段若导入`results`非空，则使用导入文件中的整组运行状态。
- 相同ID的片段若导入`results`为空或缺失，则保留当前片段的`prompt_id`、`run_dir`、`status`、`error`和`results`。
- `shots`不是数组、片段不是对象、ID为空或ID重复时，导入直接失败，不覆盖当前故事板。

因此：

- 重新导入干净JSON时，只要片段ID不变，已有视频不会消失。
- 生成后修改片段ID会失去结果匹配。
- 只有运行记录和文件路径均真实存在时，才可导入非空`results`；不要手写虚假结果。

## 六、结果记录

结果记录由工具生成，不属于干净JSON的必填内容：

```json
{
  "id": "结果ID",
  "created_at": "2026-08-21T08:00:00+00:00",
  "prompt_id": "ComfyUI任务ID",
  "path": "G:\\AI短剧生成\\示例项目\\06_生成视频\\01A\\...\\01A_开场_00001_.mp4",
  "filename": "01A_开场_00001_.mp4",
  "source": {
    "filename": "01A_开场_00001_.mp4",
    "subfolder": "codex_ref2va_tool",
    "type": "output"
  },
  "status": "ready",
  "error": ""
}
```

视频读取和删除接口只接受当前项目`06_生成视频`或旧版`data\results`目录内的文件。收集结果采用复制方式，不移动或删除ComfyUI原始输出。

## 七、验证清单

- JSON能够解析。
- 顶层`shots`是数组。
- 每个片段都是对象，且具有唯一、非空的字符串ID。
- 所有`references`都是存在的绝对文件路径。
- 所有`reference_videos`都是存在的受支持视频路径；仅用于R2VA，数量不超过3。
- 参考图顺序与Picture编号一致。
- `generation_mode`是`r2va`或`fl2va`，且图片顺序符合所选模式。
- 第一镜没有开启`continue_from_previous`；每个续镜前面都有可生成latent的紧邻上一镜。
- 提示词非空。默认结构化提示词按模式验证：R2VA六段齐全且顺序正确；FL2VA对齐说明与三核心字段齐全且顺序正确。用户明确选择自由文本时，只做内容与安全检查，不强制结构化。
- `duration`是大于零的数字。
- `output_name`非空、唯一，不含路径分隔符或特殊标点。
- `resolution`和`aspect_ratio`使用网页支持值。
- 干净交付使用`selected=false`、`status=draft`、空运行字段和`results=[]`。
- `project_dir`存在时必须是绝对路径。
- 另外核对具体项目规定的片段数量和总时长。

## 八、常见问题

| 表现 | 原因 | 处理 |
|---|---|---|
| Picture身份错乱 | 参考数组顺序与提示词编号不一致 | 调整`references`或重新编号Picture。 |
| JSON导入失败 | ID重复、ID为空或`shots`结构错误 | 修正ID，确保每个片段都是对象。 |
| 修改ID后旧视频不见 | 导入依靠`id`匹配结果 | 生成后保持片段ID稳定。 |
| 显示已完成但结果为0 | 输出尚未收集，或运行状态曾丢失 | 使用结果收集或恢复流程，不要伪造路径。 |
| 人物朗读控制说明 | 普通控制语被当成对白 | 只在明确对白标签中放置可朗读文字。 |
| 视频没有进入项目目录 | 未设置`project_dir` | 提交前设置项目绝对路径。 |
| 续镜找不到latent | 上一镜未生成、输出名被修改，或ComfyUI未加载continuation节点 | 先重启ComfyUI并按故事板顺序生成；保持上一镜`output_name`稳定。 |
| FL2VA首尾帧颠倒 | 前两张图片顺序错误 | 第1张放首帧，第2张放尾帧。 |

## 九、Latent运行状态

每次生成会在`G:\ComfyUI\output\codex_ref2va_tool\latents`保存完整H3视频/音频latent及handover元数据，文件名由`output_name`确定。该文件是本机运行状态，不是干净JSON字段；导出故事板不会嵌入latent内容。

延续镜头在提交时根据故事板顺序读取紧邻上一镜的`output_name`。使用“全部排队”时，ComfyUI按顺序先保存上一镜latent，再执行下一镜；单独提交续镜前必须确保上一镜latent已经存在。
