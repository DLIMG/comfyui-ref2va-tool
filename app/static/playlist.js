(function (root) {
  "use strict";

  function latestResult(results) {
    if (!Array.isArray(results) || results.length === 0) return undefined;

    let latestValid;
    let latestTime = -Infinity;

    results.forEach((result) => {
      const timestamp = Date.parse(result && result.created_at);
      if (!Number.isNaN(timestamp) && timestamp >= latestTime) {
        latestValid = result;
        latestTime = timestamp;
      }
    });

    return latestValid === undefined ? results[results.length - 1] : latestValid;
  }

  function buildContinuousPlaylist(shots) {
    const items = [];

    (Array.isArray(shots) ? shots : []).forEach((shot) => {
      const result = latestResult(shot && shot.results);
      if (result !== undefined) {
        items.push({ shotId: shot.id, title: shot.title, result });
      }
    });

    return items;
  }

  function reconcilePlaylistIndex(items, currentResultId, previousIndex) {
    if (!Array.isArray(items) || items.length === 0) return 0;

    const currentIndex = items.findIndex(
      (item) => item && item.result && item.result.id === currentResultId
    );
    if (currentIndex !== -1) return currentIndex;

    const fallbackIndex = Number.isFinite(previousIndex) ? Math.trunc(previousIndex) : 0;
    return Math.max(0, Math.min(fallbackIndex, items.length - 1));
  }

  const api = { latestResult, buildContinuousPlaylist, reconcilePlaylistIndex };

  if (root) root.Ref2VAPlaylist = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : undefined);
