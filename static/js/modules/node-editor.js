/**
 * Node Editor Module
 * Extracted from app.js v3.10
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs;
  var _nodeEditorConfig = null;
  var _nodeEditorData = null;
  var _nodeEditorFname = '';
  var _nodeEditorCompactMobile = false;
  var _draggingNodeKey = '';
  var _pointerDrag = null;

  function updateNodeEditorStats() {
    var cards = document.querySelectorAll('#nodeEditorModal .ne-field');
    var total = cards.length;
    var visible = 0;
    for (var i = 0; i < cards.length; i++) {
      if (!cards[i].classList.contains('hidden-field')) visible += 1;
    }
    var totalEl = document.getElementById('neStatTotal');
    var visibleEl = document.getElementById('neStatVisible');
    if (totalEl) totalEl.textContent = String(total);
    if (visibleEl) visibleEl.textContent = String(visible);
  }

  function updateNodeCompactState() {
    _nodeEditorCompactMobile = !!(window.matchMedia && window.matchMedia('(max-width: 765px)').matches);
    var modal = document.getElementById('nodeEditorModal');
    if (!modal) return;
    modal.classList.toggle('node-editor-mobile-compact', _nodeEditorCompactMobile);
  }

  function getDropTarget(container, y, draggingCard) {
    var cards = Array.from(container.querySelectorAll('.ne-field:not(.dragging)'));
    var closest = null;
    var closestOffset = Number.NEGATIVE_INFINITY;
    for (var i = 0; i < cards.length; i++) {
      var box = cards[i].getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closestOffset) {
        closestOffset = offset;
        closest = cards[i];
      }
    }
    return closest;
  }

  function zoneIdForName(zone) {
    return {
      user_input: 'neZoneUserInput',
      advanced: 'neZoneAdvanced',
      output: 'neZoneOutput',
      hidden: 'neZoneHidden',
    }[zone] || 'neZoneHidden';
  }

  function zoneNameForContainer(container) {
    var zone = container && container.closest ? container.closest('.ne-zone') : null;
    return zone ? (zone.dataset.zone || 'hidden') : 'hidden';
  }

  function syncCardZoneState(card, zone) {
    if (!card) return;
    zone = zone || zoneNameForContainer(card.parentElement);
    var hidden = zone === 'hidden';
    if (!hidden) card.dataset.prevZone = zone;
    card.dataset.zone = zone;
    card.classList.toggle('hidden-field', hidden);
    var btn = card.querySelector('.ne-field-vis');
    if (btn) {
      btn.innerHTML = hidden ? CW.icon('eye-off') : CW.icon('eye');
      btn.title = hidden ? '当前不可见，点击设为可见' : '当前可见，点击设为不可见';
    }
  }

  function moveCardToPoint(card, x, y) {
    var target = document.elementFromPoint(x, y);
    var container = target && target.closest ? target.closest('#nodeEditorModal .ne-zone-cards') : null;
    if (!container) {
      var zone = target && target.closest ? target.closest('#nodeEditorModal .ne-zone') : null;
      container = zone ? zone.querySelector('.ne-zone-cards') : null;
    }
    if (!container) return;
    var zoneName = zoneNameForContainer(container);
    var before = getDropTarget(container, y, card);
    if (before && before !== card) container.insertBefore(card, before);
    else if (!before && card.parentElement !== container) container.appendChild(card);
    else if (!before) container.appendChild(card);
    syncCardZoneState(card, zoneName);
  }

  function startPointerDrag(card, ev) {
    if (ev.button !== 0) return;
    if (ev.target && ev.target.closest('.ne-field-vis, .ne-field-label-input, input, textarea, select, button')) return;
    _pointerDrag = {
      card: card,
      startX: ev.clientX,
      startY: ev.clientY,
      active: false,
    };
    _draggingNodeKey = card.dataset.key || '';
  }

  function startTouchDrag(card, ev) {
    if (!ev.touches || ev.touches.length !== 1) return;
    if (ev.target && ev.target.closest('.ne-field-vis, .ne-field-label-input, input, textarea, select, button')) return;
    var touch = ev.touches[0];
    _pointerDrag = {
      card: card,
      startX: touch.clientX,
      startY: touch.clientY,
      active: false,
      touchId: touch.identifier,
    };
    _draggingNodeKey = card.dataset.key || '';
  }

  function onPointerMove(ev) {
    if (!_pointerDrag || !_pointerDrag.card) return;
    var dx = ev.clientX - _pointerDrag.startX;
    var dy = ev.clientY - _pointerDrag.startY;
    if (!_pointerDrag.active) {
      if (Math.abs(dx) + Math.abs(dy) < 6) return;
      _pointerDrag.active = true;
      _pointerDrag.card.classList.add('dragging', 'pointer-dragging');
      document.body.classList.add('node-dragging-active');
    }
    ev.preventDefault();
    moveCardToPoint(_pointerDrag.card, ev.clientX, ev.clientY);
  }

  function onTouchMove(ev) {
    if (!_pointerDrag || !_pointerDrag.card || !ev.touches || !ev.touches.length) return;
    var touch = null;
    for (var i = 0; i < ev.touches.length; i++) {
      if (ev.touches[i].identifier === _pointerDrag.touchId) {
        touch = ev.touches[i];
        break;
      }
    }
    if (!touch) return;
    var dx = touch.clientX - _pointerDrag.startX;
    var dy = touch.clientY - _pointerDrag.startY;
    if (!_pointerDrag.active) {
      if (Math.abs(dx) + Math.abs(dy) < 10) return;
      _pointerDrag.active = true;
      _pointerDrag.card.classList.add('dragging', 'pointer-dragging');
      document.body.classList.add('node-dragging-active');
    }
    ev.preventDefault();
    moveCardToPoint(_pointerDrag.card, touch.clientX, touch.clientY);
  }

  function endPointerDrag() {
    if (!_pointerDrag) return;
    var card = _pointerDrag.card;
    if (card) {
      card.classList.remove('dragging', 'pointer-dragging');
      syncCardZoneState(card, zoneNameForContainer(card.parentElement));
      if (_pointerDrag.active) {
        card._dragJustEnded = true;
        setTimeout(function() { card._dragJustEnded = false; }, 0);
      }
    }
    document.body.classList.remove('node-dragging-active');
    _draggingNodeKey = '';
    _pointerDrag = null;
    updateNodeEditorStats();
  }

function resetNodeConfig() {
    if (!_nodeEditorFname) return;
    if (!confirm('恢复为自动分类？已保存的配置将被删除。')) return;
    fetch(API + '/api/workflows/' + encodeURIComponent(_nodeEditorFname) + '/config', { method: 'DELETE' }).then(
      function () {
        openNodeEditor(_nodeEditorFname);
      },
    );
  }
function saveNodeConfig() {
    if (!_nodeEditorFname) return;
    // Build type lookup from analyze data
    var typeMap = {};
    if (_nodeEditorData && _nodeEditorData.nodes) {
      for (var ni = 0; ni < _nodeEditorData.nodes.length; ni++) {
        var node = _nodeEditorData.nodes[ni];
        for (var fi = 0; fi < node.fields.length; fi++) {
          var f = node.fields[fi];
          typeMap[f.key] = { type: f.type, options: f.options, step: f.step, min: f.min, max: f.max };
        }
      }
    }
    var fields = [];
    var zoneMap = {
      neZoneUserInput: 'user_input',
      neZoneAdvanced: 'advanced',
      neZoneOutput: 'output',
      neZoneHidden: 'hidden',
    };
    for (var id in zoneMap) {
      var container = document.getElementById(id);
      if (!container) continue;
      var cards = container.querySelectorAll('.ne-field');
      for (var i = 0; i < cards.length; i++) {
        var card = cards[i];
        var key = card.dataset.key;
        var visible = !card.classList.contains('hidden-field');
        var labelInput = card.querySelector('.ne-field-label-input');
        var label = labelInput ? labelInput.value : '';
        var entry = { key: key, zone: zoneMap[id], visible: visible, label: label, order: i };
        // Copy type + extra props from analyze data
        var meta = typeMap[key];
        if (meta) {
          entry.type = meta.type || 'text';
          if (meta.options) entry.options = meta.options;
          if (meta.step !== undefined) entry.step = meta.step;
          if (meta.min !== undefined) entry.min = meta.min;
          if (meta.max !== undefined) entry.max = meta.max;
        }
        fields.push(entry);
      }
    }
    var config = { version: 1, workflow: _nodeEditorFname, fields: fields };
    fetch(API + '/api/workflows/' + encodeURIComponent(_nodeEditorFname) + '/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(function (r) {
      if (r.ok) {
        closeNodeEditor();
      }
    });
  }
function renderNodeEditor(analyze, config) {
    var allFields = [];
    for (var ni = 0; ni < analyze.nodes.length; ni++) {
      var node = analyze.nodes[ni];
      for (var fi = 0; fi < node.fields.length; fi++) {
        var field = node.fields[fi];
        allFields.push({
          key: field.key,
          node_id: node.node_id,
          node_title: node.title,
          class_type: node.class_type,
          field: field.field,
          type: field.type,
          label: field.label,
          value: field.value,
          zone: field.zone,
          visible: field.visible,
        });
      }
    }
    if (config && config.fields) {
      for (var ci = 0; ci < config.fields.length; ci++) {
        var cfg = config.fields[ci];
        for (var ai = 0; ai < allFields.length; ai++) {
          if (allFields[ai].key === cfg.key) {
            allFields[ai].zone = cfg.zone || allFields[ai].zone;
            if (cfg.visible !== undefined) allFields[ai].visible = cfg.visible;
            allFields[ai].label = cfg.label || allFields[ai].label;
            break;
          }
        }
      }
    }
    var zoneMap = {
      user_input: 'neZoneUserInput',
      advanced: 'neZoneAdvanced',
      output: 'neZoneOutput',
      hidden: 'neZoneHidden',
    };
    for (var zKey in zoneMap) {
      var el = document.getElementById(zoneMap[zKey]);
      if (el) el.innerHTML = '';
    }
    for (var i = 0; i < allFields.length; i++) {
      var f = allFields[i];
      var originalZone = f.zone || 'hidden';
      var effectiveZone = f.visible === false ? 'hidden' : originalZone;
      var container = document.getElementById(zoneMap[effectiveZone] || 'neZoneHidden');
      if (!container) continue;
      var card = document.createElement('div');
      card.className = 'ne-field' + (f.visible ? '' : ' hidden-field');
      card.draggable = false;
      card.dataset.key = f.key;
      card.dataset.zone = effectiveZone;
      card.dataset.prevZone = originalZone !== 'hidden' ? originalZone : 'advanced';
      var valPreview = f.value !== undefined && f.value !== null ? String(f.value).substring(0, 80) : '';
      var visIcon = f.visible ? CW.icon('eye') : CW.icon('eye-off');
      card.innerHTML =
        '<div class="ne-field-top">' +
        '<span class="ne-field-node" title="' +
        escA(f.node_title) +
        '">[' +
        escH(f.node_id) +
        '] ' +
        escH(f.class_type) +
        '</span>' +
        '<button class="ne-field-vis" title="' + (f.visible ? '当前可见，点击设为不可见' : '当前不可见，点击设为可见') + '">' +
        visIcon +
        '</button>' +
        '</div>' +
        '<div class="ne-field-name">' +
        escH(f.field) +
        '</div>' +
        '<input class="ne-field-label-input" value="' +
        escA(f.label) +
        '" placeholder="显示名称" data-key="' +
        escA(f.key) +
        '">' +
        (valPreview
          ? '<div class="ne-field-value" title="' + escA(valPreview) + '">' + escH(valPreview) + '</div>'
          : '');
      (function (card, f) {
        card.addEventListener('mousedown', function(ev) {
          startPointerDrag(card, ev);
        });
        card.addEventListener('touchstart', function(ev) {
          startTouchDrag(card, ev);
        }, { passive: true });
        card.addEventListener('dragstart', function (ev) {
          ev.preventDefault();
          if (_nodeEditorCompactMobile) {
            return;
          }
          ev.dataTransfer.setData('text/plain', f.key);
          ev.dataTransfer.effectAllowed = 'move';
          _draggingNodeKey = f.key;
          card.style.opacity = '.4';
          card.classList.add('dragging');
        });
        card.addEventListener('dragend', function () {
          endPointerDrag();
          _draggingNodeKey = '';
          card.style.opacity = '';
          card.classList.remove('dragging');
          syncCardZoneState(card, zoneNameForContainer(card.parentElement));
          updateNodeEditorStats();
        });
        card.addEventListener('click', function(ev) {
          if (card._dragJustEnded) {
            ev.preventDefault();
            ev.stopPropagation();
            return;
          }
          if (!_nodeEditorCompactMobile) return;
          if (ev.target && (ev.target.closest('.ne-field-vis') || ev.target.closest('.ne-field-label-input'))) return;
          card.classList.toggle('expanded');
        });
        card.querySelector('.ne-field-vis').addEventListener('click', function () {
          var isHidden = card.classList.toggle('hidden-field');
          this.innerHTML = isHidden ? CW.icon('eye-off') : CW.icon('eye');
          this.title = isHidden ? '当前不可见，点击设为可见' : '当前可见，点击设为不可见';
          if (isHidden) {
            var currentZone = zoneNameForContainer(card.parentElement);
            if (currentZone !== 'hidden') card.dataset.prevZone = currentZone;
            var hiddenContainer = document.getElementById('neZoneHidden');
            if (hiddenContainer && card.parentElement !== hiddenContainer) hiddenContainer.appendChild(card);
            syncCardZoneState(card, 'hidden');
          } else {
            var targetZone = card.dataset.prevZone && card.dataset.prevZone !== 'hidden' ? card.dataset.prevZone : 'advanced';
            var targetContainer = document.getElementById(zoneIdForName(targetZone));
            if (targetContainer && card.parentElement !== targetContainer) targetContainer.appendChild(card);
            syncCardZoneState(card, targetZone);
          }
          updateNodeEditorStats();
        });
      })(card, f);
      container.appendChild(card);
    }
    for (var zone in zoneMap) {
      (function (zone, id) {
        var el = document.getElementById(id);
        if (!el) return;
        var parent = el.parentElement;
        function allowDrop(ev) {
          if (_nodeEditorCompactMobile) return;
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
          parent.classList.add('drag-over');
          var key = _draggingNodeKey || ev.dataTransfer.getData('text/plain');
          var card = key ? document.querySelector('.ne-field[data-key="' + CSS.escape(key) + '"]') : null;
          if (!card) card = document.querySelector('#nodeEditorModal .ne-field.dragging');
          if (!card) return;
          var before = getDropTarget(el, ev.clientY, card);
          if (before && before !== card) el.insertBefore(card, before);
          else if (!before && card.parentElement !== el) el.appendChild(card);
          else if (!before) el.appendChild(card);
          syncCardZoneState(card, zone);
        }
        parent.addEventListener('dragover', allowDrop);
        el.addEventListener('dragover', allowDrop);
        parent.addEventListener('dragleave', function () {
          parent.classList.remove('drag-over');
        });
        function handleDrop(ev) {
          if (_nodeEditorCompactMobile) return;
          ev.preventDefault();
          parent.classList.remove('drag-over');
          var key = _draggingNodeKey || ev.dataTransfer.getData('text/plain');
          if (!key) return;
          var card = document.querySelector('.ne-field[data-key="' + CSS.escape(key) + '"]');
          if (card) {
            var before = getDropTarget(el, ev.clientY, card);
            if (before && before !== card) el.insertBefore(card, before);
            else if (!before) el.appendChild(card);
            syncCardZoneState(card, zone);
          }
          _draggingNodeKey = '';
          updateNodeEditorStats();
        }
        parent.addEventListener('drop', handleDrop);
        el.addEventListener('drop', handleDrop);
      })(zone, zoneMap[zone]);
    }
    updateNodeEditorStats();
    setTimeout(updateNodeEditorStats, 0);
  }
function closeNodeEditor() {
    $('#nodeEditorModal').classList.remove('open');
    _nodeEditorData = null;
    _nodeEditorConfig = null;
  }
function openNodeEditor(fname) {
    _nodeEditorFname = fname;
    $('#nodeEditorTitle').textContent = '节点编辑: ' + fname.replace('.json', '');
    Promise.all([
      fetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/analyze').then(function (r) {
        return r.json();
      }),
      fetch(API + '/api/workflows/' + encodeURIComponent(fname) + '/config')
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .catch(function () {
          return null;
        }),
    ]).then(function (results) {
      _nodeEditorData = results[0];
      _nodeEditorConfig = results[1];
      updateNodeCompactState();
      renderNodeEditor(results[0], results[1]);
      $('#nodeEditorModal').classList.add('open');
      setTimeout(updateNodeEditorStats, 0);
    });
  }

  // ── Register on window.CW ──
  if (!window.CW) window.CW = {};
  window.CW.openNodeEditor = openNodeEditor;
  window.CW.closeNodeEditor = closeNodeEditor;
  window.CW.saveNodeConfig = saveNodeConfig;
  window.CW.resetNodeConfig = resetNodeConfig;
  window.addEventListener('resize', updateNodeCompactState);
  document.addEventListener('mousemove', onPointerMove, true);
  document.addEventListener('mouseup', endPointerDrag, true);
  document.addEventListener('touchmove', onTouchMove, { passive: false, capture: true });
  document.addEventListener('touchend', endPointerDrag, true);
  document.addEventListener('touchcancel', endPointerDrag, true);
  window.addEventListener('mouseup', endPointerDrag, true);
  window.addEventListener('blur', endPointerDrag);
})();
