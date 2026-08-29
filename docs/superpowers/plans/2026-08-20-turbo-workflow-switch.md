# MiniMax H3 Turbo Workflow Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the Ref2VA tool to a checked-in API-form MiniMax H3 8-step Turbo workflow while preserving every existing per-shot control and keeping the 4-step LoRA and TeaCache disabled.

**Architecture:** Preserve the current `load_template` → `build_workflow` → `ComfyClient.submit` data flow. Add one immutable API workflow asset derived from the user-validated ComfyUI graph, then strengthen template validation so tests prove the active model chain is UNET → 8-step LoRA → SageAttention, with the bypassed 4-step LoRA and TeaCache absent from execution.

**Tech Stack:** Python 3.11, FastAPI, pytest, ComfyUI API workflow JSON.

---

## File map

- Create `app/templates/minimax_h3_turbo_8step_ref2va_api.json`: executable API graph derived from the validated UI workflow.
- Modify `app/workflow.py`: define and validate the new static graph contract; retain dynamic shot input replacement.
- Modify `app/main.py`: use the project-owned template by default.
- Modify `tests/test_workflow.py`: test the new template and active acceleration chain.
- Modify `tests/test_api.py`: test that the application submits a customized copy of the new graph.
- Modify `README.md`: document the new template and default enabled/disabled accelerators.

### Task 1: Lock the new graph contract with failing tests

**Files:**
- Modify: `tests/test_workflow.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Replace the external template constant and add active-chain assertions**

Use the project asset path and require the exact model chain:

```python
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "minimax_h3_turbo_8step_ref2va_api.json"


def test_real_template_uses_turbo_8step_without_4step_or_teacache():
    workflow = load_template(TEMPLATE)

    assert workflow["150"]["class_type"] == "LoraLoaderModelOnly"
    assert workflow["150"]["inputs"]["lora_name"] == (
        "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
    )
    assert workflow["150"]["inputs"]["model"] == ["127", 0]
    assert workflow["142"]["class_type"] == "MiniMaxH3MemoryEfficientSageAttentionPatch"
    assert workflow["142"]["inputs"]["model"] == ["150", 0]
    assert workflow["124"]["inputs"]["model"] == ["142", 0]
    assert workflow["126"]["inputs"]["model"] == ["142", 0]
    assert all(node.get("class_type") != "MiniMaxH3TeaCache" for node in workflow.values())
    assert all(
        node.get("inputs", {}).get("lora_name")
        != "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
        for node in workflow.values()
    )
    assert workflow["124"]["inputs"]["scheduler"] == "simple"
    assert workflow["124"]["inputs"]["steps"] == 8
    assert workflow["123"]["inputs"]["sampler_name"] == "res_multistep"
```

- [ ] **Step 2: Retain and adapt dynamic-input tests**

Keep the existing arbitrary-reference-count, immutability, resolution, aspect-ratio, prompt, duration, seed, and output-prefix assertions. Change only their template path and model snapshots:

```python
original_model = copy.deepcopy(template["127"])
original_lora = copy.deepcopy(template["150"])
original_sage = copy.deepcopy(template["142"])
# After build_workflow(...):
assert result["127"] == original_model
assert result["150"] == original_lora
assert result["142"] == original_sage
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_workflow.py -v
```

Expected: FAIL because `app/templates/minimax_h3_turbo_8step_ref2va_api.json` does not exist.

### Task 2: Add the derived API workflow asset

**Files:**
- Create: `app/templates/minimax_h3_turbo_8step_ref2va_api.json`
- Reference only: `G:\ComfyUI\user\default\workflows\MiniMax_H3_Turbo_8Step_LoRA_SageAttention_TeaCache_R2VA_480P.json`

- [ ] **Step 1: Create the API-form graph from the validated UI graph**

Create a top-level object keyed by string node IDs. Each node must have exactly `class_type` and `inputs`. Include executable nodes 92, 115, 119–132, 136, 138, 142, 144–148, and 150. Exclude notes, node 151, bypassed node 152, and bypassed node 141.

Apply bypass rewiring explicitly:

```json
"150": {
  "class_type": "LoraLoaderModelOnly",
  "inputs": {
    "model": ["127", 0],
    "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
    "strength_model": 1.0
  }
},
"142": {
  "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
  "inputs": {"model": ["150", 0]}
}
```

Both `BasicScheduler.inputs.model` and `BasicGuider.inputs.model` must point to `["142", 0]`. Preserve all other widget values and links from the validated source graph, including VAE, CLIP, decode, video creation, frame expression, resolution selector, sampler, scheduler, and SaveVideo settings.

- [ ] **Step 2: Validate every class and input name against live ComfyUI metadata**

Run:

```powershell
$info = Invoke-RestMethod http://127.0.0.1:8188/object_info
$api = Get-Content -Raw app/templates/minimax_h3_turbo_8step_ref2va_api.json | ConvertFrom-Json -AsHashtable
$api.GetEnumerator() | ForEach-Object {
  if (-not $info.PSObject.Properties[$_.Value.class_type]) {
    throw "Unknown class at node $($_.Key): $($_.Value.class_type)"
  }
}
"Validated $($api.Count) node classes"
```

Expected: prints the validated node count without throwing.

- [ ] **Step 3: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_workflow.py -v
```

Expected: the new graph-contract tests may still fail only where `app/workflow.py` retains the old validation contract; JSON parsing and active-chain assertions pass.

### Task 3: Update template validation and the default path

**Files:**
- Modify: `app/workflow.py`
- Modify: `app/main.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Strengthen the target contract in `app/workflow.py`**

Add the new active nodes without changing the existing dynamic target IDs:

```python
TARGETS = {
    "condition": ("136", "MiniMaxH3ReferenceToVideo"),
    "prompt": ("138", "PrimitiveStringMultiline"),
    "duration": ("132", "PrimitiveFloat"),
    "seed": ("129", "RandomNoise"),
    "save": ("92", "SaveVideo"),
    "resolution": ("115", "ResolutionSelector"),
    "sampler": ("123", "KSamplerSelect"),
    "scheduler": ("124", "BasicScheduler"),
    "model": ("127", "UNETLoader"),
    "turbo_lora": ("150", "LoraLoaderModelOnly"),
    "sageattention": ("142", "MiniMaxH3MemoryEfficientSageAttentionPatch"),
}

DISABLED_CLASS_TYPES = {"MiniMaxH3TeaCache"}
DISABLED_LORAS = {"minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"}
```

After the existing node/type/input loop, reject disabled nodes and require exact active connections and settings:

```python
if any(node.get("class_type") in DISABLED_CLASS_TYPES for node in workflow.values()):
    raise ValueError("TeaCache 必须保持关闭")
if any(node.get("inputs", {}).get("lora_name") in DISABLED_LORAS for node in workflow.values()):
    raise ValueError("Ref2V 4-step LoRA 必须保持关闭")
if workflow["150"]["inputs"].get("model") != ["127", 0]:
    raise ValueError("8-step Turbo LoRA 模型连接不正确")
if workflow["142"]["inputs"].get("model") != ["150", 0]:
    raise ValueError("SageAttention 模型连接不正确")
for node_id in ("124", "126"):
    if workflow[node_id]["inputs"].get("model") != ["142", 0]:
        raise ValueError(f"节点 {node_id} 未使用 SageAttention 输出")
```

- [ ] **Step 2: Point `app/main.py` at the checked-in asset**

Replace the external default:

```python
DEFAULT_TEMPLATE = ROOT / "app" / "templates" / "minimax_h3_turbo_8step_ref2va_api.json"
```

- [ ] **Step 3: Run workflow and API tests**

Run:

```powershell
python -m pytest tests/test_workflow.py tests/test_api.py -v
```

Expected: PASS.

### Task 4: Prove the application submits the new customized graph

**Files:**
- Modify: `tests/test_api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add a submission-payload regression test**

Extend the fake Comfy client to retain its submitted workflow, then assert the API endpoint preserves the active chain and applies shot values:

```python
def test_submit_uses_turbo_graph_and_dynamic_values(client, fake_comfy, image_path):
    response = client.post(
        "/api/submit",
        json={
            "references": [str(image_path)],
            "prompt": "summary:\n测试",
            "duration": 8,
            "seed": 12345,
            "output_name": "turbo_test",
            "resolution": "720p",
            "aspect_ratio": "9:16",
        },
    )

    assert response.status_code == 200
    workflow = fake_comfy.submitted_workflow
    assert workflow["150"]["inputs"]["model"] == ["127", 0]
    assert workflow["142"]["inputs"]["model"] == ["150", 0]
    assert workflow["124"]["inputs"]["model"] == ["142", 0]
    assert workflow["138"]["inputs"]["value"] == "summary:\n测试"
    assert workflow["132"]["inputs"]["value"] == 8.0
    assert workflow["129"]["inputs"]["noise_seed"] == 12345
    assert workflow["115"]["inputs"]["megapixels"] == 0.9
    assert workflow["115"]["inputs"]["aspect_ratio"] == "9:16 (Portrait Widescreen)"
    assert workflow["92"]["inputs"]["filename_prefix"] == "codex_ref2va_tool/turbo_test"
```

- [ ] **Step 2: Run the single test and verify RED before changing any fixture code**

Run:

```powershell
python -m pytest tests/test_api.py::test_submit_uses_turbo_graph_and_dynamic_values -v
```

Expected: FAIL because the fake client does not yet retain `submitted_workflow`.

- [ ] **Step 3: Make the fake client retain the submitted workflow**

In its `submit` method, add only:

```python
self.submitted_workflow = workflow
```

- [ ] **Step 4: Rerun the API test**

Run:

```powershell
python -m pytest tests/test_api.py::test_submit_uses_turbo_graph_and_dynamic_values -v
```

Expected: PASS.

### Task 5: Update operator documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the API template location**

Document:

```markdown
- API 工作流模板：`app\templates\minimax_h3_turbo_8step_ref2va_api.json`
```

- [ ] **Step 2: Add the default acceleration state**

Add:

```markdown
- 默认启用 MiniMax H3 Turbo 8-step LoRA 和 SageAttention。
- 默认关闭 Ref2V Turbo 4-step LoRA 和 TeaCache；工具页面不会改变这两个状态。
```

- [ ] **Step 3: Verify README no longer references the old template**

Run:

```powershell
Select-String -Path README.md -Pattern 'D:\\Edges Downloads|官方参数_SageAttention_TeaCache'
```

Expected: no matches.

### Task 6: Full verification without enqueuing generation

**Files:**
- Verify only; do not modify production state.

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Validate the template against live `/object_info`**

Run the class validation command from Task 2 again and confirm every class exists. Do not call `/prompt`, because that endpoint enqueues a real generation.

- [ ] **Step 3: Start the app with a throwaway data directory through its test factory and check health metadata**

Run:

```powershell
python -c "from app.main import create_app, DEFAULT_TEMPLATE; from fastapi.testclient import TestClient; c=TestClient(create_app(data_dir='data/verify-temp')); r=c.get('/api/health'); print(r.json()['template']); assert str(DEFAULT_TEMPLATE) == r.json()['template']"
```

Expected: prints the absolute project-owned Turbo API template path and exits 0. Remove only the explicitly created `data/verify-temp` directory after resolving and confirming it is inside the project data directory.

- [ ] **Step 4: Review the final diff/file list**

Because this directory is not a Git repository, list the exact modified files and inspect their contents directly. Confirm no storyboard, uploads, existing run records, results, source UI workflow, or ComfyUI queue state changed.

