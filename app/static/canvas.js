/* Spatial storyboard view. It deliberately shares the same `board` object as app.js:
   canvas layout is presentation metadata, while the established shot order remains the
   source of truth for queueing and AV-latent continuation. */
(() => {
  const byId = id => document.getElementById(id);
  const canvas = byId('infinite-canvas');
  const workspace = byId('canvas-workspace');
  const table = byId('storyboard-table');
  const nodes = byId('canvas-nodes');
  const links = byId('canvas-links');
  const inspector = byId('canvas-inspector');
  const toggle = byId('canvas-mode-toggle');
  const title = byId('canvas-project-title');
  const zoomReadout = byId('canvas-zoom');
  const state = { scale: 0.92, x: 130, y: 90, panning: null, dragging: null, active: -1, selection: null };
  const CARD_WIDTH = 312;
  const CARD_HEIGHT = 214;
  const ASSET_WIDTH = 174;
  const ASSET_HEIGHT = 136;
  const RESULT_WIDTH = 232;
  const RESULT_HEIGHT = 204;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const defaultPosition = index => ({ x: 120 + (index % 4) * 370, y: 120 + Math.floor(index / 4) * 300 });
  const nodePosition = (shot, index) => {
    const saved = shot.canvas_position;
    return Number.isFinite(saved?.x) && Number.isFinite(saved?.y) ? saved : defaultPosition(index);
  };
  const assetKey = (kind, path) => `${kind}:${path}`;
  const sourceName = path => String(path || '').replace(/^.*[\\/]/, '') || '未命名素材';
  const imageLabel = (shot, index) => {
    if ((shot.generation_mode || 'r2va') === 'r2va') return `<Picture ${index + 1}>`;
    if (shot.continue_from_previous) return index === 0 ? '尾帧' : `Qwen 参考 ${index}`;
    return index === 0 ? '首帧' : index === 1 ? '尾帧' : `Qwen 参考 ${index - 1}`;
  };
  const inputAssets = shot => [
    ...(shot.references || []).map((path, index) => ({ kind: 'image', path, index, label: imageLabel(shot, index) })),
    ...(shot.reference_videos || []).map((path, index) => ({ kind: 'video', path, index, label: `<Video ${index + 1}> + <Audio ${index + 1}>` })),
    ...(shot.reference_audios || []).map((path, index) => ({ kind: 'audio', path, index, label: `<Audio ${(shot.reference_videos || []).length + index + 1}>` })),
  ];
  const assetPosition = (project, shot, shotIndex, asset, assetIndex) => {
    const key = assetKey(asset.kind, asset.path);
    const saved = project.canvas_asset_positions?.[key] || shot.canvas_asset_positions?.[key];
    if (Number.isFinite(saved?.x) && Number.isFinite(saved?.y)) return saved;
    const shotPosition = nodePosition(shot, shotIndex);
    return { x: shotPosition.x - 230, y: shotPosition.y - 40 + assetIndex * 156 };
  };
  function assetGraph(project) {
    const graph = new Map();
    project.shots.forEach((shot, shotIndex) => inputAssets(shot).forEach((asset, assetIndex) => {
      const key = assetKey(asset.kind, asset.path);
      let item = graph.get(key);
      if (!item) {
        item = { key, asset, consumers: [], position: assetPosition(project, shot, shotIndex, asset, assetIndex) };
        graph.set(key, item);
      }
      item.consumers.push({ shot, shotIndex, assetIndex });
    }));
    return [...graph.values()];
  }
  const resultKey = (shot, result) => `result:${shot.id}:${result.id}`;
  const resultPosition = (project, shot, shotIndex, result, resultIndex) => {
    const key = resultKey(shot, result), saved = project.canvas_result_positions?.[key];
    if (Number.isFinite(saved?.x) && Number.isFinite(saved?.y)) return saved;
    const origin = nodePosition(shot, shotIndex);
    return { x: origin.x + 390, y: origin.y + resultIndex * 236 };
  };
  const resultGraph = project => project.shots.flatMap((shot, shotIndex) => (shot.results || []).map((result, resultIndex) => ({ shot, shotIndex, result, resultIndex, key: resultKey(shot, result), position: resultPosition(project, shot, shotIndex, result, resultIndex) })));
  const statusLabel = shot => ({ draft: '待配置', invalid: '验证失败', queued: '排队中', running: '生成中', syncing: '回传中', completed: '已完成', failed: '失败', cancelled: '已取消' }[shot.status] || shot.status || '待配置');
  const applyTransform = () => {
    byId('canvas-scene').style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
    zoomReadout.textContent = `${Math.round(state.scale * 100)}%`;
  };

  function setCanvasMode(enabled, persist = true) {
    document.body.classList.toggle('canvas-mode', enabled);
    workspace.hidden = !enabled;
    table.hidden = enabled;
    toggle.setAttribute('aria-pressed', String(enabled));
    toggle.textContent = enabled ? '↗ 返回表格' : '∞ 无限画布';
    toggle.title = enabled ? '返回表格故事板' : '切换到无限画布编排';
    if (persist) localStorage.setItem('ref2va.canvasMode', enabled ? '1' : '0');
    if (enabled) requestAnimationFrame(() => { applyTransform(); canvas.focus({ preventScroll: true }); });
  }

  function cardMarkup(shot, index, position) {
    const mediaCount = (shot.references?.length || 0) + (shot.reference_videos?.length || 0) + (shot.reference_audios?.length || 0);
    const continuation = shot.continue_from_previous && index > 0 ? '<span class="canvas-card-continuation">继承上一镜 AV Latent</span>' : '';
    return `<article class="canvas-card ${esc(shot.status || 'draft')} ${state.active === index ? 'active' : ''}" data-index="${index}" style="left:${position.x}px;top:${position.y}px">
      <header class="canvas-card-head"><span class="canvas-card-id">${esc(shot.id || `#${index + 1}`)}</span><span class="canvas-card-status ${esc(shot.status || 'draft')}">${esc(statusLabel(shot))}</span></header>
      <div class="canvas-card-body"><div class="canvas-generate-glyph">▶</div><div class="canvas-card-copy"><b title="${esc(shot.title)}">${esc(shot.title || '未命名片段')}</b><small>${esc((shot.generation_mode || 'r2va').toUpperCase())} · ${esc(shot.duration || 0)} 秒 · ${esc(shot.aspect_ratio || '16:9')}${shot.shot_card_needs_sync ? ' · 英文待同步' : ''}</small><p>${esc(shot.shot_card_zh || '尚未填写中文镜头卡')}</p></div></div>
      <footer><span>素材 ${mediaCount} · 结果 ${(shot.results || []).length}</span>${continuation}<div class="canvas-card-actions"><button type="button" data-action="select">${shot.selected ? '已选中' : '选择'}</button><button type="button" data-action="edit">编辑</button><button type="button" data-action="generate" class="primary">生成</button></div></footer>
    </article>`;
  }

  function assetMarkup(item) {
    const { asset, key, position, consumers } = item;
    const encodedKey = encodeURIComponent(assetKey(asset.kind, asset.path));
    const preview = asset.kind === 'image'
      ? `<img alt="${esc(asset.label)}" src="/api/file-preview?path=${encodeURIComponent(asset.path)}">`
      : `<div class="canvas-asset-icon ${asset.kind}">${asset.kind === 'video' ? '▸' : '♪'}</div>`;
    const kindText = asset.kind === 'image' ? '图片参考' : asset.kind === 'video' ? '视频参考' : '音频参考';
    const selected = state.selection?.type === 'asset' && state.selection.key === key ? ' active' : '';
    return `<article class="canvas-asset ${asset.kind}${selected}" data-shot-index="${consumers[0].shotIndex}" data-asset-key="${encodedKey}" style="left:${position.x}px;top:${position.y}px">
      <div class="canvas-asset-preview">${preview}</div><div class="canvas-asset-copy"><span>${esc(kindText)} · 供 ${consumers.length} 镜使用</span><b title="${esc(sourceName(asset.path))}">${esc(asset.label)}</b><small title="${esc(asset.path)}">${esc(sourceName(asset.path))}</small></div><button type="button" data-action="edit-source">编辑</button>
    </article>`;
  }

  function resultMarkup(item) {
    const { shot, shotIndex, result, position } = item;
    const videoUrl = `/api/results/video/${encodeURIComponent(shot.id)}/${encodeURIComponent(result.id)}`;
    const selected = state.selection?.type === 'result' && state.selection.resultId === result.id && state.selection.shotIndex === shotIndex ? ' active' : '';
    return `<article class="canvas-result${selected}" data-shot-index="${shotIndex}" data-result-id="${esc(result.id)}" data-result-key="${encodeURIComponent(item.key)}" style="left:${position.x}px;top:${position.y}px">
      <header><span>生成结果</span><small>${esc(result.resolution || shot.resolution || '视频')}</small></header><div class="canvas-result-video-slot" data-video-url="${videoUrl}"></div><b title="${esc(result.filename || '')}">${esc(result.filename || '生成视频')}</b><small>${esc(formatTime(result.created_at))}</small><button type="button" data-action="inspect-result">查看</button>
    </article>`;
  }

  function detachResultVideos() {
    const reusable = new Map();
    nodes.querySelectorAll('.canvas-result').forEach(card => {
      const video = card.querySelector('video');
      if (!video) return;
      video.remove();
      reusable.set(decodeURIComponent(card.dataset.resultKey), video);
    });
    return reusable;
  }

  function attachResultVideos(results, reusable) {
    const retained = new Set();
    results.forEach(item => {
      const card = [...nodes.querySelectorAll('.canvas-result')].find(node => node.dataset.resultKey === encodeURIComponent(item.key));
      const slot = card?.querySelector('.canvas-result-video-slot');
      if (!slot) return;
      let video = reusable.get(item.key);
      if (!video) {
        video = document.createElement('video');
        video.controls = true;
        video.preload = 'metadata';
        video.src = slot.dataset.videoUrl;
      }
      video.className = 'canvas-result-video';
      slot.replaceWith(video);
      retained.add(item.key);
    });
    reusable.forEach((video, key) => { if (!retained.has(key)) { video.pause(); video.removeAttribute('src'); video.load(); } });
  }

  function renderInspector(currentBoard) {
    const selection = state.selection;
    if (!selection) { inspector.hidden = true; inspector.innerHTML = ''; return; }
    const shot = currentBoard.shots[selection.shotIndex];
    if (!shot) { state.selection = null; inspector.hidden = true; return; }
    inspector.hidden = false;
    if (selection.type === 'asset') {
      const item = assetGraph(currentBoard).find(asset => asset.key === selection.key);
      if (!item) { state.selection = null; renderInspector(currentBoard); return; }
      const preview = item.asset.kind === 'image' ? `<img src="/api/file-preview?path=${encodeURIComponent(item.asset.path)}" alt="${esc(item.asset.label)}">` : `<div class="canvas-inspector-media-icon ${item.asset.kind}">${item.asset.kind === 'video' ? '▸' : '♪'}</div>`;
      inspector.innerHTML = `<header><div><span>素材节点</span><h2>${esc(sourceName(item.asset.path))}</h2></div><button type="button" data-inspector-action="close" aria-label="关闭节点详情">×</button></header><div class="canvas-inspector-source">${preview}<p><b>${esc(item.asset.label)}</b><small>${esc(item.asset.path)}</small></p></div><p class="canvas-inspector-note">此素材已通过连线输入到 ${item.consumers.length} 个镜头。</p><div class="canvas-inspector-consumers">${item.consumers.map(consumer => `<button type="button" data-inspector-action="jump-shot" data-shot-index="${consumer.shotIndex}">${esc(currentBoard.shots[consumer.shotIndex].id)} · ${esc(currentBoard.shots[consumer.shotIndex].title || '未命名片段')}</button>`).join('')}</div><footer><button type="button" data-inspector-action="full-edit" data-shot-index="${selection.shotIndex}">在完整编辑器管理素材</button></footer>`;
      return;
    }
    if (selection.type === 'result') {
      const result = (shot.results || []).find(item => item.id === selection.resultId);
      if (!result) { state.selection = null; renderInspector(currentBoard); return; }
      const videoUrl = `/api/results/video/${encodeURIComponent(shot.id)}/${encodeURIComponent(result.id)}`;
      inspector.innerHTML = `<header><div><span>结果节点 · ${esc(shot.id)}</span><h2>${esc(result.filename || '生成视频')}</h2></div><button type="button" data-inspector-action="close" aria-label="关闭节点详情">×</button></header><video class="canvas-inspector-video" controls preload="metadata" src="${videoUrl}"></video><p class="canvas-inspector-note">${esc(formatTime(result.created_at))} · ${esc(result.resolution || shot.resolution || '未知清晰度')}</p><footer><button type="button" data-inspector-action="open-result" data-result-id="${esc(result.id)}">打开目录</button><button type="button" class="danger" data-inspector-action="delete-result" data-result-id="${esc(result.id)}">删除结果</button></footer>`;
      return;
    }
    const isFirst = selection.shotIndex === 0, nextNeedsLatent = Boolean(currentBoard.shots[selection.shotIndex + 1]?.continue_from_previous);
    const resultList = (shot.results || []).length ? `<div class="canvas-inspector-result-list">${shot.results.map(result => `<button type="button" data-inspector-action="inspect-result" data-result-id="${esc(result.id)}">▸ ${esc(result.filename || '生成视频')}<small>${esc(result.resolution || shot.resolution || '')}</small></button>`).join('')}</div>` : '<p class="canvas-inspector-empty">生成完成后，结果会作为独立视频节点出现在画布右侧。</p>';
    inspector.innerHTML = `<header><div><span>生成节点 · ${esc(shot.id)}</span><h2>${esc(shot.title || '未命名片段')}</h2></div><button type="button" data-inspector-action="close" aria-label="关闭节点详情">×</button></header><div class="canvas-inspector-settings"><label>标题<input data-shot-field="title" value="${esc(shot.title)}"></label><label>模式<select data-shot-field="generation_mode"><option value="r2va" ${shot.generation_mode === 'r2va' ? 'selected' : ''}>R2VA 多参考</option><option value="fl2va" ${shot.generation_mode === 'fl2va' ? 'selected' : ''}>FL2VA 首尾帧</option></select></label><label>清晰度<select data-shot-field="resolution"><option value="0.2mp" ${shot.resolution === '0.2mp' ? 'selected' : ''}>0.2 MP</option><option value="0.3mp" ${shot.resolution === '0.3mp' ? 'selected' : ''}>0.3 MP</option><option value="0.4mp" ${shot.resolution === '0.4mp' ? 'selected' : ''}>0.4 MP</option><option value="0.5mp" ${shot.resolution === '0.5mp' ? 'selected' : ''}>0.5 MP</option><option value="0.6mp" ${shot.resolution === '0.6mp' ? 'selected' : ''}>0.6 MP</option><option value="0.7mp" ${shot.resolution === '0.7mp' ? 'selected' : ''}>0.7 MP</option><option value="0.8mp" ${shot.resolution === '0.8mp' ? 'selected' : ''}>0.8 MP</option><option value="0.9mp" ${shot.resolution === '0.9mp' ? 'selected' : ''}>0.9 MP</option><option value="1.0mp" ${shot.resolution === '1.0mp' ? 'selected' : ''}>1.0 MP</option></select></label><label>画幅<select data-shot-field="aspect_ratio"><option value="16:9" ${shot.aspect_ratio === '16:9' ? 'selected' : ''}>16:9</option><option value="9:16" ${shot.aspect_ratio === '9:16' ? 'selected' : ''}>9:16</option><option value="4:3" ${shot.aspect_ratio === '4:3' ? 'selected' : ''}>4:3</option><option value="3:4" ${shot.aspect_ratio === '3:4' ? 'selected' : ''}>3:4</option><option value="1:1" ${shot.aspect_ratio === '1:1' ? 'selected' : ''}>1:1</option></select></label><label>时长<input data-shot-field="duration" type="number" min="1" step="1" value="${esc(shot.duration)}"></label><label>种子<input data-shot-field="seed" type="number" step="1" value="${esc(shot.seed)}"></label><label class="canvas-inspector-check"><input data-shot-field="continue_from_previous" type="checkbox" ${shot.continue_from_previous ? 'checked' : ''} ${isFirst ? 'disabled' : ''}>延续上一镜 AV Latent</label><label class="canvas-inspector-check"><input data-shot-field="save_latent" type="checkbox" ${(shot.save_latent || nextNeedsLatent) ? 'checked' : ''} ${nextNeedsLatent ? 'disabled' : ''}>保存 AV Latent${nextNeedsLatent ? '（下一镜需要）' : ''}</label></div><label class="canvas-inspector-prompt">视频提示词<textarea data-shot-field="prompt" rows="9">${esc(shot.prompt)}</textarea></label><p class="canvas-inspector-note">输入素材：${(shot.references || []).length} 图 · ${(shot.reference_videos || []).length} 视频 · ${(shot.reference_audios || []).length} 音频；生成结果：${(shot.results || []).length} 个。</p>${resultList}<footer><button type="button" data-inspector-action="full-edit" data-shot-index="${selection.shotIndex}">完整编辑</button><button type="button" data-inspector-action="generate" class="primary">生成此镜</button></footer>`;
    inspector.querySelector('.canvas-inspector-prompt').insertAdjacentHTML('beforebegin', `<label class="canvas-inspector-prompt canvas-inspector-shot-card">中文镜头卡<textarea data-shot-field="shot_card_zh" rows="7" placeholder="画面与景别、人物动作、镜头运动、对白与声音、本次修改、保持不变">${esc(shot.shot_card_zh || '')}</textarea></label><p class="canvas-inspector-note shot-card-sync-status ${shot.shot_card_needs_sync ? 'needs-sync' : ''}">${shot.shot_card_needs_sync ? '英文 H3 待同步，暂不能生成此镜。' : '生成时使用下方英文 H3 提示词。'}</p><button type="button" data-inspector-action="mark-card-synced" ${!shot.shot_card_needs_sync || !shot.prompt ? 'disabled' : ''}>确认英文 H3 已同步</button>`);
  }

  function render(currentBoard) {
    if (!currentBoard || !nodes) return;
    title.textContent = currentBoard.name || '未命名项目';
    const reusableVideos = detachResultVideos();
    const assets = assetGraph(currentBoard);
    const results = resultGraph(currentBoard);
    nodes.innerHTML = assets.map(assetMarkup).join('') + currentBoard.shots.map((shot, index) => cardMarkup(shot, index, nodePosition(shot, index))).join('') + results.map(resultMarkup).join('');
    const selectedShot = state.selection?.type === 'shot' ? state.selection.shotIndex : -1;
    const inputPaths = assets.flatMap(item => item.consumers.map(consumer => {
      const to = nodePosition(consumer.shot, consumer.shotIndex), from = item.position;
      const startX = from.x + ASSET_WIDTH, startY = from.y + ASSET_HEIGHT / 2;
      const endX = to.x, endY = to.y + 82 + Math.min(consumer.assetIndex, 3) * 20;
      const delta = Math.max(58, Math.abs(endX - startX) * 0.42);
      const active = (state.selection?.type === 'asset' && state.selection.key === item.key) || selectedShot === consumer.shotIndex ? ' active' : '';
      return `<path class="canvas-link asset ${item.asset.kind}${active}" d="M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}"></path>`;
    })).join('');
    const sequencePaths = currentBoard.shots.slice(1).map((shot, index) => {
      const from = nodePosition(currentBoard.shots[index], index);
      const to = nodePosition(shot, index + 1);
      const startX = from.x + CARD_WIDTH, startY = from.y + 107;
      const endX = to.x, endY = to.y + 107;
      const delta = Math.max(80, Math.abs(endX - startX) * 0.42);
      const inherited = shot.continue_from_previous ? ' latent' : '';
      const active = selectedShot === index || selectedShot === index + 1 ? ' active' : '';
      return `<path class="canvas-link sequence${inherited}${active}" d="M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}"></path>`;
    }).join('');
    const resultPaths = results.map(item => {
      const from = nodePosition(item.shot, item.shotIndex), to = item.position;
      const startX = from.x + CARD_WIDTH, startY = from.y + 135;
      const endX = to.x, endY = to.y + 46;
      const delta = Math.max(62, Math.abs(endX - startX) * 0.38);
      const active = selectedShot === item.shotIndex || (state.selection?.type === 'result' && state.selection.resultId === item.result.id && state.selection.shotIndex === item.shotIndex) ? ' active' : '';
      return `<path class="canvas-link result${active}" d="M ${startX} ${startY} C ${startX + delta} ${startY}, ${endX - delta} ${endY}, ${endX} ${endY}"></path>`;
    }).join('');
    links.setAttribute('viewBox', '0 0 3200 2200');
    links.innerHTML = inputPaths + sequencePaths + resultPaths;
    attachResultVideos(results, reusableVideos);
    renderInspector(currentBoard);
    applyTransform();
  }

  function openEditor(index) {
    state.active = index;
    setCanvasMode(false);
    expanded = index;
    render(board);
    requestAnimationFrame(() => document.querySelector(`#storyboard-body .shot-row[data-i="${index}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  }

  function addShot() {
    const shot = newShot();
    const index = board.shots.length;
    const last = board.shots[index - 1];
    const previous = last ? nodePosition(last, index - 1) : { x: -250, y: 120 };
    shot.canvas_position = { x: previous.x + 370, y: previous.y };
    board.shots.push(shot);
    state.active = index;
    scheduleSave();
    render(board);
  }

  function sortByCanvasPosition() {
    const before = board.shots.map(shot => shot.id).join('|');
    const positions = new Map(board.shots.map((shot, index) => [shot, nodePosition(shot, index)]));
    board.shots.sort((a, b) => {
      const aPos = positions.get(a);
      const bPos = positions.get(b);
      return aPos.x - bPos.x || aPos.y - bPos.y;
    });
    if (before !== board.shots.map(shot => shot.id).join('|')) {
      expanded = -1;
      board.shots.forEach((shot, index) => { if (index === 0) shot.continue_from_previous = false; });
      scheduleSave();
      render(board);
      byId('global-status').textContent = '已按节点从左到右的顺序重排故事板；生成和续镜会遵循新顺序。';
    } else byId('global-status').textContent = '画布顺序未变化。';
  }

  function fitCanvas() {
    const positions = [
      ...board.shots.map(nodePosition),
      ...assetGraph(board).map(item => item.position),
      ...resultGraph(board).map(item => item.position),
    ];
    if (!positions.length) { state.scale = 1; state.x = 100; state.y = 80; applyTransform(); return; }
    const left = Math.min(...positions.map(p => p.x));
    const top = Math.min(...positions.map(p => p.y));
    const right = Math.max(...positions.map(p => p.x + CARD_WIDTH));
    const bottom = Math.max(...positions.map(p => p.y + CARD_HEIGHT));
    const availableWidth = Math.max(300, canvas.clientWidth - 120);
    const availableHeight = Math.max(240, canvas.clientHeight - 140);
    state.scale = clamp(Math.min(1, availableWidth / (right - left), availableHeight / (bottom - top)), 0.45, 1);
    state.x = (canvas.clientWidth - (right - left) * state.scale) / 2 - left * state.scale;
    state.y = Math.max(60, (canvas.clientHeight - (bottom - top) * state.scale) / 2 - top * state.scale);
    applyTransform();
  }

  toggle.addEventListener('click', () => setCanvasMode(!document.body.classList.contains('canvas-mode')));
  byId('canvas-add-shot').addEventListener('click', addShot);
  byId('canvas-sort-shots').addEventListener('click', sortByCanvasPosition);
  byId('canvas-fit').addEventListener('click', fitCanvas);
  byId('canvas-zoom-in').addEventListener('click', () => { state.scale = clamp(state.scale + 0.1, 0.4, 1.6); applyTransform(); });
  byId('canvas-zoom-out').addEventListener('click', () => { state.scale = clamp(state.scale - 0.1, 0.4, 1.6); applyTransform(); });
  byId('project-name').addEventListener('input', event => { title.textContent = event.target.value.trim() || '未命名项目'; });

  function updateSelectedShot(event) {
    const field = event.target.dataset.shotField, selection = state.selection;
    if (!field || selection?.type !== 'shot') return;
    const shot = board.shots[selection.shotIndex];
    const checked = event.target.type === 'checkbox';
    shot[field] = checked ? event.target.checked : ['duration', 'seed'].includes(field) ? Number(event.target.value) : event.target.value;
    if (field === 'shot_card_zh') {
      shot.shot_card_needs_sync = Boolean(shot.shot_card_zh);
      const notice = inspector.querySelector('.shot-card-sync-status');
      notice.textContent = shot.shot_card_needs_sync ? '英文 H3 待同步，暂不能生成此镜。' : '生成时使用下方英文 H3 提示词。';
      notice.classList.toggle('needs-sync', shot.shot_card_needs_sync);
      inspector.querySelector('[data-inspector-action="mark-card-synced"]').disabled = !shot.shot_card_needs_sync || !shot.prompt;
    }
    if (field === 'continue_from_previous' && selection.shotIndex === 0) shot.continue_from_previous = false;
    if (field === 'continue_from_previous' && shot.continue_from_previous) board.shots[selection.shotIndex - 1].save_latent = true;
    if (field === 'save_latent' && board.shots[selection.shotIndex + 1]?.continue_from_previous) shot.save_latent = true;
    shot.status = 'draft';
    scheduleSave();
    if (event.type === 'change' && field !== 'title' && field !== 'prompt' && field !== 'shot_card_zh') render(board);
  }
  inspector.addEventListener('input', updateSelectedShot);
  inspector.addEventListener('change', updateSelectedShot);
  inspector.addEventListener('click', async event => {
    const action = event.target.closest('[data-inspector-action]')?.dataset.inspectorAction;
    if (!action) return;
    const selection = state.selection, shot = board.shots[selection?.shotIndex];
    if (action === 'close') { state.selection = null; state.active = -1; render(board); return; }
    if (action === 'jump-shot') { const index = Number(event.target.closest('button').dataset.shotIndex); state.active = index; state.selection = { type: 'shot', shotIndex: index }; render(board); return; }
    if (action === 'full-edit') { openEditor(Number(event.target.closest('button').dataset.shotIndex)); return; }
    if (action === 'mark-card-synced') { shot.shot_card_needs_sync = false; scheduleSave(); render(board); return; }
    if (action === 'inspect-result') { state.selection = { type: 'result', shotIndex: selection.shotIndex, resultId: event.target.closest('button').dataset.resultId }; render(board); return; }
    if (action === 'generate') { try { await submitShot(shot); byId('global-status').textContent = `${shot.id} 已进入生成队列。`; } catch (error) { byId('global-status').textContent = `${shot.id} 提交失败：${error.message}`; } return; }
    const result = (shot.results || []).find(item => item.id === event.target.closest('button').dataset.resultId);
    if (!result) return;
    if (action === 'open-result') { await api('/api/open-path', jsonOpt('POST', { path: result.path })); return; }
    if (action === 'delete-result' && confirm(`确定永久删除“${result.filename || '这个视频'}”吗？此操作无法恢复。`)) { const data = await api(`/api/results/${encodeURIComponent(shot.id)}/${encodeURIComponent(result.id)}`, { method: 'DELETE' }); shot.results = data.results; shot.prompt_id = data.prompt_id || ''; state.selection = null; render(board); await saveBoard(); }
  });

  nodes.addEventListener('click', async event => {
    if (event.target.closest('video')) return;
    const card = event.target.closest('.canvas-card');
    const asset = event.target.closest('.canvas-asset');
    const resultNode = event.target.closest('.canvas-result');
    if (!card && !asset && !resultNode) return;
    const index = Number(card?.dataset.index ?? asset?.dataset.shotIndex ?? resultNode.dataset.shotIndex);
    const shot = board.shots[index];
    const action = event.target.closest('button')?.dataset.action;
    if (resultNode) { state.active = index; state.selection = { type: 'result', shotIndex: index, resultId: resultNode.dataset.resultId }; render(board); return; }
    if (asset) { if (action === 'edit-source') openEditor(index); else { state.active = index; state.selection = { type: 'asset', shotIndex: index, key: decodeURIComponent(asset.dataset.assetKey) }; render(board); } return; }
    if (!action) { state.active = index; state.selection = { type: 'shot', shotIndex: index }; render(board); return; }
    if (action === 'select') { shot.selected = !shot.selected; state.active = index; state.selection = { type: 'shot', shotIndex: index }; scheduleSave(); render(board); }
    if (action === 'edit') openEditor(index);
    if (action === 'generate') {
      state.active = index; state.selection = { type: 'shot', shotIndex: index };
      byId('global-status').textContent = `正在提交 ${shot.id}…`;
      try { await submitShot(shot); byId('global-status').textContent = `${shot.id} 已进入生成队列。`; }
      catch (error) { byId('global-status').textContent = `${shot.id} 提交失败：${error.message}`; }
    }
  });

  nodes.addEventListener('pointerdown', event => {
    if (event.target.closest('button,video')) return;
    const card = event.target.closest('.canvas-card');
    const asset = event.target.closest('.canvas-asset');
    const resultNode = event.target.closest('.canvas-result');
    if (!card && !asset && !resultNode) return;
    const index = Number(card?.dataset.index ?? asset?.dataset.shotIndex ?? resultNode.dataset.shotIndex);
    const key = asset ? decodeURIComponent(asset.dataset.assetKey) : '';
    const resultId = resultNode?.dataset.resultId || '';
    const position = asset ? assetGraph(board).find(item => item.key === key)?.position : resultNode ? resultGraph(board).find(item => item.shotIndex === index && item.result.id === resultId)?.position : nodePosition(board.shots[index], index);
    if (!position) return;
    state.active = index;
    state.dragging = { type: asset ? 'asset' : resultNode ? 'result' : 'shot', index, key, resultId, startX: event.clientX, startY: event.clientY, x: position.x, y: position.y, pointerId: event.pointerId };
    (card || asset || resultNode).setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  canvas.addEventListener('pointerdown', event => {
    if (event.target.closest('.canvas-card,.canvas-asset,.canvas-result')) return;
    state.panning = { startX: event.clientX, startY: event.clientY, x: state.x, y: state.y, pointerId: event.pointerId };
    canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  window.addEventListener('pointermove', event => {
    if (state.dragging && event.pointerId === state.dragging.pointerId) {
      const drag = state.dragging;
      const shot = board.shots[drag.index];
      const position = { x: Math.round(drag.x + (event.clientX - drag.startX) / state.scale), y: Math.round(drag.y + (event.clientY - drag.startY) / state.scale) };
      if (drag.type === 'asset') { board.canvas_asset_positions ||= {}; board.canvas_asset_positions[drag.key] = position; }
      else if (drag.type === 'result') { board.canvas_result_positions ||= {}; board.canvas_result_positions[resultKey(shot, { id: drag.resultId })] = position; }
      else shot.canvas_position = position;
      render(board);
    }
    if (state.panning && event.pointerId === state.panning.pointerId) {
      state.x = state.panning.x + event.clientX - state.panning.startX;
      state.y = state.panning.y + event.clientY - state.panning.startY;
      applyTransform();
    }
  });
  window.addEventListener('pointerup', event => {
    if (state.dragging?.pointerId === event.pointerId) { state.dragging = null; scheduleSave(); }
    if (state.panning?.pointerId === event.pointerId) state.panning = null;
  });
  canvas.addEventListener('wheel', event => {
    event.preventDefault();
    const oldScale = state.scale;
    const nextScale = clamp(oldScale + (event.deltaY < 0 ? 0.08 : -0.08), 0.4, 1.6);
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left, mouseY = event.clientY - rect.top;
    state.x = mouseX - (mouseX - state.x) * (nextScale / oldScale);
    state.y = mouseY - (mouseY - state.y) * (nextScale / oldScale);
    state.scale = nextScale;
    applyTransform();
  }, { passive: false });
  canvas.addEventListener('keydown', event => { if (event.key === 'Escape') setCanvasMode(false); });

  window.Ref2VACanvas = { render, setCanvasMode };
  setCanvasMode(localStorage.getItem('ref2va.canvasMode') === '1', false);
  render(board);
})();
