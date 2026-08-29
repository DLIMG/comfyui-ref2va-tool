const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let board={name:'未命名项目',advanced_settings:{turbo_lora_enabled:true,sage_attention_enabled:true,sampling_steps:8,resolution:'0.4mp',auto_upscale_enabled:false,upscale_resolution:'720p',generation_target:'local',comfy_url:'http://192.168.11.103:8188'},shots:[]},expanded=-1,saveTimer=null,polling=false;
let continuousItems=[],continuousIndex=0,continuousFailures=new Set();
let continuousPlaybackStarted=false;
let continuousMediaHandlers=null;
let continuousStandby=null;
const collecting=new Set();
const statusText={draft:'待配置',invalid:'验证失败',queued:'排队中',running:'生成中',completed:'已完成',failed:'失败',cancelled:'已取消'};
const aspectText={'16:9':'16:9 横屏','9:16':'9:16 竖屏','4:3':'4:3 横屏','3:4':'3:4 竖屏','1:1':'1:1 方形'};

function normalizeAdvancedSettings(value){const steps=Number.parseInt(value?.sampling_steps,10);return{turbo_lora_enabled:value?.turbo_lora_enabled!==false,sage_attention_enabled:value?.sage_attention_enabled!==false,sampling_steps:Number.isInteger(steps)&&steps>=1&&steps<=100?steps:8,resolution:value?.resolution||'0.4mp',auto_upscale_enabled:value?.auto_upscale_enabled===true,upscale_resolution:['720p','1080p'].includes(value?.upscale_resolution)?value.upscale_resolution:'720p',generation_target:value?.generation_target==='remote'?'remote':'local',comfy_url:String(value?.comfy_url||'http://192.168.11.103:8188').replace(/\/$/,'')}}
function syncAdvancedSettingsUI(){board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);$('turbo-lora-enabled').checked=board.advanced_settings.turbo_lora_enabled;$('sage-attention-enabled').checked=board.advanced_settings.sage_attention_enabled;$('sampling-steps').value=board.advanced_settings.sampling_steps;$('global-resolution').value=board.advanced_settings.resolution;$('auto-upscale-enabled').checked=board.advanced_settings.auto_upscale_enabled;$('upscale-resolution').value=board.advanced_settings.upscale_resolution;$('generation-target').value=board.advanced_settings.generation_target;$('comfy-url').value=board.advanced_settings.comfy_url;$('remote-comfy-row').hidden=board.advanced_settings.generation_target!=='remote'}
const targetQuery=value=>value?'?comfy_url='+encodeURIComponent(value):'';

function newShot(copy=null){
  const n=board.shots.length+1,id=String(n).padStart(2,'0')+'A';
  const base=copy?JSON.parse(JSON.stringify(copy)):{references:[],prompt:'',duration:6,seed:Date.now()%2147483647,resolution:board.advanced_settings.resolution||'0.4mp',aspect_ratio:'16:9',generation_mode:'r2va',continue_from_previous:false,save_latent:false,audio_tail_carryover:'Full Previous Tail',audio_feather_ticks:0,results:[]};
  return{...base,id,title:copy?copy.title+' 副本':'新片段',output_name:id+'_新片段',selected:false,status:'draft',prompt_id:'',run_dir:'',error:'',results:copy?[]:(base.results||[])};
}
async function api(url,opt={}){const r=await fetch(url,opt),text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch{d={detail:text}}if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);return d}
const jsonOpt=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
async function loadBoard(){
  board=await api('/api/storyboard');
  board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);
  if(!board.shots.length)board.shots.push(newShot());
  board.shots=board.shots.map(s=>({...newShot(),...s,references:[...(s.references||[])],results:[...(s.results||[])],resolution:s.resolution||'480p',aspect_ratio:s.aspect_ratio||'16:9',generation_mode:s.generation_mode||'r2va',continue_from_previous:Boolean(s.continue_from_previous),save_latent:Boolean(s.save_latent),audio_tail_carryover:s.audio_tail_carryover||'Full Previous Tail',audio_feather_ticks:Number.isInteger(s.audio_feather_ticks)?s.audio_feather_ticks:0}));
  $('project-name').value=board.name;syncAdvancedSettingsUI();render();pollStatuses();pollUpscales();
}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(saveBoard,500)}
async function saveBoard(){board.name=$('project-name').value.trim()||'未命名项目';board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);await api('/api/storyboard',jsonOpt('PUT',board));$('global-status').textContent='故事板已保存 '+new Date().toLocaleTimeString()}
function promptSummary(p){return(p||'').split(/\r?\n/).find(x=>x.trim()&&!x.endsWith(':'))||'未填写'}
function formatRemaining(seconds){if(!Number.isFinite(seconds))return'';seconds=Math.max(0,Math.ceil(seconds));const m=Math.floor(seconds/60),s=seconds%60;return m?`${m}分${String(s).padStart(2,'0')}秒`:`${s}秒`}
function statusLabel(s){const base=statusText[s.status]||s.status;if(!['queued','running'].includes(s.status))return base;const eta=formatRemaining(Number(s.estimated_remaining_seconds)),live=String(s.eta_source||'').includes('live_sampling')?'·采样实测':'';return eta?`${base}·剩余约${eta}${live}`:base}
function refreshStatusCells(){document.querySelectorAll('#storyboard-body .shot-row').forEach(row=>{const s=board.shots[Number(row.dataset.i)],cell=row.querySelector('.status');if(s&&cell){cell.textContent=statusLabel(s);cell.className='status '+s.status}});renderQueueSidebar()}
function renderQueueSidebar(){const sidebar=$('queue-sidebar'),list=$('queue-list'),active=board.shots.map((s,i)=>({s,i})).filter(({s})=>['running','queued'].includes(s.status)).sort((a,b)=>(a.s.status==='running'?-1:0)-(b.s.status==='running'?-1:0)||a.i-b.i);sidebar.classList.toggle('has-items',active.length>0);$('queue-count').textContent=`${active.length} 个`;list.innerHTML=active.map(({s,i},position)=>{const progress=Number.isFinite(Number(s.progress_percent))?Math.max(0,Math.min(100,Number(s.progress_percent))):0;return`<article class="queue-item ${esc(s.status)}"><div class="queue-item-top"><b>#${position+1} · ${esc(s.id)}</b><span class="status ${esc(s.status)}">${esc(statusText[s.status]||s.status)}</span></div><div class="queue-item-title">${esc(s.title||'未命名分镜')}</div><div class="queue-item-meta">${esc(statusLabel(s))}</div>${s.status==='running'?`<div class="queue-progress" title="${progress}%"><span style="width:${progress}%"></span></div>`:''}<div class="queue-item-actions"><button data-queue-locate="${i}">定位</button><button class="danger" data-queue-cancel="${i}">取消</button></div></article>`}).join('')}
function setQueueCollapsed(collapsed,persist=true){const sidebar=$('queue-sidebar'),toggle=$('queue-toggle');sidebar.classList.toggle('collapsed',collapsed);document.body.classList.toggle('queue-collapsed',collapsed);toggle.setAttribute('aria-expanded',String(!collapsed));toggle.textContent=collapsed?'展开队列':'收起';toggle.title=collapsed?'展开生成队列':'收起生成队列';if(persist)localStorage.setItem('ref2va.queueCollapsed',collapsed?'1':'0')}
function render(){
  const body=$('storyboard-body');body.innerHTML='';
  board.shots.forEach((s,i)=>{
    const tr=document.createElement('tr');tr.className='shot-row '+(i===expanded?'active':'');tr.dataset.i=i;
    const thumbs=(s.references||[]).slice(0,3).map(p=>`<img src="/api/file-preview?path=${encodeURIComponent(p)}" data-preview-path="${esc(p)}" title="双击查看大图">`).join('')+((s.references||[]).length>3?`<span class="more">+${s.references.length-3}</span>`:'');
    tr.innerHTML=`<td><input class="select-shot" type="checkbox" aria-label="选择片段 ${esc(s.id)}" ${s.selected?'checked':''}></td><td class="shot-id">${esc(s.id)}</td><td>${esc(s.title)}</td><td><div class="thumbs">${thumbs||'—'}</div></td><td><div class="summary" title="${esc(promptSummary(s.prompt))}">${esc(promptSummary(s.prompt))}</div></td><td>${esc((s.resolution||'480p').toUpperCase())} · ${esc(aspectText[s.aspect_ratio]||s.aspect_ratio)}</td><td>${esc(s.duration)}秒</td><td>${esc(s.seed)}</td><td><span class="status ${esc(s.status)}">${esc(statusLabel(s))}</span></td><td>${(s.results||[]).length} 个</td><td><button class="edit">编辑</button> <button class="copy">复制</button></td>`;
    body.appendChild(tr);if(i===expanded)body.appendChild(makeEditorRow(s,i));
  });
  refreshContinuousPreview();
  renderQueueSidebar();
  const allSelected=board.shots.length>0&&board.shots.every(s=>s.selected);
  $('toggle-select-all').textContent=allSelected?'全不选':'全选';
  $('toggle-select-all').setAttribute('aria-pressed',String(allSelected));
}
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
  box.querySelector('.edit-id').value=s.id;box.querySelector('.edit-title').value=s.title;box.querySelector('.edit-output').value=s.output_name;box.querySelector('.edit-prompt').value=s.prompt;box.querySelector('.edit-duration').value=s.duration;box.querySelector('.edit-seed').value=s.seed;box.querySelector('.edit-resolution').value=s.resolution;box.querySelector('.edit-aspect').value=s.aspect_ratio;box.querySelector('.edit-generation-mode').value=s.generation_mode||'r2va';
  const continuation=box.querySelector('.edit-continuation');if(shotIndex===0)s.continue_from_previous=false;continuation.checked=Boolean(s.continue_from_previous);continuation.disabled=shotIndex===0;
  const saveLatent=box.querySelector('.edit-save-latent');saveLatent.checked=Boolean(s.save_latent)||willBeContinued(s);saveLatent.disabled=willBeContinued(s);saveLatent.title=willBeContinued(s)?'下一镜需要延续，必须保存':'保存当前分镜的 AV Latent，供后续镜头使用';
  renderRefs(box,s);renderResults(box,s);box.querySelector('.editor-message').textContent=s.error||'';
  [['id','id'],['title','title'],['output','output_name']].forEach(([c,k])=>box.querySelector('.edit-'+c).oninput=e=>{s[k]=e.target.value;scheduleSave()});
  box.querySelector('.edit-prompt').oninput=e=>{s.prompt=e.target.value;s.status='draft';scheduleSave()};
  box.querySelector('.edit-duration').oninput=e=>{s.duration=Number(e.target.value);scheduleSave()};
  box.querySelector('.edit-seed').oninput=e=>{s.seed=Number(e.target.value);scheduleSave()};
  box.querySelector('.edit-resolution').onchange=e=>{s.resolution=e.target.value;s.status='draft';scheduleSave();render()};
  box.querySelector('.edit-aspect').onchange=e=>{s.aspect_ratio=e.target.value;s.status='draft';scheduleSave();render()};
  box.querySelector('.edit-generation-mode').onchange=e=>{s.generation_mode=e.target.value;s.status='draft';scheduleSave();render()};
  continuation.onchange=e=>{s.continue_from_previous=e.target.checked;if(e.target.checked&&shotIndex>0)board.shots[shotIndex-1].save_latent=true;s.status='draft';scheduleSave();render()};
  saveLatent.onchange=e=>{s.save_latent=e.target.checked;s.status='draft';scheduleSave();render()};
  const input=box.querySelector('.image-input'),drop=box.querySelector('.image-drop-zone');
  box.querySelector('.pick-images').onclick=e=>{e.stopPropagation();input.click()};drop.onclick=()=>input.click();
  drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click()}};
  input.onchange=async()=>{await uploadImages(input.files,s,box);input.value=''};
  ['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();drop.classList.add('dragover')}));
  ['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();e.stopPropagation();drop.classList.remove('dragover')}));
  drop.addEventListener('drop',e=>uploadImages(e.dataTransfer.files,s,box));
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
function renderRefs(box,s){
  const mode=s.generation_mode||'r2va',continued=Boolean(s.continue_from_previous),guidance=box.querySelector('.reference-guidance');
  guidance.textContent=mode==='r2va'?'全部图片按顺序作为 <Picture N>；可与上一镜 Latent 同时使用。':continued?'第1张为新尾帧，其余为 Qwen 参考图；开头来自上一镜 Latent。':'第1张首帧，第2张尾帧，其余为 Qwen 参考图。';
  const label=n=>mode==='r2va'?`<Picture ${n+1}>`:continued?(n===0?'尾帧':`Qwen参考 ${n}`):(n===0?'首帧':n===1?'尾帧':`Qwen参考 ${n-1}`);
  const list=box.querySelector('.reference-list');list.innerHTML=s.references.map((p,n)=>`<div class="ref-card"><img src="/api/file-preview?path=${encodeURIComponent(p)}" data-preview-path="${esc(p)}" title="双击查看大图"><b>${esc(label(n))}</b><small title="${esc(p)}">${esc(p)}</small><div class="ref-actions"><button data-move="-1" data-n="${n}">←</button><button data-move="1" data-n="${n}">→</button><button data-remove="${n}">删</button></div></div>`).join('')||'<span>尚未选择参考图</span>';
  list.onclick=e=>{const n=Number(e.target.dataset.n);let changed=false;if(e.target.dataset.move){const to=n+Number(e.target.dataset.move);if(to>=0&&to<s.references.length){[s.references[n],s.references[to]]=[s.references[to],s.references[n]];changed=true}}else if(e.target.dataset.remove!==undefined){s.references.splice(Number(e.target.dataset.remove),1);changed=true}if(changed){s.status='draft';scheduleSave();render()}};
}
function openImagePreview(path){
  const dialog=$('image-preview-dialog'),image=$('image-preview-full');
  image.src='/api/file-preview?path='+encodeURIComponent(path);image.alt=path;
  if(!dialog.open)dialog.showModal();
}
function renderResults(box,s){
  const results=[...(s.results||[])].reverse(),list=box.querySelector('.result-list');
  box.querySelector('.result-summary').textContent=results.length?`共 ${results.length} 个，全部保留`:'尚无已收集结果';
  list.innerHTML=results.map(r=>{const up=r.upscale||{},busy=['queued','running'].includes(up.status),target=(board.advanced_settings.upscale_resolution||'720p').toUpperCase(),done=r.kind==='upscaled';const label=busy?'高清处理中…':up.status==='failed'?`重新放大到${target}`:`放大到${target}`;return`<article class="result-card"><video controls preload="metadata" src="/api/results/video/${encodeURIComponent(s.id)}/${encodeURIComponent(r.id)}"></video><b>${esc(r.filename||'生成视频')}</b><div class="result-meta"><span>${esc(formatTime(r.created_at))}</span><span>${esc(r.kind==='upscaled'?'高清·'+(r.resolution||target):(r.status||'ready'))}</span></div><div class="result-actions">${done?'':`<button data-upscale-result="${esc(r.id)}" ${busy?'disabled':''}>${esc(label)}</button>`}<button data-open-result="${esc(r.id)}">打开目录</button><button class="danger" data-delete-result="${esc(r.id)}">永久删除</button></div>${up.error?`<small class="result-error">${esc(up.error)}</small>`:''}</article>`}).join('')||'<span>视频生成完成后会自动出现在这里。</span>';
  list.onclick=async e=>{const upscaleId=e.target.dataset.upscaleResult,openId=e.target.dataset.openResult,deleteId=e.target.dataset.deleteResult;if(upscaleId)await submitUpscale(s,upscaleId,box);if(openId){const result=s.results.find(x=>x.id===openId);if(result)await api('/api/open-path',jsonOpt('POST',{path:result.path}))}if(deleteId){const result=s.results.find(x=>x.id===deleteId);if(!result||!confirm(`确定永久删除“${result.filename||'这个视频'}”吗？此操作无法恢复。`))return;try{const d=await api(`/api/results/${encodeURIComponent(s.id)}/${encodeURIComponent(deleteId)}`,{method:'DELETE'});s.results=d.results;render()}catch(err){box.querySelector('.editor-message').textContent='删除失败：'+err.message}}};
}
let batchScheduling=false;
function hasActiveGeneration(){return board.shots.some(s=>['queued','running'].includes(s.status))}
function hasActiveUpscale(){return board.shots.some(s=>(s.results||[]).some(r=>['queued','running'].includes(r.upscale?.status)))}
async function submitUpscale(s,resultId,box=null){const result=s.results.find(x=>x.id===resultId);if(!result)return false;const target=board.advanced_settings.upscale_resolution||'720p';if(batchScheduling||hasActiveGeneration()){if(box)box.querySelector('.editor-message').textContent='视频生成进行中，完成后才能提交高清放大';return false}result.upscale={status:'queued',target_resolution:target,error:''};render();try{const d=await api('/api/results/upscale',jsonOpt('POST',{shot_id:s.id,result_id:resultId,target_resolution:target}));result.upscale=d.upscale;render();return true}catch(e){result.upscale={status:'failed',target_resolution:target,error:e.message};if(box)box.querySelector('.editor-message').textContent='高清放大提交失败：'+e.message;render();return false}}
let upscaleAllScheduling=false;
function pendingUpscaleResults(target){const items=[];for(const s of board.shots){const results=s.results||[];for(const result of results){if(result.kind==='upscaled'||['queued','running'].includes(result.upscale?.status))continue;const alreadyDone=results.some(item=>item.kind==='upscaled'&&item.source_result_id===result.id&&(item.resolution||'').toLowerCase()===target);if(!alreadyDone)items.push({shot:s,result})}}return items}
async function submitAllUpscales(){if(upscaleAllScheduling){$('global-status').textContent='一键高清放大正在提交中';return}if(batchScheduling||hasActiveGeneration()){$('global-status').textContent='视频生成进行中，完成后才能一键放大全部';return}const target=(board.advanced_settings.upscale_resolution||'720p').toLowerCase(),items=pendingUpscaleResults(target);if(!items.length){$('global-status').textContent=`所有原始结果都已有 ${target.toUpperCase()} 高清版本`;return}upscaleAllScheduling=true;const button=$('upscale-all-results');button.disabled=true;let submitted=0;try{for(let index=0;index<items.length;index++){const {shot,result}=items[index];$('global-status').textContent=`正在提交高清放大 ${index+1}/${items.length}：${shot.id}`;if(await submitUpscale(shot,result.id))submitted++}$('global-status').textContent=`一键高清放大已提交 ${submitted}/${items.length} 个结果到 ${target.toUpperCase()}`}finally{upscaleAllScheduling=false;button.disabled=false}}
async function submitPendingAutoUpscales(){if(!board.advanced_settings.auto_upscale_enabled||batchScheduling||hasActiveGeneration()||hasActiveUpscale())return;for(const s of board.shots){const result=(s.results||[]).find(r=>r.kind!=='upscaled'&&!r.upscale);if(result){$('global-status').textContent=`正在自动高清放大 ${s.id} 到 ${board.advanced_settings.upscale_resolution.toUpperCase()}`;await submitUpscale(s,result.id);return}}}
async function pollUpscales(){let changed=false;for(const s of board.shots){for(const r of(s.results||[])){const up=r.upscale;if(!up?.prompt_id||!['queued','running','failed'].includes(up.status))continue;try{const d=await api('/api/task-status/'+up.prompt_id+targetQuery(up.comfy_url));up.status=d.status;if(d.status==='completed'){const collected=await api('/api/results/upscale/collect',jsonOpt('POST',{shot_id:s.id,result_id:r.id,target_resolution:up.target_resolution||'720p'}));s.results=collected.results}changed=true}catch(e){up.error=e.message;changed=true}}}if(changed){scheduleSave();render()}}
function formatTime(value){if(!value)return'未知时间';const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString()}
function updateEditorMessage(s,message){if(expanded!==board.shots.indexOf(s))return;const node=document.querySelector('#storyboard-body .editor-row .editor-message');if(node)node.textContent=message}
async function collectResults(s){
  if(!s.prompt_id||collecting.has(s.id))return;
  if((s.results||[]).some(r=>r.prompt_id===s.prompt_id))return;
  collecting.add(s.id);
  try{const d=await api('/api/results/collect',jsonOpt('POST',{shot_id:s.id}));s.results=d.results;s.status='completed';s.error='';scheduleSave();render()}catch(e){const message='结果收集：'+e.message;if(s.error!==message){s.error=message;updateEditorMessage(s,message);scheduleSave()}}finally{collecting.delete(s.id)}
}
function previousOutputName(s){const index=board.shots.indexOf(s);return index>0?String(board.shots[index-1].output_name||''):''}
function willBeContinued(s){const index=board.shots.indexOf(s);return index>=0&&index<board.shots.length-1&&Boolean(board.shots[index+1].continue_from_previous)}
function validateLocal(s,box){const errors=[];if(!s.references.length)errors.push('至少一张参考图');if((s.generation_mode||'r2va')==='fl2va'&&!s.continue_from_previous&&s.references.length<2)errors.push('FL2VA首段必须依次提供首帧和尾帧');if(s.continue_from_previous&&!previousOutputName(s))errors.push('延续镜头缺少上一镜输出名称');if(!s.prompt.trim())errors.push('提示词不能为空');s.status=errors.length?'invalid':'draft';s.error=errors.join('；');if(box)box.querySelector('.editor-message').textContent=errors.length?s.error:'验证通过';scheduleSave();return!errors.length}
async function submitShot(s,box=null,managedByBatch=false){if(batchScheduling&&!managedByBatch)throw new Error('批量生成进行中，请等待当前批次完成');if(!validateLocal(s,box)){render();throw new Error(s.error)}s.status='queued';s.error='';scheduleSave();render();const previous=board.shots[board.shots.indexOf(s)-1];try{const d=await api('/api/submit',jsonOpt('POST',{references:s.references,prompt:s.prompt,duration:s.duration,seed:s.seed,output_name:s.output_name,resolution:board.advanced_settings.resolution,aspect_ratio:s.aspect_ratio,generation_mode:s.generation_mode,continue_from_previous:s.continue_from_previous,previous_output_name:previousOutputName(s),previous_comfy_url:previous?.comfy_url||'',will_be_continued:willBeContinued(s),save_latent:s.save_latent,turbo_lora_enabled:board.advanced_settings.turbo_lora_enabled,sage_attention_enabled:board.advanced_settings.sage_attention_enabled,sampling_steps:board.advanced_settings.sampling_steps,audio_tail_carryover:s.audio_tail_carryover||'Full Previous Tail',audio_feather_ticks:Number.isInteger(s.audio_feather_ticks)?s.audio_feather_ticks:0}));s.resolution=board.advanced_settings.resolution;s.prompt_id=d.prompt_id;s.comfy_url=d.comfy_url;s.run_dir=d.run_dir;s.submitted_at=(d.submitted_at||Date.now()/1000);s.estimated_seconds=d.estimated_seconds;s.estimated_remaining_seconds=d.estimated_seconds;s.started_at=null;await saveBoard();render();return d}catch(e){s.status='failed';s.error=e.message;render();await saveBoard();throw e}}
async function cancelShot(s,box=null){if(!s.prompt_id||!['queued','running'].includes(s.status))return false;if(!confirm(`确定取消“${s.title||s.id}”的生成任务吗？`))return false;try{const d=await api('/api/cancel/'+encodeURIComponent(s.prompt_id)+targetQuery(s.comfy_url),{method:'POST'});if(!d.cancelled){if(box)box.querySelector('.editor-message').textContent='任务已经结束，无需取消';await pollStatuses();return false}s.status='cancelled';s.error='';s.estimated_remaining_seconds=0;await saveBoard();render();return true}catch(e){s.error='取消失败：'+e.message;if(box)box.querySelector('.editor-message').textContent=s.error;await saveBoard();return false}}
async function waitForShot(s){while(['queued','running'].includes(s.status)){await new Promise(resolve=>setTimeout(resolve,1500));await pollStatuses()}if(s.status==='completed'&&!(s.results||[]).some(r=>r.prompt_id===s.prompt_id))await collectResults(s);return s.status}
async function waitForUpscales(){while(hasActiveUpscale()){await new Promise(resolve=>setTimeout(resolve,1500));await pollUpscales()}}
async function cleanupBetweenShots(unloadModels=false,oomRecovery=false){return api('/api/memory/cleanup',jsonOpt('POST',{unload_models:unloadModels,oom_recovery:oomRecovery}))}
async function cleanupBetweenShotsSafely(){try{await cleanupBetweenShots(false);return true}catch(e){$('global-status').textContent='缓存清理失败，但不会中断批量生成：'+e.message;return false}}
async function preflightBatch(shots){const selected=new Set(shots),items=shots.map(s=>{const index=board.shots.indexOf(s),previous=index>0?board.shots[index-1]:null;return{id:s.id,output_name:s.output_name,continue_from_previous:Boolean(s.continue_from_previous),previous_output_name:previous?.output_name||'',previous_in_batch:Boolean(previous&&selected.has(previous))}}),result=await api('/api/batch/preflight',jsonOpt('POST',{shots:items}));if(!result.ok)throw new Error((result.errors||[]).join('；')||'批量生成 Latent 预检失败')}
async function submitMany(shots){if(batchScheduling){$('global-status').textContent='批量生成已经在调度中，请勿重复提交';return}if(!shots.length){$('global-status').textContent='没有选中任何分镜，请先勾选分镜或点击全选';return}if(hasActiveGeneration()){$('global-status').textContent='已有视频生成任务，请等待完成后再启动批量生成';return}batchScheduling=true;try{await preflightBatch(shots);$('global-status').textContent=`批量生成已启动，共 ${shots.length} 个分镜，将按故事板顺序串行生成`;await waitForUpscales();for(let index=0;index<shots.length;index++){const s=shots[index];try{$('global-status').textContent=`正在生成 ${s.id}（${index+1}/${shots.length}）；完成并保存 Latent 后才会继续下一镜`;await submitShot(s,null,true);const status=await waitForShot(s);if(status!=='completed'){$('global-status').textContent=`${s.id} 未完成，批量调度已停止`;break}await cleanupBetweenShotsSafely();if(index+1<shots.length)$('global-status').textContent=`${s.id} 已完成，正在提交下一镜 ${shots[index+1].id}`}catch(e){if(/out of memory|\bOOM\b/i.test(e.message)){try{await cleanupBetweenShots(false,true)}catch(_cleanupError){}}$('global-status').textContent=`${s.id} 生成失败，批量调度已停止：${e.message}`;break}}}catch(e){$('global-status').textContent='无法启动批量生成：'+e.message}finally{batchScheduling=false;pollStatuses()}}
async function pollStatuses(){if(polling)return;polling=true;let stateChanged=false,dataChanged=false;try{for(const s of board.shots.filter(x=>x.prompt_id&&['queued','running','failed'].includes(x.status))){try{const d=await api('/api/task-status/'+s.prompt_id+targetQuery(s.comfy_url)),next=d.status;if(next!==s.status){s.status=next;stateChanged=true;dataChanged=true}if(d.error&&s.error!==d.error){s.error=d.error;dataChanged=true;updateEditorMessage(s,d.error)}if(next==='running'&&!s.started_at){s.started_at=Date.now()/1000;dataChanged=true}if(Number.isFinite(d.estimated_remaining_seconds)){s.estimated_remaining_seconds=d.estimated_remaining_seconds;s.eta_source=d.eta_source;s.progress_percent=d.progress_percent;dataChanged=true}else if(next==='running'&&s.estimated_seconds){s.estimated_remaining_seconds=Math.max(0,s.estimated_seconds-(Date.now()/1000-s.started_at));dataChanged=true}else if(next==='queued'&&s.estimated_seconds){s.estimated_remaining_seconds=s.estimated_seconds}if(next==='completed'){s.estimated_remaining_seconds=0;await collectResults(s)}}catch(e){if(s.error!==e.message){s.error=e.message;dataChanged=true;updateEditorMessage(s,e.message)}}}for(const s of board.shots.filter(x=>x.prompt_id&&x.status==='completed'&&!(x.results||[]).some(r=>r.prompt_id===x.prompt_id)))await collectResults(s);if(dataChanged)scheduleSave();if(stateChanged)render();else refreshStatusCells()}finally{polling=false}}
async function openOutput(){const d=await api('/api/output-dir');await api('/api/open-path',jsonOpt('POST',{path:d.path}))}

$('storyboard-body').onclick=e=>{const row=e.target.closest('.shot-row');if(!row)return;const i=Number(row.dataset.i),s=board.shots[i];if(e.target.classList.contains('select-shot')){s.selected=e.target.checked;scheduleSave();return}if(e.target.classList.contains('copy')){board.shots.splice(i+1,0,newShot(s));expanded=i+1;scheduleSave();render();return}expanded=expanded===i?-1:i;render()};
$('queue-list').onclick=async e=>{
  const locate=e.target.dataset.queueLocate,cancel=e.target.dataset.queueCancel;
  if(locate!==undefined){
    const i=Number(locate);expanded=i;render();
    requestAnimationFrame(()=>document.querySelector(`#storyboard-body .shot-row[data-i="${i}"]`)?.scrollIntoView({behavior:'smooth',block:'center'}));
    return;
  }
  if(cancel!==undefined){const s=board.shots[Number(cancel)];if(s)await cancelShot(s)}
};
$('queue-toggle').onclick=()=>setQueueCollapsed(!$('queue-sidebar').classList.contains('collapsed'));
setQueueCollapsed(localStorage.getItem('ref2va.queueCollapsed')==='1',false);
$('add-shot').onclick=()=>{board.shots.push(newShot());expanded=board.shots.length-1;scheduleSave();render()};
$('toggle-select-all').onclick=()=>{const selectAll=!board.shots.every(s=>s.selected);board.shots.forEach(s=>{s.selected=selectAll});scheduleSave();render()};
$('new-storyboard').onclick=async()=>{if(!confirm('确定新建故事板吗？当前故事板内容会被清空，已生成的视频文件不会删除。'))return;clearTimeout(saveTimer);board={name:'未命名项目',shots:[]};board.advanced_settings=normalizeAdvancedSettings();board.shots=[newShot()];expanded=-1;continuousFailures.clear();$('project-name').value=board.name;syncAdvancedSettingsUI();render();await saveBoard()};
$('duplicate-shot').onclick=()=>{const i=expanded>=0?expanded:Math.max(0,board.shots.findIndex(s=>s.selected));board.shots.splice(i+1,0,newShot(board.shots[i]));expanded=i+1;scheduleSave();render()};
$('delete-selected').onclick=()=>{board.shots=board.shots.filter(s=>!s.selected);if(!board.shots.length)board.shots.push(newShot());expanded=-1;scheduleSave();render()};
$('save-storyboard').onclick=saveBoard;$('submit-selected').onclick=async()=>{await submitMany(board.shots.filter(s=>s.selected))};$('submit-all').onclick=async()=>{await submitMany(board.shots)};$('project-name').oninput=scheduleSave;
$('turbo-lora-enabled').onchange=e=>{board.advanced_settings.turbo_lora_enabled=e.target.checked;scheduleSave()};$('sage-attention-enabled').onchange=e=>{board.advanced_settings.sage_attention_enabled=e.target.checked;scheduleSave()};$('sampling-steps').onchange=e=>{board.advanced_settings.sampling_steps=Math.max(1,Math.min(100,Number.parseInt(e.target.value,10)||8));e.target.value=board.advanced_settings.sampling_steps;scheduleSave()};$('global-resolution').onchange=e=>{board.advanced_settings.resolution=e.target.value;board.shots.forEach(s=>{s.resolution=e.target.value;if(s.status!=='completed')s.status='draft'});scheduleSave();render()};$('auto-upscale-enabled').onchange=e=>{board.advanced_settings.auto_upscale_enabled=e.target.checked;scheduleSave();if(e.target.checked)submitPendingAutoUpscales()};$('upscale-resolution').onchange=e=>{board.advanced_settings.upscale_resolution=e.target.value;scheduleSave()};
$('generation-target').onchange=async e=>{if(hasActiveGeneration()||hasActiveUpscale()){e.target.value=board.advanced_settings.generation_target;$('global-status').textContent='有任务正在运行，完成或取消后才能切换生成设备';return}board.advanced_settings.generation_target=e.target.value==='remote'?'remote':'local';syncAdvancedSettingsUI();await saveBoard();await health()};
$('comfy-url').onchange=async e=>{let value=String(e.target.value||'').trim().replace(/\/+$/,'');try{const parsed=new URL(value);if(!['http:','https:'].includes(parsed.protocol))throw new Error();value=parsed.origin}catch{e.target.value=board.advanced_settings.comfy_url;$('global-status').textContent='远端地址格式无效，例如 http://192.168.11.103:8188';return}board.advanced_settings.comfy_url=value;e.target.value=value;await saveBoard();await health()};
$('test-comfy-connection').onclick=async()=>{let value=String($('comfy-url').value||'').trim().replace(/\/+$/,'');try{const parsed=new URL(value);if(!['http:','https:'].includes(parsed.protocol))throw new Error();value=parsed.origin}catch{$('global-status').textContent='远端地址格式无效，例如 http://192.168.11.103:8188';return}board.advanced_settings.comfy_url=value;$('comfy-url').value=value;await saveBoard();await health(true)};
$('upscale-all-results').onclick=submitAllUpscales;
$('export-json').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(board,null,2)],{type:'application/json'}));a.download=(board.name||'storyboard')+'.json';a.click();URL.revokeObjectURL(a.href)};
$('import-json').onclick=()=>$('json-file').click();$('json-file').onchange=async e=>{try{const imported=JSON.parse(await e.target.files[0].text()),merged=Ref2VAProjectMerge.mergeImportedProject(board,imported);board=merged;board.advanced_settings=normalizeAdvancedSettings(board.advanced_settings);expanded=-1;$('project-name').value=board.name||'未命名项目';syncAdvancedSettingsUI();render();await saveBoard()}catch(e){$('global-status').textContent='导入失败：'+e.message}finally{e.target.value=''}};
$('preview-restart').onclick=restartContinuous;
$('preview-prev').onclick=()=>advanceContinuous(-1,true);
$('preview-next').onclick=()=>advanceContinuous(1,true);
$('image-preview-close').onclick=()=>$('image-preview-dialog').close();
$('image-preview-dialog').onclick=e=>{if(e.target===$('image-preview-dialog'))e.target.close()};
document.body.ondblclick=e=>{const image=e.target.closest('[data-preview-path]');if(!image)return;e.preventDefault();e.stopPropagation();openImagePreview(image.dataset.previewPath)};
async function health(showResult=false){const pill=$('health'),remote=board.advanced_settings?.generation_target==='remote',target=remote?'远端':'本机',configuredUrl=remote?board.advanced_settings.comfy_url:'http://127.0.0.1:8188';try{const d=await api('/api/health');if(!d.ok)throw new Error(d.error||'未连接');const connectedUrl=d.comfy_url||configuredUrl;pill.textContent=`${target} ComfyUI 已连接`;pill.className='pill ok';pill.title=connectedUrl;if(showResult)$('global-status').textContent=`连接成功：${connectedUrl}`}catch(e){pill.textContent=`${target} ComfyUI 未连接`;pill.className='pill bad';pill.title=e.message;if(showResult)$('global-status').textContent=`连接失败：${e.message}`}}
loadBoard();health();setInterval(()=>{health();pollStatuses();pollUpscales();submitPendingAutoUpscales()},5000);
