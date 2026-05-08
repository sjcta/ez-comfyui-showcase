/**
 * Node Editor Module
 * Extracted from app.js v3.10
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs;
  _nodeEditorConfig = null;
  _nodeEditorData = null;
  _nodeEditorFname = '';

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
      var container = document.getElementById(zoneMap[f.zone] || 'neZoneHidden');
      if (!container) continue;
      var card = document.createElement('div');
      card.className = 'ne-field' + (f.visible ? '' : ' hidden-field');
      card.draggable = true;
      card.dataset.key = f.key;
      var valPreview = f.value !== undefined && f.value !== null ? String(f.value).substring(0, 80) : '';
      var visIcon = f.visible ? '👁️' : '🚫';
      card.innerHTML =
        '<div class="ne-field-top">' +
        '<span class="ne-field-node" title="' +
        escA(f.node_title) +
        '">[' +
        escH(f.node_id) +
        '] ' +
        escH(f.class_type) +
        '</span>' +
        '<button class="ne-field-vis" title="切换可见性">' +
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
        card.addEventListener('dragstart', function (ev) {
          ev.dataTransfer.setData('text/plain', f.key);
          ev.dataTransfer.effectAllowed = 'move';
          card.style.opacity = '.4';
        });
        card.addEventListener('dragend', function () {
          card.style.opacity = '';
        });
        card.querySelector('.ne-field-vis').addEventListener('click', function () {
          var isHidden = card.classList.toggle('hidden-field');
          this.textContent = isHidden ? '🚫' : '👁️';
        });
      })(card, f);
      container.appendChild(card);
    }
    for (var zone in zoneMap) {
      (function (zone, id) {
        var el = document.getElementById(id);
        if (!el) return;
        var parent = el.parentElement;
        parent.addEventListener('dragover', function (ev) {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'move';
          parent.classList.add('drag-over');
        });
        parent.addEventListener('dragleave', function () {
          parent.classList.remove('drag-over');
        });
        parent.addEventListener('drop', function (ev) {
          ev.preventDefault();
          parent.classList.remove('drag-over');
          var key = ev.dataTransfer.getData('text/plain');
          if (!key) return;
          var card = document.querySelector('.ne-field[data-key="' + CSS.escape(key) + '"]');
          if (card) el.appendChild(card);
        });
      })(zone, zoneMap[zone]);
    }
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
      renderNodeEditor(results[0], results[1]);
      $('#nodeEditorModal').classList.add('open');
    });
  }

  // ── Register on window.CW ──
  if (!window.CW) window.CW = {};
  window.CW.openNodeEditor = openNodeEditor;
  window.CW.closeNodeEditor = closeNodeEditor;
  window.CW.saveNodeConfig = saveNodeConfig;
  window.CW.resetNodeConfig = resetNodeConfig;
})();
