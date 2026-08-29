param(
    [string]$SuiteRoot = 'G:\ComfyUI\custom_nodes\Herrgotts-H3-Infinite-Continuation-Suite',
    [string]$WorkflowDir = 'G:\ComfyUI\user\default\workflows'
)

$variants = @(
    @{
        Source = 'Herrgotts_H3_Infinite_v1.4_01_Start.json'
        Destination = 'MiniMax_H3_FL2VA_Turbo8_Latent续镜_01_首段.json'
        Heading = '# MiniMax H3 FL2VA Turbo8 — 首段'
    },
    @{
        Source = 'Herrgotts_H3_Infinite_v1.4_02_Continue.json'
        Destination = 'MiniMax_H3_FL2VA_Turbo8_Latent续镜_02_后续段.json'
        Heading = '# MiniMax H3 FL2VA Turbo8 — 后续段'
    }
)

foreach ($variant in $variants) {
    $sourcePath = Join-Path (Join-Path $SuiteRoot 'examples') $variant.Source
    $destinationPath = Join-Path $WorkflowDir $variant.Destination
    $workflow = Get-Content -Raw -LiteralPath $sourcePath | ConvertFrom-Json

    $conditioner = $workflow.nodes | Where-Object { $_.type -in @('H3ContinuousStartV14', 'H3ContinuousContinueV14') }
    $conditioner.widgets_values[1] = 480
    $conditioner.widgets_values[2] = 864
    $conditioner.widgets_values[3] = 15.0

    $scheduler = $workflow.nodes | Where-Object type -eq 'BasicScheduler'
    $scheduler.widgets_values[0] = 'simple'
    $scheduler.widgets_values[1] = 8
    $scheduler.title = 'Turbo 8Step — simple / res_multistep'

    $modelLoader = $workflow.nodes | Where-Object id -eq 1
    $sage = $workflow.nodes | Where-Object id -eq 20
    $oldModelLink = $workflow.links | Where-Object { $_[0] -eq 22 }
    $newNodeId = [int]$workflow.last_node_id + 1
    $newLinkId = [int]$workflow.last_link_id + 1

    foreach ($node in $workflow.nodes) {
        if ([int]$node.order -ge 19) {
            $node.order = [int]$node.order + 1
        }
    }

    $modelLoader.outputs[0].links = @(22)
    $oldModelLink[3] = $newNodeId
    $sage.inputs[0].link = $newLinkId

    $lora = [pscustomobject]@{
        id = $newNodeId
        type = 'LoraLoaderModelOnly'
        pos = @(-840, 40)
        size = @(420, 82)
        flags = [pscustomobject]@{}
        order = 19
        mode = 0
        inputs = @([pscustomobject]@{ name = 'model'; type = 'MODEL'; link = 22 })
        outputs = @([pscustomobject]@{ name = 'MODEL'; type = 'MODEL'; links = @($newLinkId) })
        title = 'FL2VA Turbo 8Step LoRA'
        properties = [pscustomobject]@{ 'Node name for S&R' = 'LoraLoaderModelOnly' }
        widgets_values = @('minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors', 1.0)
    }
    $workflow.nodes += $lora
    $workflow.links += ,@($newLinkId, $newNodeId, 0, 20, 0, 'MODEL')
    $workflow.last_node_id = $newNodeId
    $workflow.last_link_id = $newLinkId

    $startNote = $workflow.nodes | Where-Object id -eq 24
    $existingNote = [string]$startNote.widgets_values[0]
    $startNote.widgets_values[0] = $variant.Heading + @'

- 480 × 864 portrait, 15 seconds, 24 fps
- FL2VA Turbo 8Step LoRA enabled
- SageAttention enabled
- Native Masked AV latent context: 39 frames (~1.625 s)
- TeaCache intentionally omitted for initial seam/stability validation

'@ + $existingNote

    $json = $workflow | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText($destinationPath, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Output $destinationPath
}
