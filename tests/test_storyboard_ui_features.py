from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")


def test_editor_offers_megapixel_presets_from_0_2_through_1_0():
    for value in range(2, 11):
        assert f'value="{value / 10:.1f}mp"' in INDEX
    assert "快速测试" in INDEX


def test_reference_images_support_double_click_preview():
    assert 'id="image-preview-dialog"' in INDEX
    assert 'id="image-preview-full"' in INDEX
    assert "data-preview-path" in APP
    assert "ondblclick" in APP
    assert "showModal()" in APP
    assert ".image-preview-dialog" in CSS


def test_new_storyboard_button_resets_after_confirmation_and_saves():
    assert 'id="new-storyboard"' in INDEX
    assert "确定新建故事板吗？" in APP
    assert "board={name:'未命名项目',shots:[]}" in APP
    assert "board.shots=[newShot()]" in APP
    assert "await saveBoard()" in APP


def test_toolbar_has_select_all_toggle_and_updates_every_shot():
    assert 'id="toggle-select-all"' in INDEX
    assert "$('toggle-select-all').checked=allSelected" in APP
    assert "board.shots.forEach(s=>{s.selected=selectAll})" in APP


def test_generate_selected_reports_empty_selection_and_awaits_batch():
    assert "没有选中任何分镜" in APP
    assert "$('submit-selected').onclick=async()" in APP
    assert "await submitMany(board.shots.filter(s=>s.selected))" in APP


def test_global_status_is_visible_and_announced():
    assert 'class="global-status"' in INDEX
    assert 'aria-live="polite"' in INDEX
    assert ".global-status" in CSS


def test_editor_offers_r2va_fl2va_and_latent_continuation_controls():
    assert 'class="edit-generation-mode"' in INDEX
    assert 'value="r2va"' in INDEX
    assert 'value="fl2va"' in INDEX
    assert 'class="edit-continuation"' in INDEX
    assert 'class="edit-save-latent"' in INDEX
    assert 'class="reference-guidance"' in INDEX


def test_new_shots_default_to_r2va_without_continuation():
    assert "generation_mode:'r2va'" in APP
    assert "continue_from_previous:false" in APP
    assert "save_latent:false" in APP


def test_global_advanced_acceleration_controls_default_on_and_submit_with_every_shot():
    assert 'id="advanced-settings"' in INDEX
    assert 'id="turbo-lora-enabled"' in INDEX
    assert 'id="sage-attention-enabled"' in INDEX
    assert "turbo_lora_enabled:true" in APP
    assert "sage_attention_enabled:true" in APP
    assert "function normalizeAdvancedSettings" in APP
    assert "function syncAdvancedSettingsUI" in APP
    assert "turbo_lora_enabled:board.advanced_settings.turbo_lora_enabled" in APP
    assert "sage_attention_enabled:board.advanced_settings.sage_attention_enabled" in APP
    assert "board.advanced_settings=normalizeAdvancedSettings" in APP


def test_face_swap_toggle_defaults_off_and_travels_with_every_shot():
    assert 'id="face-swap-enabled"' in INDEX
    assert "face_swap_enabled:false" in APP
    assert "face_swap_enabled:value?.face_swap_enabled===true" in APP
    assert "$('face-swap-enabled').checked=board.advanced_settings.face_swap_enabled" in APP
    assert "face_swap_enabled:board.advanced_settings.face_swap_enabled===true" in APP


def test_remote_comfy_address_is_editable_saved_and_tested_directly():
    assert "function normalizeComfyInput" in APP
    assert "value='http://'+value" in APP
    assert "clearTimeout(saveTimer)" in APP
    assert "await saveBoard();await health(true,value)" in APP
    assert "targetQuery(explicitUrl)" in APP


def test_comfy_terminal_log_panel_refreshes_only_while_open():
    assert 'id="comfy-log-panel"' in INDEX
    assert 'id="comfy-log-output"' in INDEX
    assert "'/api/comfy-logs'" in APP
    assert "if(!$('comfy-log-panel').open)return" in APP
    assert "setInterval(refreshComfyLogs,2000)" in APP
    assert "function cleanLogText" in APP
    assert ".comfy-log-output" in CSS


def test_preview_is_a_persistent_collapsible_resizable_left_sidebar():
    assert 'id="preview-sidebar"' in INDEX
    assert 'id="preview-sidebar-toggle"' in INDEX
    assert 'id="preview-size-toggle"' in INDEX
    assert "function setPreviewSidebarState" in APP
    assert "ref2va.previewCollapsed" in APP
    assert "ref2va.previewEnlarged" in APP
    assert ".preview-sidebar.collapsed" in CSS
    assert ".preview-sidebar.enlarged" in CSS
    assert ".preview-sidebar-head>div:first-child" in CSS
    assert "展开预览 →" in APP
    assert "← 展开队列" in APP


def test_device_and_cloud_ip_controls_live_in_the_top_right_header():
    header = INDEX.split('<header class="app-header">', 1)[1].split("</header>", 1)[0]
    advanced = INDEX.split('<details id="advanced-settings"', 1)[1].split("</details>", 1)[0]
    assert 'id="generation-target"' in header
    assert 'id="comfy-url"' in header
    assert '云端 ComfyUI' in header
    assert '云端 IP' in header
    assert 'id="generation-target"' not in advanced
    assert 'id="comfy-url"' not in advanced
    assert "await saveBoard();await health()" in APP


def test_generation_target_switches_without_being_locked_by_other_device_jobs():
    assert "有任务正在运行，完成或取消后才能切换生成设备" not in APP
    assert "belongsToActiveTarget(s.comfy_url)" in APP
    assert "其他设备上的任务仍会继续追踪和回传" in APP


def test_storyboard_table_omits_prompt_summary_column():
    assert "提示词摘要" not in INDEX
    assert "promptSummary(" not in APP
    assert "td.colSpan=11" in APP


def test_product_name_reflects_the_full_h3_workflow():
    assert "H3 连续镜头工作台" in INDEX
    assert "Ref2VA 表格故事板" not in INDEX
    assert "R2VA · FL2VA · Latent 续镜" in INDEX


def test_browser_validation_accepts_freeform_prompt_text():
    assert "if(!s.prompt.trim())errors.push('提示词不能为空')" in APP
    assert "['subject_definitions:'" not in APP


def test_submit_payload_includes_generation_and_previous_shot_fields():
    assert "generation_mode:s.generation_mode" in APP
    assert "continue_from_previous:s.continue_from_previous" in APP
    assert "previous_output_name:previousOutputName(s)" in APP
    assert "will_be_continued:willBeContinued(s)" in APP
    assert "save_latent:s.save_latent" in APP
    assert "function previousOutputName(s)" in APP
    assert "function willBeContinued(s)" in APP


def test_first_storyboard_row_cannot_enable_continuation():
    assert "continuation.disabled=shotIndex===0" in APP
    assert "if(shotIndex===0)s.continue_from_previous=false" in APP


def test_storyboard_displays_estimated_remaining_time():
    assert "estimated_remaining_seconds" in APP
    assert "formatRemaining" in APP
    assert "剩余" in APP


def test_editor_can_cancel_queued_or_running_generation():
    assert 'class="cancel-shot danger"' in INDEX
    assert "async function cancelShot(s,box=null)" in APP
    assert "'/api/cancel/'+encodeURIComponent(s.prompt_id)" in APP
    assert "s.status='cancelled'" in APP
    assert "cancelled:'已取消'" in APP
    assert "cancelButton.hidden=!['queued','running'].includes(s.status)" in APP


def test_right_sidebar_lists_active_generation_queue():
    assert 'id="queue-sidebar"' in INDEX
    assert 'id="queue-list"' in INDEX
    assert 'id="queue-count"' in INDEX
    assert "function renderQueueSidebar()" in APP
    assert "async function refreshComfyQueue()" in APP
    assert "'/api/queue'" in APP
    assert "data-queue-locate" in APP
    assert "data-prompt-cancel" in APP
    assert ".queue-sidebar" in CSS


def test_select_all_checkbox_lives_in_table_header_and_supports_partial_state():
    header = INDEX[INDEX.index("<thead>") : INDEX.index("</thead>")]
    toolbar = INDEX[INDEX.index('<section id="storyboard-toolbar"') : INDEX.index("</section>", INDEX.index('<section id="storyboard-toolbar"'))]
    assert 'id="toggle-select-all" type="checkbox"' in header
    assert 'id="toggle-select-all"' not in toolbar
    assert ".indeterminate=selectedCount>0&&!allSelected" in APP


def test_device_monitor_shows_api_stats_and_refreshes_periodically():
    assert 'id="device-stats"' in INDEX
    assert 'id="device-disks"' in INDEX
    for name in ("cpu", "gpu", "vram", "ram", "temperature", "fan", "power"):
        assert f'data-stat="{name}"' in INDEX
    assert "async function refreshDeviceStats()" in APP
    assert "function refreshDeviceDisks(disks)" in APP
    assert ".device-disk" in CSS
    assert "refreshDeviceStats()},5000)" in APP


def test_completed_cloud_job_displays_syncing_while_result_downloads():
    assert "syncing:'等待数据回传'" in APP
    assert "s.status='syncing'" in APP
    assert ".status.syncing" in CSS


def test_result_transfer_displays_size_and_speed():
    assert "/api/results/transfer/" in APP
    assert "formatTransferBytes" in APP
    assert "bytes_per_second" in APP
    assert "total_bytes" in APP
    assert "['queued','running','syncing','failed'].includes(x.status)" in APP


def test_remote_loopback_is_migrated_to_cloud_default():
    assert "['http://127.0.0.1:8188','http://localhost:8188'].includes(comfyUrl)" in APP
    assert "comfyUrl='http://192.168.11.103:8188'" in APP


def test_device_metrics_have_health_colors_and_thresholds():
    assert "function metricHealth" in APP
    assert "temperature:[70,83,95]" in APP
    assert ".device-stat.healthy" in CSS
    assert ".device-stat.warning" in CSS
    assert ".device-stat.critical" in CSS


def test_batch_refine_prequeues_all_selected_jobs_for_headless_cloud_execution():
    refine = APP[APP.index("async function refineSelected") : APP.index("/* legacy pixel upscaler")]
    assert "await submitRefine(s,null,true)" in refine
    assert "await waitForRefine(s)" not in refine
    assert "二采任务已按故事板顺序全部进入 ComfyUI 队列" in refine
    assert "button.disabled=true" in refine
    assert "pendingRefineSubmissions=shots.map" in refine
    assert "refineSubmitting" in refine
    assert "请勿重复点击" in refine
    assert "maxAttempts=3" in refine
    assert "attempt<=maxAttempts&&!accepted" in refine
    assert "为保证顺序已停止" in refine
    assert "等待按故事板顺序提交" in refine


def test_queue_sidebar_can_locate_and_cancel_a_shot():
    assert "$('queue-list').onclick" in APP
    assert "scrollIntoView" in APP
    assert "promptCancel" in APP
    assert "'/api/cancel/'" in APP


def test_queue_sidebar_can_cancel_all_jobs_on_current_device():
    assert 'id="queue-cancel-all"' in INDEX
    assert "'/api/queue/cancel-all'" in APP
    assert "已完成的视频不会删除" in APP
    assert ".queue-sidebar.collapsed #queue-cancel-all" in CSS


def test_queue_sidebar_can_collapse_and_remembers_preference():
    assert 'id="queue-toggle"' in INDEX
    assert 'aria-expanded="true"' in INDEX
    assert "function setQueueCollapsed" in APP
    assert "localStorage.getItem('ref2va.queueCollapsed')" in APP
    assert "localStorage.setItem('ref2va.queueCollapsed'" in APP
    assert ".queue-sidebar.collapsed" in CSS


def test_collapsing_queue_expands_main_storyboard_width():
    assert "document.body.classList.toggle('queue-collapsed',collapsed)" in APP
    assert "body.queue-collapsed main" in CSS
