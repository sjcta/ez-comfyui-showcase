from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistoryDeleteFocusContractTests(unittest.TestCase):
    def test_delete_history_clears_delete_button_focus_after_rerender(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _clearHistoryDeleteFocus", history_js)
        self.assertIn("classList.contains('gi-del')", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        focus_clear_before = history_js.index("_clearHistoryDeleteFocus();", del_start)
        focus_clear_after = history_js.index("_clearHistoryDeleteFocus();", focus_clear_before + 1)

        self.assertLess(focus_clear_before, del_end)
        self.assertLess(focus_clear_after, del_end)

    def test_delete_history_removes_dom_nodes_and_resyncs_remaining_card_actions(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _renderGalleryAfterHistoryRemoval(deletedEntryKeys)", history_js)
        self.assertIn("_removeDeletedHistoryCardsFromDom(deletedEntryKeys);", history_js)
        self.assertIn("_syncVisibleHistoryCardIndices();", history_js)
        self.assertIn("_historyTotal = Math.max(0, _historyTotal - deleted.size)", history_js)
        self.assertIn("_syncHistoryLoadedAllAfterLocalRemoval();", history_js)
        self.assertIn("_syncDerivedHistoryState();", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        self.assertIn("var deletedEntryKeys = _historyEntryKeysForItems(items);", del_body)
        unified_render_call = history_js.index("_renderGalleryAfterHistoryRemoval(deletedEntryKeys);", del_start)
        workflow_refresh = history_js.index("CW.loadWorkflows", del_start)
        self.assertLess(unified_render_call, workflow_refresh)
        self.assertNotIn("_patchVisibleHistoryCardsFromData", del_body)
        self.assertNotIn("_galleryStore.schedule('history:remove", del_body)
        self.assertNotIn("_captureHistoryScroll", del_body)
        self.assertNotIn("_restoreHistoryScroll", del_body)
        self.assertNotIn("_reloadHistoryWindow(true)", del_body)
        self.assertIn("_blockGalleryRenderForAtomicDelete(1800);", del_body)

    def test_delete_history_dom_update_does_not_insert_or_reorder_cards(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        fn_start = history_js.index("function _renderGalleryAfterHistoryRemoval(deletedEntryKeys)")
        fn_end = history_js.index("function _historyEmptyHintHtml", fn_start)
        fn_body = history_js[fn_start:fn_end]

        self.assertIn("_removeDeletedHistoryCardsFromDom(deletedEntryKeys);", fn_body)
        self.assertIn("_syncVisibleHistoryCardIndices();", fn_body)
        self.assertNotIn("_atomicDeleteRenderBlockUntil = 0", fn_body)
        self.assertNotIn("insertAdjacentHTML", fn_body)
        self.assertNotIn("insertBefore", fn_body)
        self.assertNotIn("_histCardHTML", fn_body)
        self.assertNotIn("_galleryStore.schedule", fn_body)
        self.assertNotIn("_renderGalleryImpl();", fn_body)
        self.assertNotIn("_patchGalleryHTML(gallery, html)", fn_body)

    def test_delete_resync_updates_lightbox_and_delete_targets_after_local_removal(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        sync_start = history_js.index("function _syncVisibleHistoryCardIndices()")
        sync_end = history_js.index("function _currentUserId()", sync_start)
        sync_body = history_js[sync_start:sync_end]

        self.assertIn("card.setAttribute('data-hist-idx', String(idx));", sync_body)
        self.assertIn("CW.openLB(\" + idx", sync_body)
        self.assertIn("CW.openBatchLB('\" + escA(entry.batch_id)", sync_body)
        self.assertIn("var del = card.querySelector('.gi-del');", sync_body)
        self.assertIn("var deleteTargetId = _batchDeleteTargetId(entry, cover);", sync_body)
        self.assertIn("CW.delHist('\" + escA(deleteTargetId) + \"', event)", sync_body)
        self.assertIn("del.remove();", sync_body)

    def test_delete_can_resolve_lazy_batch_card_when_inline_target_is_stale(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _historyItemsForDeleteTarget(id, sourceEvent)", history_js)
        helper_start = history_js.index("function _historyItemsForDeleteTarget(id, sourceEvent)")
        helper_end = history_js.index("function _historyRecordFromJob", helper_start)
        helper_body = history_js[helper_start:helper_end]
        self.assertIn("target.closest('.gi[data-hist-id]')", helper_body)
        self.assertIn("cardKey.indexOf('batch:') === 0", helper_body)
        self.assertIn("batchKey = cardKey.slice(6);", helper_body)
        self.assertIn("return historyItems.filter(function(h) { return _batchKey(h) === batchKey; });", helper_body)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        self.assertIn("async function delHist(id, sourceEvent)", del_body)
        self.assertIn("var items = _historyItemsForDeleteTarget(id, sourceEvent);", del_body)
        self.assertIn("eventTarget.closest('.gi[data-hist-id]')", del_body)

    def test_gallery_updates_are_scheduled_through_store(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("var _galleryStore = {", history_js)
        self.assertIn("function _scheduleGalleryRender(reason, options)", history_js)
        self.assertIn("window.CW.galleryStore = _galleryStore;", history_js)

        render_start = history_js.index("function renderGallery()")
        render_end = history_js.index("if (!window.CW) window.CW = {};", render_start)
        render_body = history_js[render_start:render_end]
        self.assertIn("_galleryStore.schedule('renderGallery');", render_body)
        self.assertNotIn("requestAnimationFrame(function()", render_body)
        self.assertNotIn("_renderGalleryImpl();", render_body)

        force_start = history_js.index("window.CW.forceGalleryRerender = function()")
        force_end = history_js.index("};", force_start)
        force_body = history_js[force_start:force_end]
        self.assertIn("_galleryStore.schedule('forceGalleryRerender', { force: true });", force_body)

    def test_delete_and_hide_do_not_rewind_server_history_offset(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _syncHistoryLoadedAllAfterLocalRemoval()", history_js)
        self.assertIn("Keep the server offset monotonic", history_js)
        self.assertNotIn("_historyNextOffset = Math.max(0, _historyNextOffset - 1)", history_js)
        self.assertNotIn("_historyNextOffset = Math.max(0, _historyNextOffset - deleted.size)", history_js)

        hide_start = history_js.index("function _removeHiddenHistoryItem")
        hide_end = history_js.index("async function toggleHistoryHidden", hide_start)
        hide_body = history_js[hide_start:hide_end]
        self.assertIn("_historyTotal = Math.max(0, _historyTotal - 1)", hide_body)
        self.assertIn("_syncHistoryLoadedAllAfterLocalRemoval();", hide_body)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        self.assertIn("_historyTotal = Math.max(0, _historyTotal - deleted.size)", del_body)
        self.assertIn("_syncHistoryLoadedAllAfterLocalRemoval();", del_body)
        self.assertIn("_historyNextOffset += page.raw_count || page.items.length", history_js)

    def test_render_gallery_is_blocked_during_atomic_delete_window(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        render_start = history_js.index("function _scheduleGalleryRender(reason, options)")
        render_end = history_js.index("var _galleryStore = {", render_start)
        render_body = history_js[render_start:render_end]
        block_start = history_js.index("function _isAtomicDeleteRenderBlocked()")
        block_end = history_js.index("function _scheduleGalleryRender", block_start)
        block_body = history_js[block_start:block_end]

        self.assertIn("_atomicDeleteRenderBlockUntil", render_body)
        self.assertIn("_isAtomicDeleteRenderBlocked()", render_body)
        self.assertIn("Date.now() < _atomicDeleteRenderBlockUntil", block_body)
        self.assertIn("requestAnimationFrame(run)", render_body)

    def test_atomic_delete_block_prevents_lazy_append_and_load_more(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _isAtomicDeleteRenderBlocked()", history_js)
        self.assertIn("function _scheduleSentinelRearmAfterAtomicDelete()", history_js)
        self.assertIn("function _finishSentinelRearmAfterDelete()", history_js)
        self.assertIn("function _onSentinelRearmScroll()", history_js)
        self.assertIn("_sentinelRearmAfterScroll = true;", history_js)
        self.assertIn("_sentinelRearmScrollSeen", history_js)

        sentinel_start = history_js.index("function _attachSentinel()")
        sentinel_end = history_js.index("_sentinelObs = null;", sentinel_start)
        sentinel_body = history_js[sentinel_start:sentinel_end]
        self.assertIn("if (_isAtomicDeleteRenderBlocked()) {", sentinel_body)
        self.assertIn("if (_isAtomicDeleteRenderBlocked()) {", sentinel_body[sentinel_body.index("IntersectionObserver"):])
        self.assertIn("_scheduleSentinelRearmAfterAtomicDelete();", sentinel_body)
        self.assertIn("rootMargin: _historyLazyPreloadDistance() + 'px'", sentinel_body)
        self.assertNotIn("rootMargin: '300px'", sentinel_body)

        append_start = history_js.index("function _appendNewHistoryCards()")
        append_end = history_js.index("function _histCardHTML", append_start)
        append_body = history_js[append_start:append_end]
        self.assertIn("if (_isAtomicDeleteRenderBlocked()) {", append_body)
        self.assertIn("requestAnimationFrame", append_body)
        self.assertIn("if (_isAtomicDeleteRenderBlocked()) {", append_body[append_body.index("requestAnimationFrame"):])

        load_start = history_js.index("async function _loadMoreHistory")
        load_end = history_js.index("async function loadHistory", load_start)
        load_body = history_js[load_start:load_end]
        self.assertIn("if (!manual && _isAtomicDeleteRenderBlocked()) {", load_body)
        self.assertIn("_scheduleSentinelRearmAfterAtomicDelete();", load_body)

    def test_atomic_delete_rearms_lazy_load_after_block_even_without_scroll(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        bind_start = history_js.index("function _bindSentinelRearmScroll()")
        bind_end = history_js.index("function _unbindSentinelRearmScroll()", bind_start)
        bind_body = history_js[bind_start:bind_end]
        self.assertIn("_historyBackTopRoots().forEach", bind_body)
        self.assertIn("root.addEventListener('scroll', _onSentinelRearmScroll", bind_body)

        finish_start = history_js.index("function _finishSentinelRearmAfterDelete()")
        finish_end = history_js.index("function _onSentinelRearmScroll()", finish_start)
        finish_body = history_js[finish_start:finish_end]
        self.assertIn("_sentinelRearmAfterScroll = false;", finish_body)
        self.assertIn("_unbindSentinelRearmScroll();", finish_body)
        self.assertIn("_attachSentinel();", finish_body)
        self.assertIn("_triggerVisibleSentinelLoad();", finish_body)

        scroll_start = history_js.index("function _onSentinelRearmScroll()")
        scroll_end = history_js.index("function _scheduleSentinelRearmAfterAtomicDelete()", scroll_start)
        scroll_body = history_js[scroll_start:scroll_end]
        self.assertIn("_sentinelRearmScrollSeen = true;", scroll_body)
        self.assertIn("_finishSentinelRearmAfterDelete();", scroll_body)

        schedule_start = history_js.index("function _scheduleSentinelRearmAfterAtomicDelete()")
        schedule_end = history_js.index("function _isSentinelNearViewport", schedule_start)
        schedule_body = history_js[schedule_start:schedule_end]
        self.assertIn("setTimeout(function()", schedule_body)
        self.assertIn("_finishSentinelRearmAfterDelete();", schedule_body)
        self.assertNotIn("if (_sentinelRearmScrollSeen)", schedule_body)

        near_start = history_js.index("function _isSentinelNearViewport")
        near_end = history_js.index("function _historyLazyPreloadDistance", near_start)
        near_body = history_js[near_start:near_end]
        self.assertIn("var preloadPx = _historyLazyPreloadDistance();", near_body)
        self.assertIn("rect.top < viewportH + preloadPx", near_body)
        self.assertIn("rect.bottom >= -preloadPx", near_body)
        self.assertNotIn("viewportH + 300", near_body)

        preload_start = history_js.index("function _historyLazyPreloadDistance")
        preload_end = history_js.index("function _triggerVisibleSentinelLoad", preload_start)
        preload_body = history_js[preload_start:preload_end]
        self.assertIn("querySelectorAll('.gi[data-hist-id]')", preload_body)
        self.assertIn("getBoundingClientRect().height", preload_body)
        self.assertIn("Math.max(320, Math.min(900, median || 0))", preload_body)

        trigger_start = history_js.index("function _triggerVisibleSentinelLoad()")
        trigger_end = history_js.index("function _scheduleGalleryRender", trigger_start)
        trigger_body = history_js[trigger_start:trigger_end]
        self.assertIn("_isSentinelNearViewport(sentinel)", trigger_body)
        self.assertIn("_appendNewHistoryCards();", trigger_body)
        self.assertIn("_loadMoreHistory();", trigger_body)

    def test_lazy_append_starts_after_current_dom_tail_card(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _nextUnrenderedHistoryIndex(displayArr)", history_js)
        cursor_start = history_js.index("function _nextUnrenderedHistoryIndex(displayArr)")
        cursor_end = history_js.index("function _appendNewHistoryCards()", cursor_start)
        cursor_body = history_js[cursor_start:cursor_end]
        self.assertIn("gallery.querySelectorAll('.gi[data-hist-id]')", cursor_body)
        self.assertIn("indexByKey[_galleryEntryKey(entry)] = idx;", cursor_body)
        self.assertIn("cards[i].getAttribute('data-hist-id')", cursor_body)
        self.assertIn("return indexByKey[key] + 1;", cursor_body)

        append_start = history_js.index("function _appendNewHistoryCards()")
        append_end = history_js.index("function _histCardHTML", append_start)
        append_body = history_js[append_start:append_end]
        self.assertIn("const prevCount = _nextUnrenderedHistoryIndex(filteredArr2);", append_body)
        self.assertNotIn("const prevCount = _lastRenderedHistCount;", append_body)

    def test_lazy_fetch_uses_last_loaded_history_id_cursor(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _lastLoadedHistoryCursorId()", history_js)
        cursor_start = history_js.index("function _lastLoadedHistoryCursorId()")
        cursor_end = history_js.index("function _syncHistoryLoadedAllAfterLocalRemoval()", cursor_start)
        cursor_body = history_js[cursor_start:cursor_end]
        self.assertIn("var sorted = _sortHistoryItems(historyItems || []);", cursor_body)
        self.assertIn("var tail = sorted.length ? sorted[sorted.length - 1] : null;", cursor_body)
        self.assertIn("return String(tail && tail.id || '');", cursor_body)

        self.assertIn("function _nextHistoryFetchOffset()", history_js)
        fetch_start = history_js.index("async function _fetchHistoryPage")
        fetch_end = history_js.index("async function loadHistory", fetch_start)
        fetch_body = history_js[fetch_start:fetch_end]
        self.assertIn("if (afterId) params.set('after_id', String(afterId || ''));", fetch_body)
        self.assertIn("else params.set('offset', String(offset || 0));", fetch_body)

        load_start = history_js.index("async function _loadMoreHistory")
        load_end = history_js.index("async function loadHistory", load_start)
        load_body = history_js[load_start:load_end]
        self.assertIn("await _fetchHistoryPage(_nextHistoryFetchOffset(), HISTORY_PAGE_SIZE, _lastLoadedHistoryCursorId())", load_body)

    def test_lazy_load_success_appends_without_full_gallery_render(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _syncHistorySentinelState()", history_js)
        load_start = history_js.index("async function _loadMoreHistory")
        load_end = history_js.index("async function loadHistory", load_start)
        load_body = history_js[load_start:load_end]

        self.assertIn("_syncHistorySentinelState();", load_body)
        self.assertIn("_appendNewHistoryCards();", load_body)
        self.assertIn("_syncHistoryCountText();", load_body)

        success_start = load_body.index("var seen = new Set")
        success_end = load_body.index("} catch (e)")
        success_body = load_body[success_start:success_end]
        self.assertNotIn("renderGallery();", success_body)

    def test_delete_history_does_not_reposition_scroll(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _historyScrollRoot()", history_js)
        self.assertIn("document.querySelector('.workspace')", history_js)
        self.assertIn("function _isScrollableHistoryRoot(el)", history_js)
        self.assertIn("window.getComputedStyle(el)", history_js)
        self.assertIn("el && el.scrollTop > 0", history_js)
        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]

        self.assertIn("var deletedEntryKeys = _historyEntryKeysForItems(items);", del_body)
        self.assertIn("_renderGalleryAfterHistoryRemoval(deletedEntryKeys);", del_body)
        self.assertNotIn("_captureHistoryScroll", del_body)
        self.assertNotIn("_restoreHistoryScroll", del_body)
        self.assertNotIn("scrollTop", del_body)

    def test_manual_protection_toggle_patches_card_without_gallery_rerender(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _patchHistoryProtectionCard(id, data)", history_js)
        self.assertIn("image.classList.toggle('gi-sensitive', shouldProtect);", history_js)

        apply_start = history_js.index("function _applyHistoryProtectionState")
        apply_end = history_js.index("async function toggleHistoryProtection", apply_start)
        apply_body = history_js[apply_start:apply_end]
        self.assertIn("_patchHistoryProtectionCard(id, patch);", apply_body)
        self.assertIn("_historyDetailCache[id] = Object.assign({}, _historyDetailCache[id], patch);", apply_body)
        self.assertNotIn("_galleryStore.schedule", apply_body)
        self.assertNotIn("_captureHistoryScroll", apply_body)
        self.assertNotIn("_restoreHistoryScroll", apply_body)
        self.assertNotIn("scrollTop", apply_body)

        toggle_start = history_js.index("async function toggleHistoryProtection")
        toggle_end = history_js.index("function toggleLBHidden", toggle_start)
        toggle_body = history_js[toggle_start:toggle_end]
        self.assertIn("_applyHistoryProtectionState(id, d);", toggle_body)
        self.assertNotIn("_galleryStore.schedule('history:protection'", toggle_body)
        self.assertNotIn("CW.loadWorkflows", toggle_body)
        self.assertNotIn("_captureHistoryScroll", toggle_body)
        self.assertNotIn("_restoreHistoryScroll", toggle_body)
        self.assertNotIn("scrollTop", toggle_body)

    def test_protection_history_update_does_not_reload_gallery_window(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        update_start = history_js.index("function onHistoryUpdate(update)")
        update_end = history_js.index("async function _fetchHistoryPage", update_start)
        update_body = history_js[update_start:update_end]
        protection_start = update_body.index("if (action === 'protection' && ids.length)")
        protection_end = update_body.index("var removeFromGallery", protection_start)
        protection_body = update_body[protection_start:protection_end]

        self.assertIn("_applyHistoryProtectionState(id, update);", protection_body)
        self.assertIn("return;", protection_body)
        self.assertNotIn("loadHistory", protection_body)
        self.assertNotIn("loadWorkflows", protection_body)
        self.assertLess(update_body.index("if (action === 'protection' && ids.length)"), update_body.index("Promise.resolve(loadHistory()).catch"))

    def test_deleted_history_ids_are_tombstoned_against_stale_lazy_loads(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("var _deletedHistoryIds = {};", history_js)
        self.assertIn("HISTORY_DELETE_TOMBSTONE_TTL_MS", history_js)
        self.assertIn("function _markHistoryIdsDeleted(ids)", history_js)
        self.assertIn("function _filterDeletedHistoryItems(items)", history_js)
        self.assertIn("function _removeOptimisticHistoryIds(ids)", history_js)
        self.assertIn("var items = _filterDeletedHistoryItems(d.data || []);", history_js)
        self.assertIn("raw_count: Array.isArray(d.data) ? d.data.length : items.length", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        self.assertIn("_markHistoryIdsDeleted(deleteIds);", del_body)
        self.assertIn("_removeOptimisticHistoryIds(deleteIds);", del_body)
        self.assertIn("_unmarkHistoryIdsDeleted(deleteIds);", del_body)


if __name__ == "__main__":
    unittest.main()
