const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let board={name:'未命名项目',advanced_settings:{turbo_lora_enabled:true,sage_attention_enabled:true,face_swap_enabled:false,sampling_steps:8,resolution:'0.4mp',refine_target_resolution:'0.9mp',generation_target:'local',comfy_url:'http://192.168.11.103:8188'},shared:{enabled:false,prompt:'',references:[],reference_videos:[],reference_audios:[]},shots:[]},expanded=-1,saveTimer=null,polling=false,comfyQueue=[],pendingRefineSubmissions=[],refineSubmitting=false;
let continuousItems=[],continuousIndex=0,continuousFailures=new Set();
let continuousPlaybackStarted=false;
let continuousMediaHandlers=null;
let continuousStandby=null;
const collecting=new Set();
let comfyLogTimer=null,comfyLogClearedAt=0;
const statusText={draft:'待配置',invalid:'验证失败',queued:'排队中',running:'生成中',syncing:'等待数据回传',completed:'已完成',failed:'失败',cancelled:'已取消'};
const aspectText={'16:9':'16:9 横屏','9:16':'9:16 竖屏','4:3':'4:3 横屏','3:4':'3:4 竖屏','1:1':'1:1 方形'};
const directorChoices={shot_type:['wide','medium','medium_close','close_up','extreme_close_up','over_shoulder','pov'],camera_motion:['static','push_in_slow','pull_out_slow','pan','truck','tracking','arc','handheld'],audio_cue:['ambient','dialogue','action_sync','music','silent'],continuity:['preserve','latent','keyframe']};
function normalizeDirector(value){const director=value||{},pick=(field,fallback)=>directorChoices[field].includes(director[field])?director[field]:fallback;return{enabled:director.enabled===true,shot_type:pick('shot_type','medium'),camera_motion:pick('camera_motion','static'),audio_cue:pick('audio_cue','ambient'),continuity:pick('continuity','preserve')}}
function normalizeShared(value){const shared=value||{},paths=field=>Array.isArray(shared[field])?[...new Set(shared[field].filter(Boolean).map(String))]:[];return{enabled:shared.enabled===true,prompt:String(shared.prompt||''),references:paths('references').slice(0,9),reference_videos:paths('reference_videos').slice(0,3),reference_audios:paths('reference_audios').slice(0,3)}}
function resolvedShot(s){const shared=normalizeShared(board.shared),useShared=shared.enabled;const images=useShared?(s.generation_mode==='fl2va'?[...(s.references||[]).slice(0,2),...shared.references,...(s.references||[]).slice(2)]:[...shared.references,...(s.references||[])]):[...(s.references||[])];return{references:images,reference_videos:useShared?[...shared.reference_videos,...(s.reference_videos||[])]:[...(s.reference_videos||[])],reference_audios:useShared?[...shared.reference_audios,...(s.reference_audios||[])]:[...(s.reference_audios||[])],prompt:useShared?[shared.prompt,s.prompt].filter(Boolean).join('\n\n'):s.prompt}}

function normalizeAdvancedSettings(value){const steps=Number.parseInt(value?.sampling_steps,10),legacy=value?.refine_target_resolution==='720p'?'0.9mp':value?.refine_target_resolution==='1080p'?'1.0mp':value?.refine_target_resolution,target=['0.4mp','0.5mp','0.6mp','0.7mp','0.8mp','0.9mp','1.0mp'].includes(legacy)?legacy:'0.9mp',generationTarget=value?.generation_target==='remote'?'remote':'local';let comfyUrl=String(value?.comfy_url||'http://192.168.11.103:8188').replace(/\/$/,'');if(generationTarget==='remote'&&['http://127.0.0.1:8188','http://localhost:8188'].includes(comfyUrl))comfyUrl='http://192.168.11.103:8188';return{turbo_lora_enabled:value?.turbo_lora_enabled!==false,sage_attention_enabled:value?.sage_attention_enabled!==false,face_swap_enabled:value?.face_swap_enabled===true,sampling_steps:Number.isInteger(steps)&&steps>=1&&steps<=100?steps:8,resolution:value?.resolution||'0.4mp',refine_target_resolution:target,generation_target:generationTarget,comfy_url:comfyUrl}}
function normalizeComfyInput(value){value=String(value||'').trim().replace(/\/+$/,'');if(value&&!/^[a-z][a-z\d+.-]*:\/\//i.test(value))value='http://'+value;const parsed=new URL(value);if(!['http:','https:'].includes(parsed.protocol)||!parsed.hostname||parsed.username||parsed.password)throw new Error('invalid comfy url');return parsed.origin}
function syncAdvancedSettingsUI(){board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);$('turbo-lora-enabled').checked=board.advanced_settings.turbo_lora_enabled;$('sage-attention-enabled').checked=board.advanced_settings.sage_attention_enabled;$('face-swap-enabled').checked=board.advanced_settings.face_swap_enabled;$('sampling-steps').value=board.advanced_settings.sampling_steps;$('global-resolution').value=board.advanced_settings.resolution;$('refine-target-resolution').value=board.advanced_settings.refine_target_resolution;$('generation-target').value=board.advanced_settings.generation_target;$('comfy-url').value=board.advanced_settings.comfy_url;$('remote-comfy-row').hidden=board.advanced_settings.generation_target!=='remote'}
const targetQuery=value=>value?'?comfy_url='+encodeURIComponent(value):'';

function newShot(copy=null){
  const n=board.shots.length+1,id=String(n).padStart(2,'0')+'A';
  const base=copy?JSON.parse(JSON.stringify(copy)):{references:[],reference_videos:[],reference_audios:[],prompt:'',shot_card_zh:'',shot_card_needs_sync:false,director:normalizeDirector(),duration:6,seed:Date.now()%2147483647,resolution:board.advanced_settings.resolution||'0.4mp',aspect_ratio:'16:9',generation_mode:'r2va',reference_image_size:'match',continue_from_previous:false,save_latent:false,audio_tail_carryover:'No Audio Carryover',audio_feather_ticks:0,results:[]};
  return{...base,id,title:copy?copy.title+' 副本':'新片段',output_name:id+'_新片段',selected:false,status:'draft',prompt_id:'',run_dir:'',error:'',results:copy?[]:(base.results||[])};
}
async function api(url,opt={}){const r=await fetch(url,opt),text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch{d={detail:text}}if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);return d}
const jsonOpt=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
async function loadBoard(){
  board=await api('/api/storyboard');
  board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);
  board.shared=normalizeShared(board.shared);
  if(!board.shots.length)board.shots.push(newShot());
  board.shots=board.shots.map(s=>({...newShot(),...s,references:[...(s.references||[])],reference_videos:[...(s.reference_videos||[])],reference_audios:[...(s.reference_audios||[])],results:[...(s.results||[])],director:normalizeDirector(s.director),resolution:s.resolution||'480p',aspect_ratio:s.aspect_ratio||'16:9',generation_mode:s.generation_mode||'r2va',reference_image_size:s.reference_image_size==='max'?'max':'match',continue_from_previous:Boolean(s.continue_from_previous),save_latent:Boolean(s.save_latent),audio_tail_carryover:s.audio_tail_carryover||'No Audio Carryover',audio_feather_ticks:Number.isInteger(s.audio_feather_ticks)?s.audio_feather_ticks:0}));
  $('project-name').value=board.name;syncAdvancedSettingsUI();render();pollStatuses();syncSourceUI();
}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(saveBoard,500)}
const PATH_SEP=new RegExp('['+String.fromCharCode(92)+'/]');
function baseName(value){const parts=String(value||'').split(PATH_SEP);return parts[parts.length-1]||''}
function syncSourceUI(){const path=String(board.source_json_path||''),open=$('import-json');if(!open)return;open.title=path?'当前文件：'+path+'（修改会自动保存到该文件；点击打开其他 JSON）':'打开 JSON 文件，后续修改会自动保存到该文件'}
async function saveBoard(){board.name=$('project-name').value.trim()||'未命名项目';board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);const saved=await api('/api/storyboard',jsonOpt('PUT',board)),source=baseName(board.source_json_path);$('global-status').textContent='已自动保存 '+new Date().toLocaleTimeString()+(source?(saved.mirror_error?' · 源文件回写失败：'+saved.mirror_error:' · 已同步 '+source):'')}
function formatRemaining(seconds){if(!Number.isFinite(seconds))return'';seconds=Math.max(0,Math.ceil(seconds));const m=Math.floor(seconds/60),s=seconds%60;return m?`${m}分${String(s).padStart(2,'0')}秒`:`${s}秒`}
function formatGiB(value){return Number.isFinite(Number(value))?(Number(value)/1073741824).toFixed(1)+'G':'—'}
function formatTransferBytes(value){const n=Number(value);if(!Number.isFinite(n)||n<0)return'—';if(n>=1073741824)return(n/1073741824).toFixed(2)+' GB';if(n>=1048576)return(n/1048576).toFixed(1)+' MB';if(n>=1024)return(n/1024).toFixed(0)+' KB';return n.toFixed(0)+' B'}
function statValue(value,suffix='%'){return Number.isFinite(Number(value))?`${Number(value).toFixed(0)}${suffix}`:'API未提供'}
function metricHealth(name,value){const n=Number(value);if(!Number.isFinite(n))return{state:'neutral',level:0};const thresholds={cpu:[75,95,100],gpu:[85,98,100],vram:[80,95,100],ram:[75,90,100],temperature:[70,83,95],fan:[75,95,100],power:[250,330,350]},[warning,critical,max]=thresholds[name]||[75,90,100];return{state:n>=critical?'critical':n>=warning?'warning':'healthy',level:Math.max(0,Math.min(100,n/max*100))}}
function refreshDeviceDisks(disks){const container=$('device-disks'),items=Array.isArray(disks)?disks:[];container.innerHTML=items.map(d=>{const used=Math.max(0,Math.min(100,Number(d.percent)||0)),state=used>=90?'critical':used>=75?'warning':'healthy',mount=esc(String(d.mount||d.source||'磁盘'));return`<div class="device-disk ${state}" title="${mount}：已用 ${formatGiB(d.used)}，可用 ${formatGiB(d.available)}"><span>${mount}</span><b>${used.toFixed(0)}%</b><small>${formatGiB(d.available)} 可用 / ${formatGiB(d.total)}</small><i><em style="width:${used}%"></em></i></div>`}).join('')}
async function refreshDeviceStats(){const panel=$('device-stats');try{const d=await api('/api/device-stats'+activeComfyQuery());if(!d.ok)throw new Error(d.error||'读取失败');panel.classList.remove('offline');panel.classList.add('online');panel.querySelector('.device-stats-name span').textContent=d.device_name;const set=(name,value,raw,title='')=>{const item=panel.querySelector(`[data-stat="${name}"]`),b=item.querySelector('b'),health=metricHealth(name,raw);b.textContent=value;b.title=title;item.classList.remove('healthy','warning','critical','neutral');item.classList.add(health.state);item.style.setProperty('--level',health.level+'%');item.title=health.state==='critical'?'负载或温度已达到高位':health.state==='warning'?'当前数值偏高，请留意':'状态正常'};set('cpu',statValue(d.cpu_percent),d.cpu_percent);set('gpu',statValue(d.gpu_percent),d.gpu_percent);set('vram',`${statValue(d.vram_percent)} · ${formatGiB(d.vram_used)}/${formatGiB(d.vram_total)}`,d.vram_percent);set('ram',`${statValue(d.ram_percent)} · ${formatGiB(d.ram_used)}/${formatGiB(d.ram_total)}`,d.ram_percent);set('temperature',statValue(d.temperature,'°C'),d.temperature);set('fan',statValue(d.fan_percent),d.fan_percent);set('power',statValue(d.power_watts,'W'),d.power_watts);refreshDeviceDisks(d.disks)}catch(e){panel.classList.remove('online');panel.classList.add('offline');panel.querySelector('.device-stats-name span').textContent='设备信息读取失败：'+e.message;refreshDeviceDisks([])}}
function statusLabel(s){const base=statusText[s.status]||s.status;if(s.status==='syncing'&&s.transfer_progress){const p=s.transfer_progress,received=formatTransferBytes(p.bytes_received),total=Number.isFinite(Number(p.total_bytes))?'/'+formatTransferBytes(p.total_bytes):'',speed=Number(p.bytes_per_second)>0?'·'+formatTransferBytes(p.bytes_per_second)+'/s':'';return`${base}·${received}${total}${speed}`}if(!['queued','running'].includes(s.status))return base;const eta=formatRemaining(Number(s.estimated_remaining_seconds)),live=String(s.eta_source||'').includes('live_sampling')?'·采样实测':'';return eta?`${base}·剩余约${eta}${live}`:base}
function refreshStatusCells(){document.querySelectorAll('#storyboard-body .shot-row').forEach(row=>{const s=board.shots[Number(row.dataset.i)],cell=row.querySelector('.status');if(s&&cell){cell.textContent=statusLabel(s);cell.className='status '+s.status}});renderQueueSidebar()}
function renderQueueSidebar(){const sidebar=$('queue-sidebar'),list=$('queue-list'),shotIndex=new Map(board.shots.map((s,i)=>[s.id,i])),jobs=[...pendingRefineSubmissions,...comfyQueue],cancellable=comfyQueue.filter(job=>job.prompt_id);sidebar.classList.toggle('has-items',jobs.length>0);$('queue-count').textContent=`${jobs.length} 个`;$('queue-cancel-all').disabled=!cancellable.length;list.innerHTML=jobs.map((job,position)=>{const i=shotIndex.get(job.shot_id),progress=Number.isFinite(Number(job.progress_percent))?Math.max(0,Math.min(100,Number(job.progress_percent))):0,label=job.status==='submitting'?'提交中':job.status==='running'?'生成中':'排队中',meta=job.status==='submitting'?(job.message||'正在检查节点并上传素材…'):`ComfyUI ${job.status==='running'?'正在执行':`等待位置 ${job.position}`}`;return`<article class="queue-item ${esc(job.status)}"><div class="queue-item-top"><b>#${position+1} · ${esc(job.shot_id||(job.prompt_id||'').slice(0,8))}</b><span class="status ${esc(job.status)}">${label}</span></div><div class="queue-item-title">${esc(job.title)}</div><div class="queue-item-meta">${esc(meta)}</div>${job.status==='running'?`<div class="queue-progress" title="${progress}%"><span style="width:${progress}%"></span></div>`:''}<div class="queue-item-actions">${i!==undefined?`<button data-queue-locate="${i}">定位</button>`:''}${job.status!=='submitting'?`<button class="danger" data-prompt-cancel="${esc(job.prompt_id)}">取消</button>`:''}</div></article>`}).join('')}
function setQueueCollapsed(collapsed,persist=true){const sidebar=$('queue-sidebar'),toggle=$('queue-toggle');sidebar.classList.toggle('collapsed',collapsed);document.body.classList.toggle('queue-collapsed',collapsed);toggle.setAttribute('aria-expanded',String(!collapsed));toggle.textContent=collapsed?'← 展开队列':'收起';toggle.title=collapsed?'展开生成队列':'收起生成队列';if(persist)localStorage.setItem('ref2va.queueCollapsed',collapsed?'1':'0')}
function setPreviewSidebarState(collapsed,enlarged,persist=true){const sidebar=$('preview-sidebar'),toggle=$('preview-sidebar-toggle'),size=$('preview-size-toggle');sidebar.classList.toggle('collapsed',collapsed);sidebar.classList.toggle('enlarged',enlarged);document.body.classList.toggle('preview-collapsed',collapsed);document.body.classList.toggle('preview-enlarged',enlarged&&!collapsed);toggle.setAttribute('aria-expanded',String(!collapsed));toggle.textContent=collapsed?'展开预览 →':'收起';toggle.title=collapsed?'展开连续预览':'收起连续预览';size.textContent=enlarged?'还原':'放大';size.title=enlarged?'恢复默认宽度':'放大连续预览';if(persist){localStorage.setItem('ref2va.previewCollapsed',collapsed?'1':'0');localStorage.setItem('ref2va.previewEnlarged',enlarged?'1':'0')}}
function render(){
  renderSharedAssets();
  const body=$('storyboard-body');body.innerHTML='';
  board.shots.forEach((s,i)=>{
    const tr=document.createElement('tr');tr.className='shot-row '+(i===expanded?'active':'');tr.dataset.i=i;
    const thumbs=(s.references||[]).slice(0,3).map(p=>`<img src="/api/file-preview?path=${encodeURIComponent(p)}" data-preview-path="${esc(p)}" title="双击查看大图">`).join('')+((s.references||[]).length>3?`<span class="more">+${s.references.length-3}</span>`:'');
    tr.innerHTML=`<td class="shot-number">${i+1}</td><td><input class="select-shot" type="checkbox" aria-label="选择片段 ${esc(s.id)}" ${s.selected?'checked':''}></td><td class="shot-id">${esc(s.id)}</td><td>${esc(s.title)}</td><td><div class="thumbs">${thumbs||'—'}</div></td><td>${esc((s.resolution||'480p').toUpperCase())} · ${esc(aspectText[s.aspect_ratio]||s.aspect_ratio)}</td><td>${esc(s.duration)}秒</td><td>${esc(s.seed)}</td><td><span class="status ${esc(s.status)}">${esc(statusLabel(s))}</span></td><td>${(s.results||[]).length} 个</td><td><button class="edit">编辑</button> <button class="copy">复制</button></td>`;
    body.appendChild(tr);if(i===expanded)body.appendChild(makeEditorRow(s,i));
  });
  refreshContinuousPreview();
  renderQueueSidebar();
  const selectedCount=board.shots.filter(s=>s.selected).length,allSelected=board.shots.length>0&&selectedCount===board.shots.length;
  $('toggle-select-all').checked=allSelected;
  $('toggle-select-all').indeterminate=selectedCount>0&&!allSelected;
  window.Ref2VACanvas?.render(board);
}
function renderSharedAssets(){const shared=normalizeShared(board.shared);board.shared=shared;const total=shared.references.length+shared.reference_videos.length+shared.reference_audios.length;$('shared-enabled').checked=shared.enabled;$('shared-prompt').value=shared.prompt;$('shared-assets-summary').textContent=shared.enabled?`${total} 个素材 · 已应用`:`${total} 个素材 · 未应用`;const items=[...shared.references.map((p,i)=>`<span>公共 Picture ${i+1}：${esc(p.split(/[\\/]/).pop())}</span>`),...shared.reference_videos.map((p,i)=>`<span>公共 Video ${i+1}：${esc(p.split(/[\\/]/).pop())}</span>`),...shared.reference_audios.map((p,i)=>`<span>公共 Audio ${i+1}：${esc(p.split(/[\\/]/).pop())}</span>` )];$('shared-assets-list').innerHTML=items.join('')||'<span>尚无公共参考素材；可通过 Director 包导入。</span>'}
function refreshContinuousPreview(){
  const video=$('continuous-video'),currentId=continuousItems[continuousIndex]?.result?.id||video.dataset.resultId;
  continuousItems=Ref2VAPlaylist.buildContinuousPlaylist(board.shots);
  continuousIndex=Ref2VAPlaylist.reconcilePlaylistIndex(continuousItems,currentId,continuousIndex);
  const available=continuousItems.length;
  $('continuous-preview').classList.toggle('has-items',available>0);
  $('preview-count').textContent=`${available} 段可用`;
  if(!available){clearContinuousStandby();video.removeAttribute('src');delete video.dataset.resultId;delete video.dataset.itemKey;video.load();$('preview-status').textContent='尚无可播放片段';$('preview-notice').textContent='';updateContinuousButtons();return}
  showContinuousItem(continuousIndex,false);
}
function continuousItemKey(item){return`${item.shotId}:${item.result.id}`}
function clearContinuousStandby(){if(continuousStandby){continuousStandby.remove();continuousStandby=null}}
function continuousVideoUrl(item){return`/api/results/video/${encodeURIComponent(item.shotId)}/${encodeURIComponent(item.result.id)}`}
function preloadNextContinuous(){const next=continuousItems[continuousIndex+1],active=$('continuous-video');if(!next||!active||!active.parentNode){clearContinuousStandby();return}const nextKey=continuousItemKey(next);if(Ref2VAMedia.canReusePreload(continuousStandby,nextKey))return;clearContinuousStandby();continuousStandby=Ref2VAMedia.preparePreload(active,nextKey,continuousVideoUrl(next));continuousStandby.onerror=()=>{if(continuousStandby?.dataset.itemKey===nextKey)clearContinuousStandby()}}
function updateContinuousButtons(){
  const count=continuousItems.length;
  $('preview-restart').disabled=!count;
  $('preview-prev').disabled=count<2||continuousIndex<=0;
  $('preview-next').disabled=count<2||continuousIndex>=count-1;
}
function handleContinuousError(itemKey){
  const failedItem=continuousItems.find(item=>continuousItemKey(item)===itemKey);
  if(failedItem)continuousFailures.add(continuousItemKey(failedItem));
  if(continuousItems.length&&continuousItems.every(item=>continuousFailures.has(continuousItemKey(item)))){$('preview-notice').textContent='所有可用片段均加载失败';updateContinuousButtons();return}
  if(failedItem)$('preview-notice').textContent=`加载失败：${failedItem.shotId} ${failedItem.title||'未命名片段'}；正在跳到下一段`;
  for(let offset=1;offset<=continuousItems.length;offset++){
    const next=(continuousIndex+offset)%continuousItems.length,item=continuousItems[next];
    if(!continuousFailures.has(continuousItemKey(item))){showContinuousItem(next,continuousPlaybackStarted);return}
  }
  $('preview-notice').textContent='没有可继续播放的片段';
}
function unbindContinuousMediaEvents(video){
  if(continuousMediaHandlers){video.removeEventListener('play',continuousMediaHandlers.play);video.removeEventListener('ended',continuousMediaHandlers.ended);video.removeEventListener('error',continuousMediaHandlers.error);video.removeEventListener('loadeddata',continuousMediaHandlers.loadeddata)}
  continuousMediaHandlers=null;
}
function bindContinuousMediaEvents(video,itemKey){
  unbindContinuousMediaEvents(video);
  const current=()=>video.dataset.itemKey===itemKey;
  continuousMediaHandlers={
    play:()=>{if(!current())return;continuousPlaybackStarted=true},
    ended:()=>{if(!current())return;advanceContinuous(1,continuousPlaybackStarted)},
    error:()=>{if(video.dataset.itemKey!==itemKey)return;handleContinuousError(itemKey)},
    loadeddata:()=>{if(!current())return;continuousFailures.delete(itemKey);$('preview-notice').textContent='';preloadNextContinuous()}
  };
  video.addEventListener('play',continuousMediaHandlers.play);video.addEventListener('ended',continuousMediaHandlers.ended);video.addEventListener('error',continuousMediaHandlers.error);video.addEventListener('loadeddata',continuousMediaHandlers.loadeddata);
}
function showContinuousItem(index,autoplay){
  if(!continuousItems.length){updateContinuousButtons();return}
  continuousIndex=Math.max(0,Math.min(index,continuousItems.length-1));
  const item=continuousItems[continuousIndex],resultId=String(item.result.id);let video=$('continuous-video');
  const key=continuousItemKey(item);
  if(video.dataset.itemKey!==key){if(continuousStandby?.dataset.itemKey===key&&continuousStandby.readyState>=2){const standby=continuousStandby;continuousStandby=null;video=Ref2VAMedia.promotePreloaded(video,standby,key,unbindContinuousMediaEvents,bindContinuousMediaEvents)}else{clearContinuousStandby();video=Ref2VAMedia.replaceMediaElement(video,key,unbindContinuousMediaEvents,bindContinuousMediaEvents);video.src=continuousVideoUrl(item)}video.dataset.resultId=resultId}
  $('preview-status').textContent=`${item.shotId} ${item.title||'未命名片段'} · ${continuousIndex+1} / ${continuousItems.length}`;
  updateContinuousButtons();
  if(video.readyState>=2)preloadNextContinuous();
  if(autoplay){continuousPlaybackStarted=true;const promise=video.play();if(promise&&promise.catch)promise.catch(()=>{if(video.dataset.itemKey!==key)return;continuousPlaybackStarted=false;$('preview-notice').textContent='浏览器阻止自动播放，请点击播放继续'})}
}
function restartContinuous(){
  const video=$('continuous-video');video.currentTime=0;showContinuousItem(0,true);
}
function advanceContinuous(delta,autoplay){
  const next=continuousIndex+delta;
  if(next<0||next>=continuousItems.length){updateContinuousButtons();return false}
  showContinuousItem(next,autoplay);return true;
}
function makeEditorRow(s,shotIndex){
  const tr=document.createElement('tr');tr.className='editor-row';const td=document.createElement('td');td.colSpan=11;
  const box=$('editor-template').content.firstElementChild.cloneNode(true);td.appendChild(box);tr.appendChild(td);
  box.querySelector('.editor-grid').before(box.querySelector('.shot-card-section'));
  box.querySelector('.edit-id').value=s.id;box.querySelector('.edit-title').value=s.title;box.querySelector('.edit-output').value=s.output_name;box.querySelector('.edit-prompt').value=s.prompt;box.querySelector('.edit-shot-card').value=s.shot_card_zh||'';box.querySelector('.edit-duration').value=s.duration;box.querySelector('.edit-seed').value=s.seed;box.querySelector('.edit-resolution').value=s.resolution;box.querySelector('.edit-aspect').value=s.aspect_ratio;box.querySelector('.edit-generation-mode').value=s.generation_mode||'r2va';box.querySelector('.edit-reference-image-size').value=s.reference_image_size==='max'?'max':'match';box.querySelector('.edit-audio-tail').value=s.audio_tail_carryover||'No Audio Carryover';
  const continuation=box.querySelector('.edit-continuation');if(shotIndex===0)s.continue_from_previous=false;continuation.checked=Boolean(s.continue_from_previous);continuation.disabled=shotIndex===0;
  s.director=normalizeDirector(s.director);const director=s.director,directorEnabled=box.querySelector('.director-enabled'),directorControls=box.querySelector('.director-controls'),directorPreview=box.querySelector('.director-preview');
  const refreshDirector=()=>{directorEnabled.checked=director.enabled;directorControls.hidden=!director.enabled;box.querySelector('.director-shot-type').value=director.shot_type;box.querySelector('.director-camera-motion').value=director.camera_motion;box.querySelector('.director-audio-cue').value=director.audio_cue;box.querySelector('.director-continuity').value=director.continuity};
  directorEnabled.onchange=e=>{director.enabled=e.target.checked;directorPreview.hidden=true;s.status='draft';refreshDirector();scheduleSave()};
  [['.director-shot-type','shot_type'],['.director-camera-motion','camera_motion'],['.director-audio-cue','audio_cue'],['.director-continuity','continuity']].forEach(([selector,key])=>box.querySelector(selector).onchange=e=>{director[key]=e.target.value;directorPreview.hidden=true;s.status='draft';scheduleSave()});
  box.querySelector('.preview-director-prompt').onclick=async()=>{try{const result=await api('/api/prompts/director',jsonOpt('POST',{prompt:s.prompt,generation_mode:s.generation_mode,director}));directorPreview.textContent=result.note?`将提交给 H3 的附加导演指令：\n${result.note}\n\n完整预览：\n${result.prompt}`:'本镜未启用 Director，提交原提示词。';directorPreview.hidden=false}catch(error){box.querySelector('.editor-message').textContent='Director 预览失败：'+error.message}};
  refreshDirector();
  const saveLatent=box.querySelector('.edit-save-latent');saveLatent.checked=Boolean(s.save_latent)||willBeContinued(s);saveLatent.disabled=willBeContinued(s);saveLatent.title=willBeContinued(s)?'下一镜需要延续，必须保存':'保存当前分镜的 AV Latent，供后续镜头使用';
  renderRefs(box,s);renderResults(box,s);box.querySelector('.editor-message').textContent=s.error||'';
  [['id','id'],['title','title'],['output','output_name']].forEach(([c,k])=>box.querySelector('.edit-'+c).oninput=e=>{s[k]=e.target.value;scheduleSave()});
  box.querySelector('.edit-prompt').oninput=e=>{s.prompt=e.target.value;s.status='draft';scheduleSave()};
  const syncStatus=box.querySelector('.shot-card-sync-status'),syncButton=box.querySelector('.mark-shot-card-synced');
  const refreshCardSync=()=>{syncStatus.textContent=s.shot_card_needs_sync?'英文 H3 待同步':s.shot_card_zh?'中文卡与英文已确认同步':'尚未填写';syncStatus.classList.toggle('needs-sync',Boolean(s.shot_card_needs_sync));syncButton.disabled=!s.shot_card_zh||!s.prompt||!s.shot_card_needs_sync};
  box.querySelector('.edit-shot-card').oninput=e=>{s.shot_card_zh=e.target.value;s.shot_card_needs_sync=Boolean(s.shot_card_zh);refreshCardSync();scheduleSave()};
  syncButton.onclick=()=>{s.shot_card_needs_sync=false;refreshCardSync();scheduleSave()};
  refreshCardSync();
  box.querySelector('.edit-duration').oninput=e=>{s.duration=Number(e.target.value);scheduleSave()};
  box.querySelector('.edit-seed').oninput=e=>{s.seed=Number(e.target.value);scheduleSave()};
  box.querySelector('.edit-resolution').onchange=e=>{s.resolution=e.target.value;s.status='draft';scheduleSave();render()};
  box.querySelector('.edit-aspect').onchange=e=>{s.aspect_ratio=e.target.value;s.status='draft';scheduleSave();render()};
  box.querySelector('.edit-generation-mode').onchange=e=>{s.generation_mode=e.target.value;s.status='draft';scheduleSave();render()};
  box.querySelector('.edit-reference-image-size').onchange=e=>{s.reference_image_size=e.target.value==='max'?'max':'match';s.status='draft';scheduleSave();render()};
  box.querySelector('.edit-audio-tail').onchange=e=>{s.audio_tail_carryover=e.target.value;s.status='draft';scheduleSave()};
  continuation.onchange=e=>{s.continue_from_previous=e.target.checked;if(e.target.checked&&shotIndex>0)board.shots[shotIndex-1].save_latent=true;s.status='draft';scheduleSave();render()};
  saveLatent.onchange=e=>{s.save_latent=e.target.checked;s.status='draft';scheduleSave();render()};
  const input=box.querySelector('.image-input'),drop=box.querySelector('.image-drop-zone');
  box.querySelector('.pick-images').onclick=e=>{e.stopPropagation();input.click()};drop.onclick=()=>input.click();
  drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click()}};
  input.onchange=async()=>{await uploadImages(input.files,s,box);input.value=''};
  ['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();drop.classList.add('dragover')}));
  ['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();drop.classList.remove('dragover')}));
  drop.addEventListener('drop',e=>uploadImages(e.dataTransfer.files,s,box));
  const videoInput=box.querySelector('.video-input'),videoDrop=box.querySelector('.video-drop-zone');
  box.querySelector('.pick-videos').onclick=e=>{e.stopPropagation();videoInput.click()};videoDrop.onclick=()=>videoInput.click();
  videoDrop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();videoInput.click()}};
  videoInput.onchange=async()=>{await uploadVideos(videoInput.files,s,box);videoInput.value=''};
  ['dragenter','dragover'].forEach(name=>videoDrop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();videoDrop.classList.add('dragover')}));
  ['dragleave','drop'].forEach(name=>videoDrop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();videoDrop.classList.remove('dragover')}));
  videoDrop.addEventListener('drop',e=>uploadVideos(e.dataTransfer.files,s,box));
  const audioInput=box.querySelector('.audio-input'),audioDrop=box.querySelector('.audio-drop-zone');
  box.querySelector('.pick-audios').onclick=e=>{e.stopPropagation();audioInput.click()};audioDrop.onclick=()=>audioInput.click();
  audioDrop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();audioInput.click()}};
  audioInput.onchange=async()=>{await uploadAudios(audioInput.files,s,box);audioInput.value=''};
  ['dragenter','dragover'].forEach(name=>audioDrop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();audioDrop.classList.add('dragover')}));
  ['dragleave','drop'].forEach(name=>audioDrop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();audioDrop.classList.remove('dragover')}));
  audioDrop.addEventListener('drop',e=>uploadAudios(e.dataTransfer.files,s,box));
  box.querySelector('.pick-text').onclick=async()=>{const d=await api('/api/pick-text',jsonOpt('POST',{}));if(d.text){s.prompt=d.text;s.status='draft';scheduleSave();render()}};
  const cancelButton=box.querySelector('.cancel-shot');cancelButton.hidden=!['queued','running'].includes(s.status);cancelButton.onclick=()=>cancelShot(s,box);
  box.querySelector('.validate-shot').onclick=()=>validateLocal(s,box);box.querySelector('.submit-shot').onclick=()=>submitShot(s,box);box.querySelector('.open-run').onclick=()=>s.run_dir&&api('/api/open-path',jsonOpt('POST',{path:s.run_dir}));box.querySelector('.open-output').onclick=openOutput;return tr;
}
async function uploadImages(files,s,box){
  if(!files||!files.length)return;
  const message=box.querySelector('.editor-message'),form=new FormData();
  [...files].forEach(file=>form.append('files',file,file.name));message.textContent=`正在上传 ${files.length} 张图片…`;
  try{const d=await api('/api/upload-images',{method:'POST',body:form});s.references.push(...d.paths.filter(p=>!s.references.includes(p)));s.status='draft';message.textContent=`已添加 ${d.paths.length} 张图片`;scheduleSave();render()}catch(e){message.textContent='上传失败：'+e.message}
}
async function uploadVideos(files,s,box){
  if(!files||!files.length)return;
  const remaining=3-(s.reference_videos||[]).length,message=box.querySelector('.editor-message');
  if(remaining<=0){message.textContent='参考视频最多3段';return}
  const selected=[...files].slice(0,remaining),form=new FormData();
  selected.forEach(file=>form.append('files',file,file.name));message.textContent=`正在上传 ${selected.length} 段视频…`;
  try{const d=await api('/api/upload-videos',{method:'POST',body:form});s.reference_videos.push(...d.paths.filter(p=>!s.reference_videos.includes(p)));s.status='draft';message.textContent=`已添加 ${d.paths.length} 段参考视频`;scheduleSave();render()}catch(e){message.textContent='上传失败：'+e.message}
}
async function uploadAudios(files,s,box){
  if(!files||!files.length)return;
  const remaining=3-(s.reference_audios||[]).length,message=box.querySelector('.editor-message');
  if(remaining<=0){message.textContent='纯音频参考最多3段';return}
  const selected=[...files].slice(0,remaining),form=new FormData();
  selected.forEach(file=>form.append('files',file,file.name));message.textContent=`正在添加 ${selected.length} 段纯音频参考…`;
  try{const d=await api('/api/upload-audios',{method:'POST',body:form});s.reference_audios.push(...d.paths.filter(p=>!s.reference_audios.includes(p)));s.status='draft';message.textContent=`已添加 ${d.paths.length} 段；提交时自动提取 WAV`;scheduleSave();render()}catch(e){message.textContent='上传失败：'+e.message}
}
function renderRefs(box,s){
  const mode=s.generation_mode||'r2va',continued=Boolean(s.continue_from_previous),guidance=box.querySelector('.reference-guidance');
  guidance.textContent=mode==='r2va'?'全部图片按顺序作为 <Picture N>；可与上一镜 Latent 同时使用。':continued?'第1张为新尾帧，其余为 Qwen 参考图；开头来自上一镜 Latent。':'第1张首帧，第2张尾帧，其余为 Qwen 参考图。';
  const label=n=>mode==='r2va'?`<Picture ${n+1}>`:continued?(n===0?'尾帧':`Qwen参考 ${n}`):(n===0?'首帧':n===1?'尾帧':`Qwen参考 ${n-1}`);
  const list=box.querySelector('.reference-list');list.innerHTML=s.references.map((p,n)=>`<div class="ref-card"><img src="/api/file-preview?path=${encodeURIComponent(p)}" data-preview-path="${esc(p)}" title="双击查看大图"><b>${esc(label(n))}</b><small title="${esc(p)}">${esc(p)}</small><div class="ref-actions"><button data-move="-1" data-n="${n}">←</button><button data-move="1" data-n="${n}">→</button><button data-remove="${n}">删</button></div></div>`).join('')||'<span>尚未选择参考图</span>';
  list.onclick=e=>{const n=Number(e.target.dataset.n);let changed=false;if(e.target.dataset.move){const to=n+Number(e.target.dataset.move);if(to>=0&&to<s.references.length){[s.references[n],s.references[to]]=[s.references[to],s.references[n]];changed=true}}else if(e.target.dataset.remove!==undefined){s.references.splice(Number(e.target.dataset.remove),1);changed=true}if(changed){s.status='draft';scheduleSave();render()}};
  const videos=box.querySelector('.reference-video-list');videos.innerHTML=(s.reference_videos||[]).map((p,n)=>`<div class="ref-card"><video controls preload="metadata" src="/api/video-preview?path=${encodeURIComponent(p)}"></video><b>&lt;Video ${n+1}&gt; / &lt;Audio ${n+1}&gt;</b><small title="${esc(p)}">${esc(p)}</small><div class="ref-actions"><button data-video-move="-1" data-n="${n}">←</button><button data-video-move="1" data-n="${n}">→</button><button data-video-to-audio="${n}" title="不参考画面，只保留音色/声音">转纯音频</button><button data-video-remove="${n}">删</button></div></div>`).join('')||'<span>尚未选择参考视频</span>';
  videos.onclick=e=>{const n=Number(e.target.dataset.n);let changed=false;if(e.target.dataset.videoMove){const to=n+Number(e.target.dataset.videoMove);if(to>=0&&to<s.reference_videos.length){[s.reference_videos[n],s.reference_videos[to]]=[s.reference_videos[to],s.reference_videos[n]];changed=true}}else if(e.target.dataset.videoToAudio!==undefined){if((s.reference_audios||[]).length>=3)return;const [path]=s.reference_videos.splice(Number(e.target.dataset.videoToAudio),1);if(path&&!s.reference_audios.includes(path))s.reference_audios.push(path);changed=true}else if(e.target.dataset.videoRemove!==undefined){s.reference_videos.splice(Number(e.target.dataset.videoRemove),1);changed=true}if(changed){s.status='draft';scheduleSave();render()}};
  const audios=box.querySelector('.reference-audio-list');audios.innerHTML=(s.reference_audios||[]).map((p,n)=>`<div class="ref-card"><div class="audio-ref-icon">♪</div><b>&lt;Audio ${(s.reference_videos||[]).length+n+1}&gt; · 纯音频</b><small title="${esc(p)}">${esc(p)}</small><div class="ref-actions"><button data-audio-move="-1" data-n="${n}">←</button><button data-audio-move="1" data-n="${n}">→</button><button data-audio-remove="${n}">删</button></div></div>`).join('')||'<span>尚未选择纯音频参考</span>';
  audios.onclick=e=>{const n=Number(e.target.dataset.n);let changed=false;if(e.target.dataset.audioMove){const to=n+Number(e.target.dataset.audioMove);if(to>=0&&to<s.reference_audios.length){[s.reference_audios[n],s.reference_audios[to]]=[s.reference_audios[to],s.reference_audios[n]];changed=true}}else if(e.target.dataset.audioRemove!==undefined){s.reference_audios.splice(Number(e.target.dataset.audioRemove),1);changed=true}if(changed){s.status='draft';scheduleSave();render()}};
}
function openImagePreview(path){
  const dialog=$('image-preview-dialog'),image=$('image-preview-full');
  image.src='/api/file-preview?path='+encodeURIComponent(path);image.alt=path;
  if(!dialog.open)dialog.showModal();
}
function renderResults(box,s){
  const results=[...(s.results||[])].reverse(),list=box.querySelector('.result-list');
  box.querySelector('.result-summary').textContent=results.length?`共 ${results.length} 个，全部保留`:'尚无已收集结果';
  list.innerHTML=results.map(r=>`<article class="result-card"><video controls preload="metadata" src="/api/results/video/${encodeURIComponent(s.id)}/${encodeURIComponent(r.id)}"></video><b>${esc(r.filename||'生成视频')}</b><div class="result-meta"><span>${esc(formatTime(r.created_at))}</span><span>${esc(r.resolution||r.status||'ready')}</span></div><div class="result-actions"><button data-refine-result="${esc(r.id)}">${resultPass(r)+1}采到${esc((board.advanced_settings.refine_target_resolution||'0.9mp').toUpperCase())}</button><button data-open-result="${esc(r.id)}">打开目录</button><button class="danger" data-delete-result="${esc(r.id)}">永久删除</button></div></article>`).join('')||'<span>视频生成完成后会自动出现在这里。</span>';
  const restoreButton=box.querySelector('.restore-results');
  if(restoreButton)restoreButton.onclick=async()=>{if(restoreButton.disabled)return;restoreButton.disabled=true;restoreButton.textContent='正在从 ComfyUI 恢复…';try{const d=await api('/api/results/restore',jsonOpt('POST',{shot_id:s.id}));s.results=d.results;s.status=(s.results||[]).length?'completed':s.status;s.error='';await saveBoard();render();updateEditorMessage(s,d.restored?`已从 ComfyUI 拉回 ${d.restored} 个视频${d.repaired?`（修复 ${d.repaired} 条失效记录）`:''}`:'ComfyUI 上没有可恢复的视频')}catch(err){render();updateEditorMessage(s,'恢复失败：'+err.message)}};
  list.onclick=async e=>{const openId=e.target.dataset.openResult,deleteId=e.target.dataset.deleteResult,refineId=e.target.dataset.refineResult;if(refineId){await refineResult(s,refineId,e.target);return;}if(openId){const result=s.results.find(x=>x.id===openId);if(result)await api('/api/open-path',jsonOpt('POST',{path:result.path}))}if(deleteId){const result=s.results.find(x=>x.id===deleteId);if(!result||!confirm(`确定永久删除“${result.filename||'这个视频'}”吗？此操作无法恢复。`))return;try{const d=await api(`/api/results/${encodeURIComponent(s.id)}/${encodeURIComponent(deleteId)}`,{method:'DELETE'});s.results=d.results;s.prompt_id=d.prompt_id||'';if(d.refine_cleared)delete s.refine_job;render();await saveBoard()}catch(err){box.querySelector('.editor-message').textContent='删除失败：'+err.message}}};
}
let resultRefineSubmitting=false;
async function refineResult(s,resultId,button){
  if(resultRefineSubmitting||refineSubmitting){$('global-status').textContent='二采正在提交，请勿重复点击';return}
  resultRefineSubmitting=true;
  const originalText=button.textContent;
  button.disabled=true;button.textContent='正在提交…';
  $('global-status').textContent=`正在提交 ${s.id} 的精修任务…`;
  try{
    await saveBoard();
    const d=await submitRefine(s,null,false,resultId);
    const message=`已提交${d.refine_job.pass_number}采，正在 ComfyUI 排队`;
    $('global-status').textContent=message;updateEditorMessage(s,message);
  }catch(err){
    const message='精修提交失败：'+err.message;
    $('global-status').textContent=message;updateEditorMessage(s,message);
  }finally{resultRefineSubmitting=false;button.disabled=false;button.textContent=originalText}
}
let batchScheduling=false;
function normalizedTargetUrl(value){return String(value||'').trim().replace(/\/+$/,'').replace('localhost','127.0.0.1')}
function activeTargetUrl(){return normalizedTargetUrl(board.advanced_settings?.generation_target==='remote'?board.advanced_settings.comfy_url:'http://127.0.0.1:8188')}
function belongsToActiveTarget(comfyUrl){return !comfyUrl||normalizedTargetUrl(comfyUrl)===activeTargetUrl()}
function hasActiveGeneration(){return board.shots.some(s=>belongsToActiveTarget(s.comfy_url)&&['queued','running','syncing'].includes(s.status))}
function hasActiveRefine(){return board.shots.some(s=>belongsToActiveTarget(s.refine_job?.comfy_url)&&['queued','running','syncing'].includes(s.refine_job?.status))}
function resultPass(r){const value=Number(r?.pass_number);if(Number.isInteger(value)&&value>=1)return value;const matched=/_p(\d+)(?:_|$)/.exec(String(r?.filename||''));return matched?Number(matched[1]):1}
function resultLatent(r,s){if(r?.latent_name)return String(r.latent_name);return resultPass(r)<=1?String(s.output_name||''):`${s.output_name}_p${resultPass(r)}`}
async function submitRefine(s,box=null,managedByBatch=false,sourceResultId=null){if(hasActiveGeneration()||(!managedByBatch&&hasActiveRefine()))throw new Error('请等待当前生成/二采任务完成');let previous,pass;const source=sourceResultId?(s.results||[]).find(r=>r.id===sourceResultId):null;if(source){pass=resultPass(source)+1;previous=resultLatent(source,s);if(pass>9)throw new Error(`该结果已经是 ${pass-1} 采，档位已达上限，请从更早的结果重新开始`)}else{const jobFresh=s.refine_job?.status==='completed'&&(s.refine_job.submitted_at||0)>=(s.submitted_at||0);previous=jobFresh?(s.refine_job.latent_name||s.refine_job.output_name):s.output_name;pass=jobFresh?(s.refine_job.pass_number||2)+1:2}const d=await api('/api/refine',jsonOpt('POST',{shot_id:s.id,target_resolution:board.advanced_settings.refine_target_resolution,source_latent_name:previous,pass_number:pass,source_result_id:source?source.id:''}));s.refine_job=d.refine_job;if(s.refine_job&&!s.refine_job.submitted_at)s.refine_job.submitted_at=s.submitted_at||Date.now()/1000;if(box)box.querySelector('.editor-message').textContent=`已提交${pass}采`;await saveBoard();render();return d}
async function waitForRefine(s){while(['queued','running'].includes(s.refine_job?.status)){await new Promise(resolve=>setTimeout(resolve,1500));const d=await api('/api/task-status/'+s.refine_job.prompt_id+targetQuery(s.refine_job.comfy_url));s.refine_job.status=d.status;if(d.status==='completed'){s.prompt_id=s.refine_job.prompt_id;s.comfy_url=s.refine_job.comfy_url;s.resolution=s.refine_job.target_resolution;await saveBoard();await collectResults(s)}await saveBoard();render()}return s.refine_job?.status}
async function refineSelected(){if(refineSubmitting||resultRefineSubmitting){$('global-status').textContent='二采正在提交，请勿重复点击';return}const shots=board.shots.filter(s=>s.selected&&s.status==='completed');if(!shots.length){$('global-status').textContent='请选中已完成一采的分镜';return}if(hasActiveGeneration()||hasActiveRefine()){$('global-status').textContent='已有生成/二采任务，请完成后再批量提交';return}refineSubmitting=true;const button=$('refine-selected'),originalText=button.textContent,maxAttempts=3;button.disabled=true;button.textContent='正在提交二采…';pendingRefineSubmissions=shots.map(s=>({prompt_id:`pending-refine-${s.id}`,shot_id:s.id,title:`${s.title||s.output_name}·二采`,status:'submitting',message:'等待按故事板顺序提交'}));renderQueueSidebar();let submitted=0,stopped=false;try{for(let i=0;i<shots.length;i++){const s=shots[i],pending=()=>pendingRefineSubmissions.find(x=>x.shot_id===s.id);let accepted=false,lastError=null;for(let attempt=1;attempt<=maxAttempts&&!accepted;attempt++){const item=pending();if(item)item.message=attempt===1?'正在检查节点并上传素材…':`连接失败，正在原位重试 ${attempt}/${maxAttempts}…`;renderQueueSidebar();$('global-status').textContent=`正在按顺序提交二采 ${s.id}（${i+1}/${shots.length}）·尝试 ${attempt}/${maxAttempts}`;try{await submitRefine(s,null,true);accepted=true;submitted++;pendingRefineSubmissions=pendingRefineSubmissions.filter(x=>x.shot_id!==s.id);await refreshComfyQueue()}catch(e){lastError=e;if(attempt<maxAttempts)await new Promise(resolve=>setTimeout(resolve,2000))}}if(!accepted){stopped=true;const item=pending();if(item)item.message=`3 次提交均失败，已停止后续队列`;renderQueueSidebar();$('global-status').textContent=`${s.id} 原位重试 3 次仍失败，为保证顺序已停止：${lastError?.message||'未知错误'}`;break}}if(!stopped&&submitted===shots.length)$('global-status').textContent=`${submitted} 个二采任务已按故事板顺序全部进入 ComfyUI 队列`}finally{if(!stopped)pendingRefineSubmissions=[];refineSubmitting=false;button.disabled=false;button.textContent=originalText;await refreshComfyQueue()}}
/* legacy pixel upscaler removed
function hasActiveUpscale(){return board.shots.some(s=>(s.results||[]).some(r=>['queued','running'].includes(r.upscale?.status)))}
async function submitUpscale(s,resultId,box=null){const result=s.results.find(x=>x.id===resultId);if(!result)return false;const target=board.advanced_settings.upscale_resolution||'720p';if(batchScheduling||hasActiveGeneration()){if(box)box.querySelector('.editor-message').textContent='视频生成进行中，完成后才能提交高清放大';return false}result.upscale={status:'queued',target_resolution:target,error:''};render();try{const d=await api('/api/results/upscale',jsonOpt('POST',{shot_id:s.id,result_id:resultId,target_resolution:target}));result.upscale=d.upscale;render();return true}catch(e){result.upscale={status:'failed',target_resolution:target,error:e.message};if(box)box.querySelector('.editor-message').textContent='高清放大提交失败：'+e.message;render();return false}}
let upscaleAllScheduling=false;
function pendingUpscaleResults(target){const items=[];for(const s of board.shots){const results=s.results||[];for(const result of results){if(result.kind==='upscaled'||['queued','running'].includes(result.upscale?.status))continue;const alreadyDone=results.some(item=>item.kind==='upscaled'&&item.source_result_id===result.id&&(item.resolution||'').toLowerCase()===target);if(!alreadyDone)items.push({shot:s,result})}}return items}
async function submitAllUpscales(){if(upscaleAllScheduling){$('global-status').textContent='一键高清放大正在提交中';return}if(batchScheduling||hasActiveGeneration()){$('global-status').textContent='视频生成进行中，完成后才能一键放大全部';return}const target=(board.advanced_settings.upscale_resolution||'720p').toLowerCase(),items=pendingUpscaleResults(target);if(!items.length){$('global-status').textContent=`所有原始结果都已有 ${target.toUpperCase()} 高清版本`;return}upscaleAllScheduling=true;const button=$('upscale-all-results');button.disabled=true;let submitted=0;try{for(let index=0;index<items.length;index++){const {shot,result}=items[index];$('global-status').textContent=`正在提交高清放大 ${index+1}/${items.length}：${shot.id}`;if(await submitUpscale(shot,result.id))submitted++}$('global-status').textContent=`一键高清放大已提交 ${submitted}/${items.length} 个结果到 ${target.toUpperCase()}`}finally{upscaleAllScheduling=false;button.disabled=false}}
async function submitPendingAutoUpscales(){if(!board.advanced_settings.auto_upscale_enabled||batchScheduling||hasActiveGeneration()||hasActiveUpscale())return;for(const s of board.shots){const result=(s.results||[]).find(r=>r.kind!=='upscaled'&&!r.upscale);if(result){$('global-status').textContent=`正在自动高清放大 ${s.id} 到 ${board.advanced_settings.upscale_resolution.toUpperCase()}`;await submitUpscale(s,result.id);return}}}
async function pollUpscales(){let changed=false;for(const s of board.shots){for(const r of(s.results||[])){const up=r.upscale;if(!up?.prompt_id||!['queued','running','failed'].includes(up.status))continue;try{const d=await api('/api/task-status/'+up.prompt_id+targetQuery(up.comfy_url));up.status=d.status;if(d.status==='completed'){const collected=await api('/api/results/upscale/collect',jsonOpt('POST',{shot_id:s.id,result_id:r.id,target_resolution:up.target_resolution||'720p'}));s.results=collected.results}changed=true}catch(e){up.error=e.message;changed=true}}}if(changed){scheduleSave();render()}}
*/
function formatTime(value){if(!value)return'未知时间';const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString()}
function updateEditorMessage(s,message){if(expanded!==board.shots.indexOf(s))return;const node=document.querySelector('#storyboard-body .editor-row .editor-message');if(node)node.textContent=message}
async function collectResults(s){
  if(!s.prompt_id||collecting.has(s.id))return;
  if((s.results||[]).some(r=>r.prompt_id===s.prompt_id))return;
  collecting.add(s.id);
  s.status='syncing';s.transfer_progress={bytes_received:0,total_bytes:null,bytes_per_second:0};if(s.refine_job?.prompt_id===s.prompt_id)s.refine_job.status='syncing';render();scheduleSave();
  const progressTimer=setInterval(async()=>{try{s.transfer_progress=await api('/api/results/transfer/'+encodeURIComponent(s.id));refreshStatusCells()}catch{}},500);
  try{const d=await api('/api/results/collect',jsonOpt('POST',{shot_id:s.id}));s.results=d.results;s.status='completed';delete s.transfer_progress;if(s.refine_job?.prompt_id===s.prompt_id)s.refine_job.status='completed';s.error='';scheduleSave();render()}catch(e){const message='结果回传：'+e.message;s.status='syncing';if(s.refine_job?.prompt_id===s.prompt_id)s.refine_job.status='syncing';if(s.error!==message){s.error=message;updateEditorMessage(s,message);scheduleSave();render()}}finally{clearInterval(progressTimer);collecting.delete(s.id)}
}
function previousOutputName(s){const index=board.shots.indexOf(s);return index>0?String(board.shots[index-1].output_name||''):''}
function willBeContinued(s){const index=board.shots.indexOf(s);return index>=0&&index<board.shots.length-1&&Boolean(board.shots[index+1].continue_from_previous)}
function validateLocal(s,box){const effective=resolvedShot(s),errors=[],videos=effective.reference_videos,audios=effective.reference_audios;if(!effective.references.length&&!videos.length&&!audios.length)errors.push('至少一张参考图、一段参考视频或一段参考音频');if(effective.references.length>9)errors.push('合并公共层后参考图最多9张');if(videos.length>3)errors.push('合并公共层后参考视频最多3段');if(audios.length>3)errors.push('合并公共层后纯音频最多3段');if(!['match','max'].includes(s.reference_image_size||'match'))errors.push('参考图尺寸策略仅支持 Match 或 Max');if((s.generation_mode||'r2va')!=='r2va'&&(videos.length||audios.length))errors.push('参考视频和音频当前仅支持R2VA模式');if((s.generation_mode||'r2va')==='fl2va'&&!s.continue_from_previous&&(s.references||[]).length<2)errors.push('FL2VA首段必须依次提供本镜首帧和尾帧');if(s.continue_from_previous&&!previousOutputName(s))errors.push('延续镜头缺少上一镜输出名称');if(!s.prompt.trim())errors.push('提示词不能为空');if(s.shot_card_needs_sync)errors.push('中文镜头卡已修改，请先同步英文 H3 提示词');s.status=errors.length?'invalid':'draft';s.error=errors.join('；');if(box)box.querySelector('.editor-message').textContent=errors.length?s.error:'验证通过（已合并公共层）';scheduleSave();return!errors.length}
async function submitShot(s,box=null,managedByBatch=false){if(batchScheduling&&!managedByBatch)throw new Error('批量生成进行中，请等待当前批次完成');if(!validateLocal(s,box)){render();throw new Error(s.error)}const effective=resolvedShot(s);s.status='queued';s.error='';scheduleSave();render();const previous=board.shots[board.shots.indexOf(s)-1];try{const d=await api('/api/submit',jsonOpt('POST',{references:effective.references,reference_videos:effective.reference_videos,reference_audios:effective.reference_audios,prompt:effective.prompt,director:normalizeDirector(s.director),duration:s.duration,seed:s.seed,output_name:s.output_name,resolution:board.advanced_settings.resolution,aspect_ratio:s.aspect_ratio,generation_mode:s.generation_mode,reference_image_size:s.reference_image_size==='max'?'max':'match',continue_from_previous:s.continue_from_previous,previous_output_name:previousOutputName(s),previous_comfy_url:previous?.comfy_url||'',will_be_continued:willBeContinued(s),save_latent:s.save_latent,turbo_lora_enabled:board.advanced_settings.turbo_lora_enabled,sage_attention_enabled:board.advanced_settings.sage_attention_enabled,face_swap_enabled:board.advanced_settings.face_swap_enabled===true,sampling_steps:board.advanced_settings.sampling_steps,audio_tail_carryover:s.audio_tail_carryover||'No Audio Carryover',audio_feather_ticks:Number.isInteger(s.audio_feather_ticks)?s.audio_feather_ticks:0}));s.resolution=board.advanced_settings.resolution;s.prompt_id=d.prompt_id;s.comfy_url=d.comfy_url;s.run_dir=d.run_dir;s.submitted_at=(d.submitted_at||Date.now()/1000);if(s.refine_job&&!['queued','running','syncing'].includes(s.refine_job.status))delete s.refine_job;s.estimated_seconds=d.estimated_seconds;s.estimated_remaining_seconds=d.estimated_seconds;s.started_at=null;await saveBoard();render();return d}catch(e){s.status='failed';s.error=e.message;render();await saveBoard();throw e}}
async function cancelShot(s,box=null){if(!s.prompt_id||!['queued','running'].includes(s.status))return false;if(!confirm(`确定取消“${s.title||s.id}”的生成任务吗？`))return false;try{const d=await api('/api/cancel/'+encodeURIComponent(s.prompt_id)+targetQuery(s.comfy_url),{method:'POST'});if(!d.cancelled){if(box)box.querySelector('.editor-message').textContent='任务已经结束，无需取消';await pollStatuses();return false}s.status='cancelled';s.error='';s.estimated_remaining_seconds=0;await saveBoard();render();return true}catch(e){s.error='取消失败：'+e.message;if(box)box.querySelector('.editor-message').textContent=s.error;await saveBoard();return false}}
async function waitForShot(s){while(['queued','running'].includes(s.status)){await new Promise(resolve=>setTimeout(resolve,1500));await pollStatuses()}if(s.status==='completed'&&!(s.results||[]).some(r=>r.prompt_id===s.prompt_id))await collectResults(s);return s.status}
async function waitForUpscales(){return}
async function cleanupBetweenShots(unloadModels=false,oomRecovery=false){return api('/api/memory/cleanup',jsonOpt('POST',{unload_models:unloadModels,oom_recovery:oomRecovery}))}
async function cleanupBetweenShotsSafely(){try{await cleanupBetweenShots(false);return true}catch(e){$('global-status').textContent='缓存清理失败，但不会中断批量生成：'+e.message;return false}}
async function preflightBatch(shots){const selected=new Set(shots),items=shots.map(s=>{const index=board.shots.indexOf(s),previous=index>0?board.shots[index-1]:null;return{id:s.id,output_name:s.output_name,continue_from_previous:Boolean(s.continue_from_previous),previous_output_name:previous?.output_name||'',previous_in_batch:Boolean(previous&&selected.has(previous))}}),result=await api('/api/batch/preflight',jsonOpt('POST',{shots:items}));if(!result.ok)throw new Error((result.errors||[]).join('；')||'批量生成 Latent 预检失败')}
async function submitMany(shots){if(batchScheduling){$('global-status').textContent='批量生成已经在提交中，请勿重复提交';return}if(!shots.length){$('global-status').textContent='没有选中任何分镜，请先勾选分镜或点击全选';return}if(hasActiveGeneration()){$('global-status').textContent='已有视频生成任务，请等待完成后再启动批量生成';return}batchScheduling=true;let submitted=0;try{await preflightBatch(shots);$('global-status').textContent=`正在把 ${shots.length} 个分镜交给 ComfyUI`;await waitForUpscales();for(let index=0;index<shots.length;index++){const s=shots[index];try{$('global-status').textContent=`正在排队 ${s.id}（${index+1}/${shots.length}）`;await submitShot(s,null,true);submitted++}catch(e){s.status='failed';s.error=e.message;await saveBoard();$('global-status').textContent=`${s.id} 提交失败，已提交 ${submitted}/${shots.length}：${e.message}`;break}}if(submitted===shots.length)$('global-status').textContent=`${submitted} 个分镜已全部进入 ComfyUI 队列，锁屏也会继续`}catch(e){$('global-status').textContent='无法启动批量生成：'+e.message}finally{batchScheduling=false;await refreshComfyQueue();pollStatuses()}}
function activeComfyQuery(){return board.advanced_settings.generation_target==='remote'?targetQuery(board.advanced_settings.comfy_url):''}
async function refreshComfyQueue(){try{const d=await api('/api/queue'+activeComfyQuery());comfyQueue=d.jobs||[];renderQueueSidebar()}catch(_e){}}
async function pollStatuses(){if(polling)return;polling=true;let stateChanged=false,dataChanged=false;try{for(const s of board.shots.filter(x=>x.prompt_id&&['queued','running','syncing','failed'].includes(x.status))){try{const d=await api('/api/task-status/'+s.prompt_id+targetQuery(s.comfy_url)),next=d.status;if(next!==s.status){s.status=next;stateChanged=true;dataChanged=true}if(d.error&&s.error!==d.error){s.error=d.error;dataChanged=true;updateEditorMessage(s,d.error)}if(next==='running'&&!s.started_at){s.started_at=Date.now()/1000;dataChanged=true}if(Number.isFinite(d.estimated_remaining_seconds)){s.estimated_remaining_seconds=d.estimated_remaining_seconds;s.eta_source=d.eta_source;s.progress_percent=d.progress_percent;dataChanged=true}else if(next==='running'&&s.estimated_seconds){s.estimated_remaining_seconds=Math.max(0,s.estimated_seconds-(Date.now()/1000-s.started_at));dataChanged=true}else if(next==='queued'&&s.estimated_seconds){s.estimated_remaining_seconds=s.estimated_seconds}if(next==='completed'){s.estimated_remaining_seconds=0;await collectResults(s)}}catch(e){if(s.error!==e.message){s.error=e.message;dataChanged=true;updateEditorMessage(s,e.message)}}}for(const s of board.shots.filter(x=>x.prompt_id&&x.status==='completed'&&!(x.results||[]).some(r=>r.prompt_id===x.prompt_id)))await collectResults(s);if(dataChanged)scheduleSave();if(stateChanged)render();else refreshStatusCells()}finally{polling=false}}
async function pollRefines(){for(const s of board.shots.filter(x=>x.refine_job?.prompt_id&&(['queued','running','syncing'].includes(x.refine_job.status)||(x.refine_job.status==='failed'&&String(x.refine_job.error||'').includes('不在 ComfyUI 队列或历史记录中'))))){try{const job=s.refine_job,d=await api('/api/task-status/'+job.prompt_id+targetQuery(job.comfy_url));job.status=d.status;job.error=d.error||'';if(d.status==='completed'){s.prompt_id=job.prompt_id;s.comfy_url=job.comfy_url;s.resolution=job.target_resolution;s.status='syncing';render();await saveBoard();await collectResults(s)}else{if(d.status==='syncing')s.status='syncing';scheduleSave();render()}}catch(e){s.refine_job.error=e.message;scheduleSave()}}}
async function openOutput(){const d=await api('/api/output-dir');await api('/api/open-path',jsonOpt('POST',{path:d.path}))}

$('storyboard-body').onclick=e=>{const row=e.target.closest('.shot-row');if(!row)return;const i=Number(row.dataset.i),s=board.shots[i];if(e.target.classList.contains('select-shot')){s.selected=e.target.checked;scheduleSave();return}if(e.target.classList.contains('copy')){board.shots.splice(i+1,0,newShot(s));expanded=i+1;scheduleSave();render();return}expanded=expanded===i?-1:i;render()};
$('queue-list').onclick=async e=>{
  const locate=e.target.dataset.queueLocate,promptCancel=e.target.dataset.promptCancel;
  if(locate!==undefined){
    const i=Number(locate);expanded=i;render();
    requestAnimationFrame(()=>document.querySelector(`#storyboard-body .shot-row[data-i="${i}"]`)?.scrollIntoView({behavior:'smooth',block:'center'}));
    return;
  }
  if(promptCancel!==undefined&&confirm('确定取消这个 ComfyUI 任务吗？')){await api('/api/cancel/'+encodeURIComponent(promptCancel)+activeComfyQuery(),{method:'POST'});await refreshComfyQueue();await pollStatuses()}
};
$('queue-toggle').onclick=()=>setQueueCollapsed(!$('queue-sidebar').classList.contains('collapsed'));
$('queue-cancel-all').onclick=async()=>{const count=comfyQueue.filter(job=>job.prompt_id).length,target=board.advanced_settings.generation_target==='remote'?'云端':'本地';if(!count||!confirm(`确定取消${target}设备上的全部 ${count} 个运行中和排队任务吗？已完成的视频不会删除。`))return;const button=$('queue-cancel-all');button.disabled=true;button.textContent='取消中…';try{const d=await api('/api/queue/cancel-all'+activeComfyQuery(),{method:'POST'});$('global-status').textContent=d.failed?.length?`已取消 ${d.cancelled}/${d.requested} 个任务，${d.failed.length} 个取消失败`:`已取消${target}设备上的 ${d.cancelled} 个任务`;await loadBoard();await refreshComfyQueue()}catch(e){$('global-status').textContent='全部取消失败：'+e.message}finally{button.textContent='全部取消';renderQueueSidebar()}};
setQueueCollapsed(localStorage.getItem('ref2va.queueCollapsed')==='1',false);
$('preview-sidebar-toggle').onclick=()=>setPreviewSidebarState(!$('preview-sidebar').classList.contains('collapsed'),$('preview-sidebar').classList.contains('enlarged'));
$('preview-size-toggle').onclick=()=>setPreviewSidebarState(false,!$('preview-sidebar').classList.contains('enlarged'));
setPreviewSidebarState(localStorage.getItem('ref2va.previewCollapsed')==='1',localStorage.getItem('ref2va.previewEnlarged')==='1',false);
$('add-shot').onclick=()=>{board.shots.push(newShot());expanded=board.shots.length-1;scheduleSave();render()};
$('toggle-select-all').onchange=e=>{const selectAll=e.target.checked;board.shots.forEach(s=>{s.selected=selectAll});scheduleSave();render()};
$('new-storyboard').onclick=async()=>{if(!confirm('确定新建故事板吗？当前故事板内容会被清空，已生成的视频文件不会删除。'))return;clearTimeout(saveTimer);board={name:'未命名项目',shots:[]};board.shared=normalizeShared();board.advanced_settings=normalizeAdvancedSettings();board.shots=[newShot()];expanded=-1;continuousFailures.clear();$('project-name').value=board.name;syncAdvancedSettingsUI();syncSourceUI();render();await saveBoard()};
$('duplicate-shot').onclick=()=>{const i=expanded>=0?expanded:Math.max(0,board.shots.findIndex(s=>s.selected));board.shots.splice(i+1,0,newShot(board.shots[i]));expanded=i+1;scheduleSave();render()};
$('delete-selected').onclick=()=>{board.shots=board.shots.filter(s=>!s.selected);if(!board.shots.length)board.shots.push(newShot());expanded=-1;scheduleSave();render()};
$('submit-selected').onclick=async()=>{await submitMany(board.shots.filter(s=>s.selected))};$('submit-all').onclick=async()=>{await submitMany(board.shots)};$('project-name').oninput=scheduleSave;
$('shared-enabled').onchange=e=>{board.shared=normalizeShared(board.shared);board.shared.enabled=e.target.checked;scheduleSave();render()};$('shared-prompt').oninput=e=>{board.shared=normalizeShared(board.shared);board.shared.prompt=e.target.value;scheduleSave()};
$('turbo-lora-enabled').onchange=e=>{board.advanced_settings.turbo_lora_enabled=e.target.checked;scheduleSave()};$('sage-attention-enabled').onchange=e=>{board.advanced_settings.sage_attention_enabled=e.target.checked;scheduleSave()};$('face-swap-enabled').onchange=e=>{board.advanced_settings.face_swap_enabled=e.target.checked;scheduleSave()};$('sampling-steps').onchange=e=>{board.advanced_settings.sampling_steps=Math.max(1,Math.min(100,Number.parseInt(e.target.value,10)||8));e.target.value=board.advanced_settings.sampling_steps;scheduleSave()};$('global-resolution').onchange=e=>{board.advanced_settings.resolution=e.target.value;board.shots.forEach(s=>{s.resolution=e.target.value;if(s.status!=='completed')s.status='draft'});scheduleSave();render()};$('refine-target-resolution').onchange=e=>{board.advanced_settings.refine_target_resolution=e.target.value;scheduleSave()};
$('generation-target').onchange=async e=>{board.advanced_settings.generation_target=e.target.value==='remote'?'remote':'local';syncAdvancedSettingsUI();await saveBoard();await health();await refreshComfyQueue();$('global-status').textContent=`已切换到${board.advanced_settings.generation_target==='remote'?'云端':'本地'}；其他设备上的任务仍会继续追踪和回传`};
$('comfy-url').onchange=async e=>{let value;try{value=normalizeComfyInput(e.target.value)}catch{e.target.value=board.advanced_settings.comfy_url;$('global-status').textContent='云端 IP 格式无效，例如 192.168.11.103:8188';return}board.advanced_settings.comfy_url=value;e.target.value=value;await saveBoard();await health(false,value)};
$('test-comfy-connection').onclick=async()=>{let value;try{value=normalizeComfyInput($('comfy-url').value)}catch{$('global-status').textContent='云端 IP 格式无效，例如 192.168.11.103:8188';return}clearTimeout(saveTimer);board.advanced_settings.comfy_url=value;$('comfy-url').value=value;await saveBoard();await health(true,value)};
$('refine-selected').onclick=refineSelected;
$('import-json').onclick=async()=>{
  const open=$('import-json');open.disabled=true;
  try{
    clearTimeout(saveTimer);await saveBoard();
    let path='';
    try{const picked=await api('/api/pick-json',{method:'POST'});path=String(picked?.path||'');if(!path)return}
    catch(e){path=(prompt('请输入故事板 JSON 的完整路径（留空取消）',String(board.source_json_path||''))||'').trim()}
    if(!path)return;
    clearTimeout(saveTimer);await saveBoard();
    $('global-status').textContent='正在打开 JSON…';
    const r=await api('/api/storyboard/source-file',jsonOpt('POST',{path,import_now:true}));
    board=r.project;board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);board.shared=normalizeShared(board.shared);expanded=-1;
    $('project-name').value=board.name||'未命名项目';syncAdvancedSettingsUI();syncSourceUI();render();
    const recovered=r.recovered_results?` · 已恢复 ${r.recovered_results} 个视频结果`:'';
    $('global-status').textContent=r.mirror_error?`已打开 ${baseName(path)}${recovered} · 源文件保存失败：${r.mirror_error}`:`已打开 ${baseName(path)}${recovered} · 修改将自动保存到该文件`;
  }catch(e){$('global-status').textContent='打开失败：'+e.message}
  finally{open.disabled=false}
};
$('import-director-pack').onclick=()=>$('director-pack-file').click();$('director-pack-file').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;const form=new FormData();form.append('pack',file,file.name);try{$('global-status').textContent='正在安全校验并转换 Director 包…';const preview=await api('/api/storyboard/import-director-pack',{method:'POST',body:form}),lines=[`将导入 ${preview.summary.shots} 个 ${String(preview.summary.mode).toUpperCase()} 镜头`,preview.summary.shared_references?`公共图片：${preview.summary.shared_references} 张`:'无公共图片',...(preview.warnings||[])];if(!confirm(lines.join('\n\n')+'\n\n确认替换当前故事板吗？')){$('global-status').textContent='已取消 Director 包导入';return}await saveBoard();const restored=await api('/api/storyboard/import',jsonOpt('POST',{project:preview.project}));board=restored.project;board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);board.shared=normalizeShared(board.shared);expanded=-1;$('project-name').value=board.name||'Director 导入';syncAdvancedSettingsUI();syncSourceUI();render();$('global-status').textContent=`已导入 Director 包：${preview.summary.shots} 个镜头。请先检查公共层和最终引用编号，再提交。`}catch(err){$('global-status').textContent='Director 包导入失败：'+err.message}finally{e.target.value=''}};
$('import-video-analyzer').onclick=async()=>{try{const shared=normalizeShared(board.shared);if(shared.enabled&&(shared.references.length||shared.reference_videos.length||shared.reference_audios.length))throw new Error('请先关闭公共参考层，再导入视频分析草稿，以免 Picture/Video/Audio 编号错位');const directory=prompt('输入 VideoAnalyzer 分析目录的本机绝对路径（目录内应有 prompt.txt 和 keyframes/shot_N.jpg）');if(!directory?.trim())return;const referenceVideo=prompt('输入原参考视频的本机绝对路径；暂时没有可留空，之后在镜头编辑器补充。')||'';const preview=await api('/api/storyboard/preview-video-analyzer',jsonOpt('POST',{directory:directory.trim(),reference_video:referenceVideo.trim()}));const shot=preview.shot,lines=[`追加 1 个可编辑 R2VA 草稿镜头`,`${shot.references.length} 张逐镜参考帧 · ${shot.reference_videos.length} 段参考视频`,...(preview.warnings||[])];if(!confirm(lines.join('\n\n')+'\n\n确认追加到当前故事板吗？'))return;await saveBoard();if(board.shots.some(s=>s.id===shot.id||s.output_name===shot.output_name))throw new Error('草稿 ID 冲突，请重试');board.shots.push({...newShot(),...shot,resolution:board.advanced_settings.resolution||'0.4mp'});expanded=board.shots.length-1;await saveBoard();render();$('global-status').textContent='已追加 VideoAnalyzer 草稿；请核对标签、素材、时长和原声后再生成。'}catch(err){$('global-status').textContent='视频分析草稿导入失败：'+err.message}};
$('preview-restart').onclick=restartContinuous;
$('preview-prev').onclick=()=>advanceContinuous(-1,true);
$('preview-next').onclick=()=>advanceContinuous(1,true);
$('image-preview-close').onclick=()=>$('image-preview-dialog').close();
$('image-preview-dialog').onclick=e=>{if(e.target===$('image-preview-dialog'))e.target.close()};
document.body.ondblclick=e=>{const image=e.target.closest('[data-preview-path]');if(!image)return;e.preventDefault();e.stopPropagation();openImagePreview(image.dataset.previewPath)};
async function health(showResult=false,explicitUrl=''){const pill=$('health'),remote=board.advanced_settings?.generation_target==='remote',target=remote?'云端':'本地',configuredUrl=explicitUrl||(remote?board.advanced_settings.comfy_url:'http://127.0.0.1:8188');try{const d=await api('/api/health'+targetQuery(explicitUrl));if(!d.ok)throw new Error(d.error||'未连接');const connectedUrl=d.comfy_url||configuredUrl;pill.textContent=`${target} ComfyUI 已连接`;pill.className='pill ok';pill.title=connectedUrl;if(showResult)$('global-status').textContent=`连接成功：${connectedUrl}`}catch(e){pill.textContent=`${target} ComfyUI 未连接`;pill.className='pill bad';pill.title=e.message;if(showResult)$('global-status').textContent=`连接失败：${e.message}`}}
function cleanLogText(value){return String(value||'').replace(/\x1b\[[0-?]*[ -\/]*[@-~]/g,'').replace(/\r(?!\n)/g,'\n')}
function logLevel(line){const match=line.match(/^\s*\[(DEBUG|DETAIL|INFO|WARNING|ERROR|CRITICAL)\]/i);return match?match[1].toLowerCase():''}
async function refreshComfyLogs(){if(!$('comfy-log-panel').open)return;const state=$('comfy-log-state');state.textContent='正在刷新…';const explicit=board.advanced_settings?.generation_target==='remote'?board.advanced_settings.comfy_url:'';try{const d=await api('/api/comfy-logs'+targetQuery(explicit));if(!d.ok)throw new Error(d.error||'无法读取日志');const entries=(d.entries||[]).filter(entry=>Date.parse(entry.t||0)>=comfyLogClearedAt),text=cleanLogText(entries.map(entry=>entry.m||'').join('')),lines=text.split('\n'),output=$('comfy-log-output');output.replaceChildren(...(lines.some(Boolean)?lines.map(line=>{const node=document.createElement('div');node.className='log-line '+logLevel(line);node.textContent=line||' ';return node}):[Object.assign(document.createElement('div'),{className:'log-placeholder',textContent:'当前还没有日志。'})]));$('comfy-log-source').textContent=d.comfy_url||'ComfyUI';state.textContent=`${entries.length} 条 · ${new Date().toLocaleTimeString()}`;if($('comfy-log-follow').checked)output.scrollTop=output.scrollHeight}catch(e){state.textContent='读取失败';$('comfy-log-source').textContent=e.message}}
$('comfy-log-panel').ontoggle=()=>{clearInterval(comfyLogTimer);comfyLogTimer=null;if($('comfy-log-panel').open){refreshComfyLogs();comfyLogTimer=setInterval(refreshComfyLogs,2000)}};
$('comfy-log-refresh').onclick=refreshComfyLogs;
$('comfy-log-clear').onclick=()=>{comfyLogClearedAt=Date.now();$('comfy-log-output').innerHTML='<div class="log-placeholder">显示已清空；新的 ComfyUI 日志会继续出现。</div>';$('comfy-log-state').textContent='显示已清空'};
loadBoard();health();refreshComfyQueue();refreshDeviceStats();setInterval(()=>{health();pollStatuses();pollRefines();refreshComfyQueue();refreshDeviceStats()},5000);
