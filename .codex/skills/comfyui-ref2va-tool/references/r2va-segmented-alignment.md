# R2VA 分段参考视频与 Latent 帧对齐规范

## 适用条件

遇到以下任一情况时使用本规范：

- 把一段长参考视频拆成多个R2VA镜头；
- R2VA参考视频自带声音，并与Masked AV latent续镜同时使用；
- 第一镜正常，但第二镜开始声音、嘴型或动作节奏混乱；
- 网页填写5秒，成片只有约4–5秒；
- 需要精确规划总帧数、总时长或最终铺回原声。

## 核心事实

1. H3原生视频是24fps，并使用`17k+5`合法帧格；用户请求秒数不会保证成为相同的最终可见秒数。
2. `H3ContinuousContinueV14`默认使用39帧（1.625秒）Masked AV上下文。续镜内部先放置这39帧，最终Stitch Ready输出再移除它们。
3. 首镜若要供下一镜续接，Stitch Ready通常还会移除安全handover尾部；实际裁剪量以handover分析结果为准，常见为17帧，不能预先把请求时长当成最终时长。
4. R2VA续镜同时接收上一镜latent和当前参考视频条件。若当前参考视频直接从新段边界开始，它的第0帧/第0秒会错误地对应内部39帧接续头，导致从第二镜起音频、嘴型和动作整体错位。
5. `No Audio Carryover`只解决“上一镜音频latent被保护”的冲突；它不会自动修正当前参考音视频与39帧隐藏头的时间轴偏移。

## 先计算，再切片

使用节点包中的真实函数作为帧数来源，不手算近似值：

```python
from release_utils import (
    align_frame_count,
    duration_to_requested_frames,
    masked_av_duration_plan,
)

first_requested = duration_to_requested_frames(first_duration)
first_total = align_frame_count(first_requested)
continue_plan = masked_av_duration_plan(
    continue_duration, 39, "Net New Content"
)
```

需要区分：

- `first_total`：首镜内部总帧数；
- 首镜可见帧数：`first_total - 实际安全尾裁帧数`；
- `continue_plan.total_frame_count`：续镜内部总帧数；
- `continue_plan.context_frames`：隐藏接续头，通常39帧；
- `continue_plan.net_new_frames`：续镜最终可见新内容帧数。

## 续镜参考素材必须包含前置重叠

设：

- 上一镜在原参考视频中的可见结束边界为`B`；
- 隐藏上下文为`C=39`帧；
- 续镜内部总帧数为`T`；
- fps为24。

则续镜参考素材应为：

```text
开始时间 = B - C / 24
参考帧数 = T
参考时长 = T / 24
```

参考视频的前39帧对应上一镜末尾的latent头；剩余`T-39`帧对应最终可见的新内容。画面和原声必须从同一个切点一起编码，不能分别偏移。

不要使用以下错误切法：

```text
镜1：原片 0–5秒
镜2：原片 5–10秒
```

若镜2使用39帧latent头，正确结构应类似：

```text
镜2参考：原片 3.375–约10秒
前1.625秒：隐藏对齐头
后续部分：可见新内容
```

具体终点必须由合法帧格决定，不能固定写成整数秒。

## R2VA分段音频策略

当每个续镜都提供带同步原声的当前参考视频时，优先使用：

```json
"audio_tail_carryover": "No Audio Carryover",
"audio_feather_ticks": 0
```

含义：

- 视频latent仍继承39帧，维持姿势、身份、相机和光线连续；
- 上一镜音频latent不受保护；
- 当前镜音频和嘴型由包含39帧前置重叠的当前`<Video 1>/<Audio 1>`驱动。

仅在没有当前同步参考音频、且必须保留上一镜未结束的对白时，考虑`Match Video Handover`或`Full Previous Tail`。若声音与嘴型同时从第二镜崩坏，先检查实际`run.json`中的`audio_tail_carryover`和参考视频路径，不凭网页显示或记忆判断。

## 提示词时间轴

分镜提示词使用当前最终可见片段的局部时间轴，不使用原片绝对区间。

正确：

```text
Visible local timeline: 00:00.000-00:04.958.
```

错误：

```text
From 00:05.000 to 00:10.000...
```

原片区间只用于文件名、制作记录和切片计算，不要作为当前镜头动作时间交给模型。续镜提示词应明确：

```text
The first 39 internal frames are hidden alignment context.
The visible local timeline starts after them.
```

所有动作时间点必须小于或等于实际预计可见时长；若预计可见119帧，提示词终点写`00:04.958`，不要写`00:05.000`。

## 719帧对齐实例

目标约30秒、24fps、6镜、39帧续镜头时，可采用：

```text
首镜：内部141帧，安全尾裁17帧，可见124帧（5.167秒）
续镜2–6：各内部158帧，裁39帧头，各可见119帧（4.958秒）
总计：124 + 119×5 = 719帧 = 29.958秒
```

对应参考素材：

- 首镜参考141帧；
- 每个续镜参考158帧，其中前39帧是前置重叠；
- 每个续镜的原片可见边界以上一镜真实可见帧数累加，不使用固定5秒整数切点。

这只是一个已验证实例，不是所有项目的固定模板。安全尾裁帧数、上下文帧数、时长模式或模型节点变化后，必须重新计算。

## ffmpeg与ffprobe检查

切片时强制统一24fps，并用明确帧数限制视频轨。音频与画面从同一`-ss`开始，使用相同目标时长。编码后逐段检查：

```powershell
ffprobe -v error -count_frames `
  -show_entries format=duration `
  -show_entries stream=codec_type,nb_read_frames,r_frame_rate,sample_rate,channels,duration `
  -of json <segment.mp4>
```

必须确认：

- 首镜参考帧数等于首镜内部帧数；
- 续镜参考帧数等于`total_frame_count`；
- fps为`24/1`；
- 每段包含预期音轨；
- JSON路径指向新对齐素材，而非旧5秒素材；
- 新版本使用新的`id`和`output_name`，避免导入时合并旧结果。

生成后再次用ffprobe读取实际输出，不以网页`duration`字段或肉眼播放器取整作为证据。总时长以实际视频帧数之和除以24计算。

## 排查顺序

当第一镜正常、第二镜立即异常时，依次检查：

1. 读取第二镜最新`run.json`，确认实际提交的音频carryover模式和参考路径；
2. ffprobe第二镜参考视频，确认包含39帧前置重叠且总帧数匹配内部目标；
3. 确认参考视频画面和音频从同一原片切点编码；
4. 确认提示词采用可见局部时间轴；
5. ffprobe输出，比较视频帧数和音频时长；
6. 只有以上全部正确后，才判断模型本身的音频生成不稳定；最终要求原声完全一致时，生成画面后统一铺回原片音轨。
