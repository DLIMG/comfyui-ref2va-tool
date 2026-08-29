# Mixed H3 Latent Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every storyboard shot choose R2VA or FL2VA First/Last Frame generation and optionally continue the immediately previous shot through protected H3 video/audio latent context.

**Architecture:** Keep storyboard configuration separate from runtime state. Add `generation_mode` and `continue_from_previous` to each shot, route workflow construction through mode-specific builders, and save a deterministic AV-latent sidecar for every successful generation. Continuation loads the previous shot's sidecar, applies `H3ContinuousContinueV14`, then uses either FL2VA conditioning or R2VA conditioning with the masked target latent.

**Tech Stack:** Python 3, FastAPI/Pydantic, ComfyUI API workflows, Herrgotts H3 Infinite Continuation v1.4 nodes, vanilla JavaScript/CSS, pytest.

---

### Task 1: Shot configuration and validation

**Files:**
- Modify: `app/validation.py`
- Modify: `tests/test_validation.py`

- [ ] **Step 1: Write failing tests** for supported `generation_mode` values, FL2VA keyframe requirements, and rejection of continuation on the first storyboard shot.
- [ ] **Step 2: Run** `python -m pytest tests/test_validation.py -q` and confirm the new tests fail because mode-aware validation is absent.
- [ ] **Step 3: Implement** constants for `r2va` and `fl2va`, plus mode-aware reference-count and previous-shot validation.
- [ ] **Step 4: Run** `python -m pytest tests/test_validation.py -q` and confirm all validation tests pass.

### Task 2: Mode-specific ComfyUI API workflow construction

**Files:**
- Create: `app/templates/minimax_h3_turbo_8step_fl2va_api.json`
- Modify: `app/workflow.py`
- Modify: `tests/test_workflow.py`

- [ ] **Step 1: Write failing workflow tests** asserting R2VA normal, FL2VA first/last, FL2VA continuation, and R2VA-conditioning-plus-masked-latent graphs.
- [ ] **Step 2: Run** `python -m pytest tests/test_workflow.py -q` and confirm failures identify the missing mixed-mode builder.
- [ ] **Step 3: Add the FL2VA template** using `H3ContinuousStartV14`, the existing FL2VA Turbo8 LoRA/Sage chain, dual VAE decode, auto handover, deterministic latent save, stitch output, and SaveVideo node 92.
- [ ] **Step 4: Implement workflow routing** that stages mode-appropriate images, loads the previous deterministic latent for continuation, uses 39-frame Native Masked AV context, and preserves R2VA conditioning when R2VA is selected.
- [ ] **Step 5: Run** `python -m pytest tests/test_workflow.py -q` and confirm all graph invariants pass.

### Task 3: Submit API and previous-shot resolution

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests** for mode forwarding, continuation previous-output resolution, first-shot rejection, and deterministic latent prefixes.
- [ ] **Step 2: Run** `python -m pytest tests/test_api.py -q` and confirm the new payload fields are rejected or ignored.
- [ ] **Step 3: Extend `SubmitBody` and `/api/submit`** with `generation_mode`, `continue_from_previous`, and `previous_output_name`; route to the mixed workflow builder without changing queue semantics.
- [ ] **Step 4: Run** `python -m pytest tests/test_api.py -q` and confirm all API tests pass.

### Task 4: Storyboard editor controls

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/app.css`
- Modify: `tests/test_storyboard_ui_features.py`

- [ ] **Step 1: Write failing UI source tests** for the mode selector, continuation checkbox, dynamic reference guidance, payload fields, and disabling continuation on the first row.
- [ ] **Step 2: Run** `python -m pytest tests/test_storyboard_ui_features.py -q` and confirm the controls are missing.
- [ ] **Step 3: Add editor controls** and defaults (`r2va`, continuation off), show reference semantics for each mode, include previous output name on submit, and preserve fields across save/import/copy.
- [ ] **Step 4: Run** `python -m pytest tests/test_storyboard_ui_features.py -q` and confirm all UI feature tests pass.

### Task 5: Documentation and skill update

**Files:**
- Modify: `README.md`
- Modify: `.codex/skills/comfyui-ref2va-tool/SKILL.md`
- Modify: `.codex/skills/comfyui-ref2va-tool/references/storyboard-json.md`

- [ ] **Step 1: Update the JSON specification** with the two new configuration fields, mode-specific reference semantics, continuation ordering, and runtime latent behavior.
- [ ] **Step 2: Update the skill** so future work selects the correct model path, treats latent files as runtime state, and never submits continuation without a valid previous shot.
- [ ] **Step 3: Update the README** with the user workflow and restart requirement for the continuation node pack.
- [ ] **Step 4: Run** the skill creator `quick_validate.py` against `.codex/skills/comfyui-ref2va-tool`.

### Task 6: Full verification

**Files:**
- Test: `tests/`

- [ ] **Step 1: Run** `python -m pytest -q` and require zero failures.
- [ ] **Step 2: Parse both API templates** and assert every referenced node exists and the model chain is FL2VA/R2VA as selected.
- [ ] **Step 3: Query the live ComfyUI node registry** after restart, or import the installed node package directly if restart is deferred, and verify all continuation node classes exist.
- [ ] **Step 4: Confirm** no `/api/submit` request or ComfyUI queue mutation occurred during implementation.
