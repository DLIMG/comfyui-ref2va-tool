from pathlib import Path


APP_JS = Path(__file__).parents[1] / "app" / "static" / "app.js"
INDEX_HTML = Path(__file__).parents[1] / "app" / "static" / "index.html"


def collect_results_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("async function collectResults")
    end = source.index("function validateLocal", start)
    return source[start:end]


def test_repeated_collection_error_does_not_rerender_storyboard():
    function_source = collect_results_source()
    error_branch = function_source.split("catch(e)", 1)[1]

    assert "const message='结果收集：'+e.message" in error_branch
    assert "if(s.error!==message)" in error_branch
    assert "updateEditorMessage(s,message)" in error_branch
    assert "render()" not in error_branch


def test_api_reports_plain_text_server_errors_instead_of_json_parse_errors():
    source = APP_JS.read_text(encoding="utf-8")
    api_source = source[source.index("async function api") : source.index("const jsonOpt")]

    assert "await r.text()" in api_source
    assert "JSON.parse" in api_source
    assert "HTTP ${r.status}" in api_source


def test_polling_recovers_failed_shot_when_prompt_was_actually_accepted():
    source = APP_JS.read_text(encoding="utf-8")
    poll = source[source.index("async function pollStatuses") : source.index("async function openOutput")]

    assert "['queued','running','failed'].includes(x.status)" in poll


def test_result_cards_offer_720p_upscale_and_poll_jobs():
    source = APP_JS.read_text(encoding="utf-8")
    render = source[source.index("function renderResults") : source.index("function formatTime")]

    assert "data-upscale-result" in render
    assert "upscale_resolution" in render
    assert "放大到${target}" in render
    assert "async function submitUpscale" in source
    assert "async function pollUpscales" in source
    assert "/api/results/upscale/collect" in source


def test_global_settings_offer_one_click_upscale_all_results():
    source = APP_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="upscale-all-results"' in html
    assert "一键放大全部" in html
    assert "function pendingUpscaleResults" in source
    assert "async function submitAllUpscales" in source
    assert "$('upscale-all-results').onclick=submitAllUpscales" in source
    assert "item.source_result_id===result.id" in source


def test_index_loads_playlist_before_app_and_has_continuous_preview_controls():
    source = INDEX_HTML.read_text(encoding="utf-8")

    playlist_index = source.index('<script src="/playlist.js"></script>')
    media_index = source.index('<script src="/media-player.js"></script>')
    app_index = source.index('<script src="/app.js"></script>')
    assert playlist_index < media_index < app_index
    for element_id in (
        "continuous-preview",
        "continuous-video",
        "preview-restart",
        "preview-prev",
        "preview-next",
        "preview-status",
        "preview-count",
        "preview-empty",
    ):
        assert f'id="{element_id}"' in source


def test_app_refreshes_continuous_playlist_from_render_and_handles_media_events():
    source = APP_JS.read_text(encoding="utf-8")
    render_source = source[source.index("function render()") : source.index("function makeEditorRow")]

    assert "let continuousItems=[],continuousIndex=0,continuousFailures=new Set();" in source
    assert "Ref2VAPlaylist.buildContinuousPlaylist(board.shots)" in source
    assert "Ref2VAPlaylist.reconcilePlaylistIndex" in source
    assert "refreshContinuousPreview()" in render_source
    assert "video.addEventListener('ended'" in source
    assert "video.addEventListener('error'" in source
    assert "function showContinuousItem(index,autoplay)" in source
    assert "function advanceContinuous(delta,autoplay)" in source


def test_restart_rewinds_even_when_first_item_is_already_loaded():
    source = APP_JS.read_text(encoding="utf-8")

    assert "function restartContinuous()" in source
    restart_source = source[
        source.index("function restartContinuous()") : source.index(
            "function advanceContinuous", source.index("function restartContinuous()")
        )
    ]
    assert "video.currentTime=0" in restart_source
    assert "showContinuousItem(0,true)" in restart_source


def test_error_stop_condition_only_counts_failures_in_current_playlist():
    source = APP_JS.read_text(encoding="utf-8")
    error_source = source[source.index("function handleContinuousError") :]

    assert "continuousItems.every" in error_source


def test_empty_playlist_clears_loaded_item_key_for_future_reappearance():
    source = APP_JS.read_text(encoding="utf-8")
    refresh_source = source[
        source.index("function refreshContinuousPreview") : source.index(
            "function updateContinuousButtons"
        )
    ]

    assert "delete video.dataset.itemKey" in refresh_source


def test_load_error_has_persistent_visible_notice_while_advancing():
    html = INDEX_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")
    error_source = source[source.index("function handleContinuousError") :]

    assert 'id="preview-notice"' in html
    assert "$('preview-notice').textContent=`加载失败：" in error_source
    assert "正在跳到下一段" in error_source


def test_failures_use_composite_shot_and_result_key_consistently():
    source = APP_JS.read_text(encoding="utf-8")
    error_source = source[source.index("function handleContinuousError") :]

    assert "function continuousItemKey(item)" in source
    assert "continuousFailures.add(continuousItemKey" in error_source
    assert "continuousFailures.has(continuousItemKey(item))" in error_source


def test_media_handlers_are_rebound_per_source_and_ignore_stale_events():
    source = APP_JS.read_text(encoding="utf-8")

    assert "function bindContinuousMediaEvents(video,itemKey)" in source
    assert "video.removeEventListener('error'" in source
    assert "video.dataset.itemKey!==itemKey" in source
    assert "Ref2VAMedia.replaceMediaElement(video,key,unbindContinuousMediaEvents,bindContinuousMediaEvents)" in source


def test_successful_media_load_clears_current_failure_and_notice():
    source = APP_JS.read_text(encoding="utf-8")
    binding_source = source[
        source.index("function bindContinuousMediaEvents") : source.index(
            "function showContinuousItem"
        )
    ]

    assert "loadeddata" in binding_source
    assert "continuousFailures.delete(itemKey)" in binding_source
    assert "$('preview-notice').textContent=''" in binding_source


def test_untrusted_status_fallback_is_escaped_in_table_markup():
    source = APP_JS.read_text(encoding="utf-8")

    assert "${esc(statusLabel(s))}" in source


def test_play_rejection_resets_started_state_and_shows_notice():
    source = APP_JS.read_text(encoding="utf-8")
    show_source = source[
        source.index("function showContinuousItem") : source.index(
            "function restartContinuous"
        )
    ]

    assert "continuousPlaybackStarted=false" in show_source
    assert "浏览器阻止自动播放，请点击播放继续" in show_source


def test_continuous_preview_and_storyboard_controls_are_accessible():
    html = INDEX_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="continuous-video" aria-label="连续预览视频"' in html
    assert 'class="select-shot" type="checkbox" aria-label=' in source
    assert 'class="image-drop-zone" tabindex="0" role="button" aria-label=' in html
    assert "drop.onkeydown=" in source
    assert "e.key==='Enter'||e.key===' '" in source


def test_eta_polling_updates_status_cell_without_rebuilding_open_editor():
    source = APP_JS.read_text(encoding="utf-8")
    poll = source[source.index("async function pollStatuses") : source.index("async function openOutput")]

    assert "function refreshStatusCells()" in source
    assert "refreshStatusCells()" in poll
    assert "s.estimated_remaining_seconds=Math.max" in poll
    eta_branch = poll.split("s.estimated_remaining_seconds=Math.max", 1)[1].split("else if", 1)[0]
    assert "changed=true" not in eta_branch


def test_continuous_preview_preloads_and_promotes_the_next_video():
    source = APP_JS.read_text(encoding="utf-8")
    css = (APP_JS.parents[0] / "app.css").read_text(encoding="utf-8")

    assert "let continuousStandby=null" in source
    assert "function preloadNextContinuous()" in source
    assert "Ref2VAMedia.preparePreload" in source
    assert "Ref2VAMedia.promotePreloaded" in source
    assert ".preview-standby" in css


def test_polling_prefers_backend_live_sampling_eta():
    source = APP_JS.read_text(encoding="utf-8")
    poll = source[source.index("async function pollStatuses") : source.index("async function openOutput")]

    assert "d.estimated_remaining_seconds" in poll
    assert "s.eta_source=d.eta_source" in poll
    assert "if(d.error&&s.error!==d.error)" in poll


def test_batch_generation_is_serial_and_cleans_cache_without_unloading_models():
    source = APP_JS.read_text(encoding="utf-8")
    scheduler = source[source.index("async function waitForShot") : source.index("async function pollStatuses")]

    assert "await waitForShot(s)" in scheduler
    assert "submitShot(s,null,true)" in scheduler
    assert "await cleanupBetweenShots(false)" in scheduler
    assert "cleanupBetweenShotsSafely" in scheduler
    assert "缓存清理失败，但不会中断批量生成" in scheduler
    assert "正在提交下一镜" in scheduler
    assert "unload_models:unloadModels" in scheduler
    assert "oom_recovery:oomRecovery" in scheduler
    assert "out of memory" in scheduler
    assert "break" in scheduler
    assert "await preflightBatch(shots)" in scheduler
    assert "previous_in_batch" in scheduler
    assert "完成并保存 Latent 后才会继续下一镜" in scheduler


def test_upscale_and_h3_generation_are_not_cross_submitted():
    source = APP_JS.read_text(encoding="utf-8")

    assert "batchScheduling||hasActiveGeneration()" in source
    assert "await waitForUpscales()" in source
    assert "if(batchScheduling&&!managedByBatch)" in source
