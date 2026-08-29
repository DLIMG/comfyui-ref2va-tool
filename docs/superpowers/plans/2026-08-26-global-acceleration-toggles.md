# Global Acceleration Toggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-wide, default-on Turbo LoRA and SageAttention switches that control every submitted storyboard shot.

**Architecture:** Store both booleans in the storyboard top-level `advanced_settings` object, normalize missing values to `true` for backward compatibility, and include them in every `/api/submit` request. The workflow builder bypasses optional acceleration nodes and rewires the scheduler/guider to the last enabled model stage; disabling Turbo restores the suite's 15-step non-Turbo baseline.

**Tech Stack:** FastAPI/Pydantic, Python workflow transformation, vanilla JavaScript/HTML/CSS, pytest.

---

### Task 1: Workflow acceleration configuration

**Files:**
- Modify: `app/workflow.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Write failing tests** asserting all four Turbo/Sage combinations, node removal, model rewiring, and 8-step versus 15-step sampling.
- [ ] **Step 2: Run `python -m pytest tests/test_workflow.py -q`** and confirm failures are caused by the missing keyword arguments.
- [ ] **Step 3: Add `turbo_lora_enabled` and `sage_attention_enabled` parameters and a focused rewiring helper.**
- [ ] **Step 4: Re-run the workflow tests** and confirm they pass.

### Task 2: Submit API propagation

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write a failing API test** that submits both switches disabled and inspects the emitted workflow and saved request.
- [ ] **Step 2: Run the targeted API test** and confirm the new request fields are not yet accepted/propagated.
- [ ] **Step 3: Add default-on fields to `SubmitBody` and pass them to `build_shot_workflow`.**
- [ ] **Step 4: Re-run the targeted API test** and confirm it passes.

### Task 3: Global advanced controls and persistence

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/app.css`
- Modify: `app/storage.py`
- Test: `tests/test_storyboard_ui_features.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing static UI and default-project tests** for the advanced section, default-on normalization, save/import/new-project synchronization, and submit payload fields.
- [ ] **Step 2: Run the targeted tests** and confirm the controls/defaults are absent.
- [ ] **Step 3: Add the toolbar advanced panel, normalization/synchronization helpers, handlers, submit fields, and server-side default project settings.**
- [ ] **Step 4: Re-run the targeted tests** and confirm they pass.

### Task 4: Documentation and full verification

**Files:**
- Modify: `.codex/skills/comfyui-ref2va-tool/references/storyboard-json.md`

- [ ] **Step 1: Document `advanced_settings` and backward-compatible defaults.**
- [ ] **Step 2: Run `python -m pytest -q`.**
- [ ] **Step 3: Parse the template and exercise all four acceleration combinations without submitting to ComfyUI.**
- [ ] **Step 4: Inspect generated workflows to confirm disabled nodes are absent and model connections are valid.**
