# Resolution Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add selectable 0.2–1.0 megapixel presets so low-resolution storyboard tests can render faster while preserving existing saved resolution values.

**Architecture:** Keep the persisted `resolution` field as a string preset key. Extend the workflow mapping and the existing editor select together; legacy `480p`, `720p`, and `1080p` values remain supported for old storyboards.

**Tech Stack:** FastAPI/Python workflow builder, static HTML/JavaScript, pytest.

---

### Task 1: Define and expose the new presets

**Files:**
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_storyboard_ui_features.py`
- Modify: `app/workflow.py`
- Modify: `app/static/index.html`

- [ ] **Step 1: Write failing workflow and UI tests**

Add assertions that every key from `0.2mp` through `1.0mp` maps to the matching numeric megapixel value, and that the editor exposes those nine values with a fast-test hint on `0.2mp`.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/test_workflow.py tests/test_storyboard_ui_features.py -q`

Expected: FAIL because the new preset keys and HTML options do not exist.

- [ ] **Step 3: Add the minimal preset mapping and options**

Extend `RESOLUTION_MAP` with `0.2mp`–`1.0mp`, and add matching `<option>` entries to `.edit-resolution`. Keep the three existing P-labeled choices for backward compatibility.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/test_workflow.py tests/test_storyboard_ui_features.py -q`

Expected: PASS.

- [ ] **Step 5: Run the complete regression suite**

Run: `python -m pytest -q`

Expected: all tests pass with no failures.
