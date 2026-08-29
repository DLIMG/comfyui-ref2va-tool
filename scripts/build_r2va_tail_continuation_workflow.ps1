param(
    [string]$Source = 'G:\ComfyUI\user\default\workflows\MiniMax_H3_Turbo_8Step_LoRA_SageAttention_TeaCache_R2VA_480P.json',
    [string]$Destination = 'G:\ComfyUI\user\default\workflows\MiniMax_H3_Turbo_8Step_R2VA_尾部视频续镜_480P.json'
)

$workflow = Get-Content -Raw -LiteralPath $Source | ConvertFrom-Json
$h3 = $workflow.nodes | Where-Object id -eq 136
$loader = $workflow.nodes | Where-Object id -eq 153

$loader.type = 'VHS_LoadVideoFFmpeg'
$loader | Add-Member -NotePropertyName title -NotePropertyValue '上一镜尾部视频（建议最后 2 秒 / 48 帧）' -Force
$loader.size = @(360, 690)
$loader.inputs = @(
    [pscustomobject]@{ name = 'video'; type = 'COMBO'; widget = [pscustomobject]@{ name = 'video' }; link = $null },
    [pscustomobject]@{ name = 'force_rate'; type = 'FLOAT'; widget = [pscustomobject]@{ name = 'force_rate' }; link = $null },
    [pscustomobject]@{ name = 'custom_width'; type = 'INT'; widget = [pscustomobject]@{ name = 'custom_width' }; link = $null },
    [pscustomobject]@{ name = 'custom_height'; type = 'INT'; widget = [pscustomobject]@{ name = 'custom_height' }; link = $null },
    [pscustomobject]@{ name = 'frame_load_cap'; type = 'INT'; widget = [pscustomobject]@{ name = 'frame_load_cap' }; link = $null },
    [pscustomobject]@{ name = 'start_time'; type = 'FLOAT'; widget = [pscustomobject]@{ name = 'start_time' }; link = $null },
    [pscustomobject]@{ name = 'upload'; type = 'IMAGEUPLOAD'; widget = [pscustomobject]@{ name = 'upload' }; link = $null }
)
$loader.outputs = @(
    [pscustomobject]@{ name = 'IMAGE'; type = 'IMAGE'; links = @(298) },
    [pscustomobject]@{ name = 'mask'; type = 'MASK'; links = $null },
    [pscustomobject]@{ name = 'audio'; type = 'AUDIO'; links = @(299) },
    [pscustomobject]@{ name = 'video_info'; type = 'VHS_VIDEOINFO'; links = $null }
)
$loader.properties = [pscustomobject]@{ 'Node name for S&R' = 'VHS_LoadVideoFFmpeg' }
$loader.widgets_values = @(
    'codex_ref2va_tool/01A_最后一段人类记忆_00001_.mp4',
    24,
    480,
    864,
    48,
    0,
    'image'
)

$h3.inputs[7].link = 298
$h3.inputs[8].link = 299
$h3.title = 'H3 REF2VA - 上一镜尾部视频续镜 / 15S'

$promptNode = $workflow.nodes | Where-Object id -eq 138
$promptNode.title = '续镜提示词：Video 1 为上一镜尾部'
$oldPrompt = [string]$promptNode.widgets_values[0]
$continuationRule = @'
<Video 1> is the final two-second motion-and-audio context from the immediately preceding shot.
The first frame of [Shot 1] must continue directly and seamlessly from the final frame of <Video 1>. Preserve the exact subject positions, body momentum, camera direction, lighting, color grade, environment state, ambient sound, and dialogue continuity established at the end of <Video 1>. Do not replay, summarize, reverse, freeze, or visibly restart the action from <Video 1>.

'@
$promptNode.widgets_values[0] = $continuationRule + $oldPrompt

$note = [pscustomobject]@{
    id = 154
    type = 'MarkdownNote'
    pos = @(1300, 1080)
    size = @(560, 620)
    flags = [pscustomobject]@{}
    order = 16
    mode = 0
    inputs = @()
    outputs = @()
    title = '使用说明：R2VA 尾部视频续镜（非原生 latent）'
    properties = [pscustomobject]@{}
    widgets_values = @(@'
# R2VA 尾部视频续镜

1. 在左侧视频加载节点选择上一镜成片。
2. `force_rate = 24`，`frame_load_cap = 48`，即最多读取 2 秒。
3. 把 `start_time` 设为“上一镜总时长 - 2 秒”。例如上一镜 15 秒，填写 13。
4. `<Video 1>` 已同时接入画面和原生音频参考。
5. 保留角色、场景参考图；提示词中必须明确下一步动作，不要复述上一段动作。
6. 若衔接处重复约 2 秒，剪辑时删掉新片开头的重叠内容，再在动作匹配点拼接。

这是 Ref2VA 的视频参考续写版，不是 AV latent 直传版。优点是你现有模型和节点可以直接使用；缺点是色彩、动作仍可能小幅漂移。
'@)
    color = '#1f3a4d'
    bgcolor = '#0b1820'
}
$workflow.nodes += $note
$workflow.links += ,@(298, 153, 0, 136, 7, 'IMAGE')
$workflow.links += ,@(299, 153, 2, 136, 8, 'AUDIO')
$workflow.last_node_id = 154
$workflow.last_link_id = 299

$json = $workflow | ConvertTo-Json -Depth 100
[System.IO.File]::WriteAllText($Destination, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output $Destination
