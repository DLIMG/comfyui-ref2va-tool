import json
import subprocess
from pathlib import Path


MEDIA_PLAYER_MODULE = Path(__file__).parents[1] / "app" / "static" / "media-player.js"


def test_replacing_media_detaches_delayed_events_from_previous_source():
    script = r"""
const media = require(process.argv[1]);
class FakeVideo {
  constructor() { this.dataset = {}; this.listeners = {}; this.pauseCalls = 0; }
  addEventListener(name, handler) { (this.listeners[name] ||= new Set()).add(handler); }
  removeEventListener(name, handler) { this.listeners[name]?.delete(handler); }
  dispatch(name) { for (const handler of [...(this.listeners[name] || [])]) handler(); }
  pause() { this.pauseCalls += 1; }
  cloneNode() { return new FakeVideo(); }
  removeAttribute() {}
  replaceWith(next) { this.replacement = next; }
}
const handlers = new WeakMap();
let index = 0;
const failures = new Set();
function bind(video, key) {
  const bound = {error: () => failures.add(key), ended: () => { index += 1; }};
  handlers.set(video, bound);
  video.addEventListener('error', bound.error);
  video.addEventListener('ended', bound.ended);
}
function unbind(video) {
  const bound = handlers.get(video);
  if (!bound) return;
  video.removeEventListener('error', bound.error);
  video.removeEventListener('ended', bound.ended);
  handlers.delete(video);
}
const sourceA = new FakeVideo();
sourceA.dataset.itemKey = '01A:a';
bind(sourceA, '01A:a');
const sourceB = media.replaceMediaElement(sourceA, '02A:b', unbind, bind);
sourceA.dispatch('error');
sourceA.dispatch('ended');
const staleState = {index, failures: [...failures]};
sourceB.dispatch('ended');
sourceB.dispatch('error');
process.stdout.write(JSON.stringify({staleState,currentState:{index,failures:[...failures]},pausedOld:sourceA.pauseCalls,replaced:sourceA.replacement===sourceB,currentKey:sourceB.dataset.itemKey}));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(MEDIA_PLAYER_MODULE)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["staleState"] == {"index": 0, "failures": []}
    assert result["currentState"] == {"index": 1, "failures": ["02A:b"]}
    assert result["pausedOld"] == 1
    assert result["replaced"] is True
    assert result["currentKey"] == "02A:b"


def test_preloaded_video_is_promoted_without_clearing_the_stage():
    script = r"""
const media = require(process.argv[1]);
class FakeClassList { constructor(){this.values=new Set()} add(x){this.values.add(x)} remove(x){this.values.delete(x)} has(x){return this.values.has(x)} }
class FakeParent { appendChild(x){this.child=x;x.parentNode=this} }
class FakeVideo {
  constructor(){this.dataset={};this.classList=new FakeClassList();this.controls=true;this.pauseCalls=0;this.removed=false;this.loaded=false;this.parentNode=new FakeParent()}
  cloneNode(){const x=new FakeVideo();x.parentNode=this.parentNode;return x}
  removeAttribute(name){if(name==='id')this.id='';if(name==='controls')this.controls=false}
  pause(){this.pauseCalls+=1}
  load(){this.loaded=true}
  remove(){this.removed=true}
}
const active=new FakeVideo();active.id='continuous-video';
const standby=media.preparePreload(active,'02A:b','/b.mp4');
let unbound=false,bound=false;
const promoted=media.promotePreloaded(active,standby,'02A:b',()=>{unbound=true},()=>{bound=true});
process.stdout.write(JSON.stringify({same:promoted===standby,key:promoted.dataset.itemKey,id:promoted.id,controls:promoted.controls,hidden:promoted.classList.has('preview-standby'),oldRemoved:active.removed,oldPaused:active.pauseCalls,unbound,bound,loaded:standby.loaded,src:standby.src}));
"""
    completed = subprocess.run(["node", "-e", script, str(MEDIA_PLAYER_MODULE)], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result == {
        "same": True, "key": "02A:b", "id": "continuous-video", "controls": True,
        "hidden": False, "oldRemoved": True, "oldPaused": 1, "unbound": True,
        "bound": True, "loaded": True, "src": "/b.mp4",
    }


def test_matching_preload_is_reused_across_ui_renders():
    script = r"""
const media = require(process.argv[1]);
const standby = {dataset:{itemKey:'02A:b'}};
process.stdout.write(JSON.stringify({same:media.canReusePreload(standby,'02A:b'),different:media.canReusePreload(standby,'03A:c'),missing:media.canReusePreload(null,'02A:b')}));
"""
    completed = subprocess.run(["node", "-e", script, str(MEDIA_PLAYER_MODULE)], check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout) == {"same": True, "different": False, "missing": False}
