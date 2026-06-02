/**
 * CardManager thin adapter.
 *
 * History owns gallery rendering and DOM patching. This adapter keeps the
 * small runtime contract used by PollManager without carrying a second copy
 * of the card renderer.
 */
(function () {
  'use strict';

  function CardManager(galleryEl) {
    this.galleryEl = galleryEl || document.getElementById('gallery');
  }

  CardManager.prototype.renderCard = function (data) {
    if (!data) return '';
    if (data.status !== 'history' && window.CW && typeof window.CW._renderJobCard === 'function') {
      return window.CW._renderJobCard(data);
    }
    return '';
  };

  CardManager.prototype.patchJobCard = function (job) {
    if (!job) return;
    if (window.CW && typeof window.CW._patchJobCard === 'function') {
      window.CW._patchJobCard(job);
    } else if (window.CW && typeof window.CW.forceGalleryRerender === 'function') {
      window.CW.forceGalleryRerender();
    }
  };

  CardManager.prototype.onJobDone = function (job) {
    if (window.CW && typeof window.CW._onJobDone === 'function') {
      window.CW._onJobDone(job);
    }
  };

  CardManager.prototype.onJobError = function (job) {
    if (window.CW && typeof window.CW._onJobError === 'function') {
      window.CW._onJobError(job);
    }
  };

  CardManager.prototype.renderGallery = function () {
    if (window.CW && typeof window.CW.renderGallery === 'function') {
      window.CW.renderGallery();
    }
  };

  CardManager.prototype.forceRender = function () {
    if (window.CW && typeof window.CW.forceGalleryRerender === 'function') {
      window.CW.forceGalleryRerender();
    } else {
      this.renderGallery();
    }
  };

  CardManager.prototype.populateFilterOptions = function () {
    if (window.CW && typeof window.CW.refreshHistoryTypeFilters === 'function') {
      window.CW.refreshHistoryTypeFilters();
    }
  };

  CardManager.prototype.filterHistory = function (arr) {
    return Array.isArray(arr) ? arr : [];
  };

  CardManager.prototype.applyFilters = function () {
    if (window.CW && typeof window.CW.applyFilters === 'function') {
      window.CW.applyFilters();
    }
  };

  CardManager.prototype.clearFilters = function () {
    if (window.CW && typeof window.CW.clearFilters === 'function') {
      window.CW.clearFilters();
    }
  };

  function initCardManager() {
    if (window.CW.cardManager) return;
    window.CW.cardManager = new CardManager(document.getElementById('gallery'));
  }

  if (!window.CW) window.CW = {};
  window.CW.CardManager = CardManager;
  window.CW.initCardManager = initCardManager;
})();
