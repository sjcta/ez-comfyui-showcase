/**
 * icons.js — SVG Icon helper for Ez ComfyUI Showcase
 * Sprite is inlined in index.html. This module provides CW.icon().
 *
 * Usage in templates:
 *   ${CW.icon('play')}                    // default 16px
 *   ${CW.icon('trash-2', 20)}            // 20px
 *   ${CW.icon('check', 14, 'var(--green)')} // 14px, green
 */
(function() {
  function icon(name, size, color) {
    size = size || 16;
    color = color || 'currentColor';
    return '<svg class="cw-icon" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="cw-icon-svg"><use href="#icon-' + name + '"/></svg>';
  }

  window.CW = window.CW || {};
  window.CW.icon = icon;
})();
