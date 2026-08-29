(function (root) {
  "use strict";

  function replaceMediaElement(video, itemKey, unbind, bind) {
    video.pause();
    unbind(video);
    const replacement = video.cloneNode(false);
    replacement.removeAttribute("src");
    replacement.dataset.itemKey = itemKey;
    video.replaceWith(replacement);
    bind(replacement, itemKey);
    return replacement;
  }

  function preparePreload(active, itemKey, src) {
    const standby = active.cloneNode(false);
    standby.removeAttribute("id");
    standby.removeAttribute("controls");
    standby.controls = false;
    standby.preload = "auto";
    standby.dataset.itemKey = itemKey;
    standby.classList.add("preview-standby");
    standby.src = src;
    active.parentNode.appendChild(standby);
    standby.load();
    return standby;
  }

  function canReusePreload(standby, itemKey) {
    return Boolean(standby && standby.dataset && standby.dataset.itemKey === itemKey);
  }

  function promotePreloaded(active, standby, itemKey, unbind, bind) {
    active.pause();
    unbind(active);
    standby.dataset.itemKey = itemKey;
    standby.id = "continuous-video";
    standby.controls = true;
    standby.classList.remove("preview-standby");
    bind(standby, itemKey);
    active.remove();
    return standby;
  }

  const api = { replaceMediaElement, preparePreload, canReusePreload, promotePreloaded };

  if (root) root.Ref2VAMedia = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : undefined);
