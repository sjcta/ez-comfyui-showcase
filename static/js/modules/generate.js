/**
 * Generate Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
  var API = A.API, jobs = A.jobs, jobFields = A.jobFields, historyItems = A.historyItems;
  var PROMPT_TRANSLATION_CACHE_KEY = 'cw_prompt_translation_cache_v1';
  var _promptTranslationCache = _loadPromptTranslationCache();

  function _normalizePromptCacheText(text) {
    return String(text || '').trim().replace(/\s+/g, ' ');
  }

  function _detectPromptTargetLanguage(text) {
    return /[\u4e00-\u9fff]/.test(String(text || '')) ? 'en' : 'zh';
  }

  function _looksLikeJsonPrompt(text) {
    try {
      return !!JSON.parse(String(text || '').trim());
    } catch (e) {
      return false;
    }
  }

  function _promptTranslationCacheKey(text, target) {
    return String(target || '') + '\n' + _normalizePromptCacheText(text);
  }

  function _loadPromptTranslationCache() {
    try {
      var raw = sessionStorage.getItem(PROMPT_TRANSLATION_CACHE_KEY);
      var parsed = raw ? JSON.parse(raw) : null;
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function _savePromptTranslationCache() {
    try {
      var keys = Object.keys(_promptTranslationCache);
      if (keys.length > 160) {
        keys.slice(0, keys.length - 160).forEach(function(key) { delete _promptTranslationCache[key]; });
      }
      sessionStorage.setItem(PROMPT_TRANSLATION_CACHE_KEY, JSON.stringify(_promptTranslationCache));
    } catch (e) {}
  }

  function _getPromptTranslationCache(text, target) {
    var entry = _promptTranslationCache[_promptTranslationCacheKey(text, target)];
    return entry && entry.text ? String(entry.text).trim() : '';
  }

  function _rememberPromptTranslationPair(source, targetLang, translated) {
    var src = String(source || '').trim();
    var dst = String(translated || '').trim();
    var lang = targetLang === 'zh' ? 'zh' : 'en';
    if (!src || !dst || src === dst) return;
    _promptTranslationCache[_promptTranslationCacheKey(src, lang)] = { text: dst, ts: Date.now() };
    _promptTranslationCache[_promptTranslationCacheKey(dst, lang === 'en' ? 'zh' : 'en')] = { text: src, ts: Date.now() };
    _savePromptTranslationCache();
  }

  function registerPromptTranslationPair(promptZh, promptEn) {
    var zh = String(promptZh || '').trim();
    var en = String(promptEn || '').trim();
    if (!zh || !en) return;
    _rememberPromptTranslationPair(zh, 'en', en);
  }

  var FLUX2_MAX_PIXELS = 2048 * 2048;
  var DEFAULT_SIZE_LIMITS = { maxSide: 1920, maxPixels: null, multiple: 64, minSide: 256, inputMax: 2048 };
  var DEFAULT_RATIO_BASE_PRESETS = [
    [1024, 1024, '1:1', '22px', '22px'],
    [1536, 1024, '3:2', '26px', '17px'],
    [1920, 1080, '16:9', '28px', '16px'],
    [1536, 1152, '4:3', '24px', '18px'],
    [1152, 1536, '3:4', '18px', '24px'],
    [1024, 1536, '2:3', '16px', '24px'],
    [1080, 1920, '9:16', '14px', '24px']
  ];
  var FLUX2_RATIO_BASE_PRESETS = [
    [2048, 2048, '1:1', '22px', '22px'],
    [3072, 2048, '3:2', '26px', '17px'],
    [3840, 2160, '16:9', '28px', '16px'],
    [3072, 2304, '4:3', '24px', '18px'],
    [2304, 3072, '3:4', '18px', '24px'],
    [2048, 3072, '2:3', '16px', '24px'],
    [2160, 3840, '9:16', '14px', '24px']
  ];
  var QWEN_IMAGE_RATIO_PRESETS = [
    [1328, 1328, '1:1', '22px', '22px'],
    [1584, 1056, '3:2', '26px', '17px'],
    [1664, 928, '16:9', '28px', '16px'],
    [1472, 1140, '4:3', '24px', '18px'],
    [1140, 1472, '3:4', '18px', '24px'],
    [1056, 1584, '2:3', '16px', '24px'],
    [928, 1664, '9:16', '14px', '24px']
  ];
  var Z_IMAGE_RATIO_PRESETS = [
    [1024, 1024, '1:1', '22px', '22px'],
    [1248, 832, '3:2', '26px', '17px'],
    [1280, 720, '16:9', '28px', '16px'],
    [1152, 864, '4:3', '24px', '18px'],
    [864, 1152, '3:4', '18px', '24px'],
    [832, 1248, '2:3', '16px', '24px'],
    [720, 1280, '9:16', '14px', '24px']
  ];

function _hasFieldClass(fields, pattern) {
    return (fields || A._wfFieldMeta || []).some(function(f) {
      return f && pattern.test(String(f.class_type || ''));
    });
  }

function _workflowSizeLimits(fields) {
    var workflow = String(A.currentWF || '');
    var hasLtxVideoLatent = _hasFieldClass(fields, /EmptyLTXVLatentVideo|LTXV/i);
    if (/ltx|sulphur/i.test(workflow) || hasLtxVideoLatent) {
      return { name: 'ltx-video', maxSide: 1280, maxPixels: null, multiple: 32, minSide: 192, minWidth: 256, minHeight: 192, inputMax: 1280, basePresets: DEFAULT_RATIO_BASE_PRESETS };
    }
    var hasFlux2Scheduler = _hasFieldClass(fields, /^Flux2Scheduler$/);
    if (/flux[\s_.-]*2/i.test(workflow) || hasFlux2Scheduler) {
      return { name: 'flux2', maxSide: null, maxPixels: FLUX2_MAX_PIXELS, multiple: 16, minSide: 64, inputMax: 4096, basePresets: FLUX2_RATIO_BASE_PRESETS };
    }
    if (/qwen|千问/i.test(workflow) || _hasFieldClass(fields, /QwenImage/i)) {
      return { name: 'qwen-image', maxSide: null, maxPixels: 1328 * 1328, multiple: 4, minSide: 256, inputMax: 2048, presets: QWEN_IMAGE_RATIO_PRESETS };
    }
    if (/z[-_ ]?image|z[-_ ]?xxx|nunchaku/i.test(workflow) || _hasFieldClass(fields, /ZImage|NunchakuZImage/i)) {
      return { name: 'z-image', maxSide: null, maxPixels: 1024 * 1024, multiple: 32, minSide: 256, inputMax: 1536, presets: Z_IMAGE_RATIO_PRESETS };
    }
    if (/ernie/i.test(workflow) || _hasFieldClass(fields, /ERNIE/i)) {
      return { name: 'ernie-image', maxSide: 2048, maxPixels: null, multiple: 16, minSide: 64, inputMax: 2048, basePresets: FLUX2_RATIO_BASE_PRESETS };
    }
    return DEFAULT_SIZE_LIMITS;
  }

function _limitDimensions(w, h, limits) {
    limits = limits || DEFAULT_SIZE_LIMITS;
    var multiple = Math.max(1, parseInt(limits.multiple || 64, 10));
    var minSide = Math.max(multiple, parseInt(limits.minSide || multiple, 10));
    var minWidth = Math.max(multiple, parseInt(limits.minWidth || minSide, 10));
    var minHeight = Math.max(multiple, parseInt(limits.minHeight || minSide, 10));
    var width = Math.max(minWidth, parseInt(w, 10) || minWidth);
    var height = Math.max(minHeight, parseInt(h, 10) || minHeight);
    var scale = 1;
    if (limits.maxSide) scale = Math.min(scale, Number(limits.maxSide) / Math.max(width, height));
    if (limits.maxPixels) scale = Math.min(scale, Math.sqrt(Number(limits.maxPixels) / Math.max(1, width * height)));
    width = Math.max(minWidth, Math.floor((width * scale) / multiple) * multiple);
    height = Math.max(minHeight, Math.floor((height * scale) / multiple) * multiple);
    while (limits.maxPixels && width * height > limits.maxPixels) {
      if (width >= height && width > minWidth) width -= multiple;
      else if (height > minHeight) height -= multiple;
      else break;
    }
    return [width, height];
  }

function _scaledRatioPreset(w, h, label, shapeW, shapeH, limits) {
    var size = _limitDimensions(w, h, limits);
    return [size[0], size[1], label, shapeW, shapeH];
  }

function _ratioPresetsForLimits(limits) {
    if (limits && limits.presets) return limits.presets;
    var source = (limits && limits.basePresets) || DEFAULT_RATIO_BASE_PRESETS;
    return source.map(function(p) {
      return _scaledRatioPreset(p[0], p[1], p[2], p[3], p[4], limits);
    });
  }

function _applyCurrentSizeLimit() {
    var wi = $('#widthInput'), hi = $('#heightInput');
    if (!wi || !hi) return;
    var size = _limitDimensions(wi.value, hi.value, _workflowSizeLimits());
    wi.value = size[0];
    hi.value = size[1];
    highlightRatio(size[0], size[1]);
  }

function initRatioGrid() {
    // Ratio buttons are created dynamically by renderQuickForm - guard
    var btns = $$('.ratio-btn');
    if (!btns || !btns.length) return;
    btns.forEach(function(b) {
      b.addEventListener('click', function() {
        var allBtns = $$('.ratio-btn');
        allBtns.forEach(function(x) { x.classList.remove('active'); });
        b.classList.add('active');
        $('#widthInput').value = b.dataset.w;
        $('#heightInput').value = b.dataset.h;
        _applyCurrentSizeLimit();
      });
    });
    // Sync: if user manually changes inputs, clear active highlight
    ['#widthInput', '#heightInput'].forEach(function(sel) {
      var el = $(sel);
      if (el) {
        el.addEventListener('input', function() {
          var w = parseInt($('#widthInput').value) || 0,
            h = parseInt($('#heightInput').value) || 0;
          highlightRatio(w, h);
        });
        el.addEventListener('change', _applyCurrentSizeLimit);
        el.addEventListener('blur', _applyCurrentSizeLimit);
      }
    });
  }

function highlightRatio(w, h) {
    var target = w / h;
    var best = null, bestDiff = Infinity;
    $$('.ratio-btn').forEach((b) => {
      var bw = parseInt(b.dataset.w), bh = parseInt(b.dataset.h);
      var ratio = bw / bh;
      var diff = Math.abs(ratio - target);
      if (diff < bestDiff) { bestDiff = diff; best = b; }
    });
    $$('.ratio-btn').forEach((b) => b.classList.toggle('active', bestDiff < 0.01 && b === best));
  }

function scaleDim(w, h, maxSide = 1920) {
    return _limitDimensions(w, h, Object.assign({}, DEFAULT_SIZE_LIMITS, { maxSide: maxSide }));
  }

function _setPromptInputValue(value) {
    var pi = $('#promptInput');
    if (!pi) return null;
    pi.value = value || '';
    pi.dispatchEvent(new Event('input', { bubbles: true }));
    if (window.CW && CW.syncClearPromptButton) CW.syncClearPromptButton();
    return pi;
  }

function _getSeedInput() {
    return document.querySelector('.seed-group input[type="number"]');
  }

function _setSeedRandomEnabled(enabled) {
    $$('.btn-dice[data-seed-random]').forEach(function(btn) {
      btn.classList.toggle('is-active', !!enabled);
      btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    });
  }

function _isSeedRandomEnabled() {
    var btn = document.querySelector('.btn-dice[data-seed-random]');
    return !!(btn && btn.classList.contains('is-active'));
  }

function _getManualSeedValue() {
    var input = _getSeedInput();
    if (!input) return null;
    var value = String(input.value || '').trim();
    if (!value) return null;
    var seed = parseInt(value, 10);
    return Number.isFinite(seed) ? seed : null;
  }

function _hasRestorableSeedFieldValues(values) {
    return Object.keys(values || {}).some(function(key) {
      return /::(?:seed|noise_seed)$/.test(key);
    });
  }

function _normalizeFieldMeta(fields, workflowName) {
    var normalized = (fields || []).map(function(f) {
      return {
        key: f.key || (f.node_id + '::' + f.field),
        node_id: f.node_id,
        class_type: f.class_type,
        field: f.field,
        zone: f.zone,
        visible: f.visible !== false,
        type: f.type,
        label: f.label,
        value: f.value,
        options: f.options,
        step: f.step,
        min: f.min,
        max: f.max,
        order: f.order,
      };
    });
    A._wfFieldMeta = normalized;
    A._wfFieldWorkflow = workflowName || A.currentWF || '';
    window.__APP__._wfFieldMeta = normalized;
    window.__APP__._wfFieldWorkflow = A._wfFieldWorkflow;
    return normalized;
  }

function _numberAttr(name, value) {
    return value === undefined || value === null || value === ''
      ? ''
      : ' ' + name + '="' + escA(String(value)) + '"';
  }

function _hasCurrentFieldCache() {
    return !!(A._wfFieldMeta && A._wfFieldMeta.length && A._wfFieldWorkflow === A.currentWF);
  }

async function _getSubmitFieldsMeta() {
    if (_hasCurrentFieldCache()) return A._wfFieldMeta;
    try {
      var fr = await fetch(`${API}/api/workflows/${encodeURIComponent(A.currentWF)}/fields`);
      if (!fr.ok) throw new Error('字段读取失败');
      var fd = await fr.json();
      return _normalizeFieldMeta(fd.fields || [], A.currentWF);
    } catch (e) {
      if (_hasCurrentFieldCache()) return A._wfFieldMeta;
      throw e;
    }
  }

function _isPromptSubmitField(f) {
    if (!f) return false;
    var zone = f.zone || '';
    if (zone === 'user_input') return _isPromptLikeField(f);
    return !f.zone && _isPromptLikeField(f);
  }

function _isPromptLikeField(f) {
    if (!f) return false;
    var cls = String(f.class_type || '');
    var field = String(f.field || '').toLowerCase();
    if (f.type === 'textarea' || cls.indexOf('TextEncode') >= 0) return true;
    if (cls === 'CLIPTextEncode' && field === 'text') return true;

    var label = String(f.label || '').toLowerCase();
    var title = String(f.node_title || '').toLowerCase();
    var promptNamed = label.indexOf('prompt') >= 0 || label.indexOf('提示词') >= 0 || title.indexOf('prompt') >= 0 || title.indexOf('提示词') >= 0;
    var stringLike = f.type === 'text' || f.type === 'textarea' || cls.indexOf('String') >= 0 || cls.indexOf('Text') >= 0;
    var promptField = field === 'text' || field === 'prompt' || field === 'value' || field === 'positive' || field === 'negative';
    return promptNamed && stringLike && promptField;
  }

function _isVideoPromptWorkflow(fields) {
    var workflow = String(A.currentWF || '');
    var meta = (A._wfMeta || {})[workflow] || {};
    var tags = meta.tags || [];
    if (tags.some(function(t) { return /视频/.test(String(t || '')); })) return true;
    var typeTag = window.CW && CW.getWFType ? CW.getWFType(workflow) : null;
    if (typeTag && /视频/.test(String(typeTag.text || ''))) return true;
    if (/(\bi2v\b|\bt2v\b|ltx|sulphur|seedance|video|视频)/i.test(workflow)) return true;
    return (fields || A._wfFieldMeta || []).some(function(f) {
      if (!f) return false;
      var cls = String(f.class_type || '');
      return /LoadVideo|SaveVideo|EmptyLTXVLatentVideo|LTXV|VHS_/i.test(cls) || f.type === 'video_mode';
    });
  }

function _promptOptimizeMode(fields) {
    return _isVideoPromptWorkflow(fields) ? 'video_script' : 'image';
  }

function _promptOptimizeCopy(fields) {
    var isVideo = _promptOptimizeMode(fields) === 'video_script';
    return {
      mode: isVideo ? 'video_script' : 'image',
      label: isVideo ? '视频脚本优化' : '提示词优化',
      loading: isVideo ? '脚本优化中' : '优化中',
      empty: isVideo ? '先输入视频脚本' : '先输入提示词',
      error: isVideo ? '视频脚本优化失败' : '提示词优化失败',
      done: isVideo ? '视频脚本已优化' : '提示词已优化',
      doneJson: isVideo ? '视频脚本已优化' : '提示词已优化，JSON 版本已生成'
    };
  }

function _currentFieldValueForMeta(f) {
    var key = _fieldKeyForMeta(f);
    if (!key) return null;
    var el = document.querySelector('#quickFormFields [data-key="' + key + '"], #advFields [data-key="' + key + '"]');
    if (el) return _readFieldControlValue(el);
    return f ? f.value : null;
  }

function _videoScriptTimingContext() {
    var context = {};
    var fields = A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      var label = String(f.label || '');
      var field = String(f.field || '');
      var key = _fieldKeyForMeta(f);
      var haystack = (label + ' ' + field + ' ' + key).toLowerCase();
      var raw = _currentFieldValueForMeta(f);
      var value = parseFloat(raw);
      if (!isFinite(value) || value <= 0) continue;
      if (/帧率|fps|frame[_ -]?rate|framerate/.test(haystack)) {
        context.fps = value;
      } else if (/长度.*秒|秒|duration|seconds|duration_sec/.test(haystack)) {
        context.duration_seconds = value;
      } else if (/帧数|总帧|frames[_ -]?number|frame[_ -]?count|num[_ -]?frames/.test(haystack)) {
        context.frame_count = value;
      }
    }
    if (!context.duration_seconds && context.frame_count && context.fps) {
      context.duration_seconds = Math.round((context.frame_count / context.fps) * 100) / 100;
    }
    if (A.currentWF) context.workflow = A.currentWF;
    return context;
  }

function _promptTextValue(value) {
    if (typeof value !== 'string') return '';
    return value.trim();
  }

function _fieldKeyForMeta(f) {
    if (!f) return '';
    return f.key || (String(f.node_id || '') + '::' + String(f.field || ''));
  }

function _isSeedVR2VideoUpscaleWorkflow(fieldsMeta) {
    var workflow = String(A.currentWF || '');
    if (/seedvr2.*video.*upscale|seedvr2.*视频.*放大/i.test(workflow)) return true;
    var fields = fieldsMeta || A._wfFieldMeta || [];
    var hasVideo = false, hasSeedVR2 = false;
    for (var i = 0; i < fields.length; i++) {
      var cls = String((fields[i] || {}).class_type || '');
      if (cls === 'LoadVideo') hasVideo = true;
      if (cls === 'SeedVR2VideoUpscaler') hasSeedVR2 = true;
    }
    return hasVideo && hasSeedVR2;
  }

function _videoUpscaleResolutionField(fieldsMeta) {
    var fields = fieldsMeta || A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if (f.class_type === 'SeedVR2VideoUpscaler' && f.field === 'resolution') return _fieldKeyForMeta(f);
    }
    for (var j = 0; j < fields.length; j++) {
      var candidate = fields[j] || {};
      if (candidate.field === 'resolution') return _fieldKeyForMeta(candidate);
    }
    return '';
  }

function _roundToMultiple(value, multiple) {
    var step = Math.max(1, parseInt(multiple || 1, 10));
    return Math.max(step, Math.round((Number(value) || 0) / step) * step);
  }

function _getRefVideoMetadata() {
    var valueInput = $('#refVideoValue');
    var preview = $('#refVideoPreview');
    var width = parseInt(
      (valueInput && valueInput.getAttribute('data-video-width')) ||
      (preview && (preview.getAttribute('data-video-width') || preview.videoWidth)) ||
      0,
      10
    ) || 0;
    var height = parseInt(
      (valueInput && valueInput.getAttribute('data-video-height')) ||
      (preview && (preview.getAttribute('data-video-height') || preview.videoHeight)) ||
      0,
      10
    ) || 0;
    return { width: width, height: height };
  }

function _applyVideoUpscaleLongEdgeResolution(fields, fieldsMeta) {
    if (!_isSeedVR2VideoUpscaleWorkflow(fieldsMeta)) return null;
    var resolutionKey = _videoUpscaleResolutionField(fieldsMeta);
    if (!resolutionKey) return null;
    var targetLongEdge = parseInt(fields[resolutionKey], 10) || 0;
    if (targetLongEdge <= 0) return null;
    var meta = _getRefVideoMetadata();
    var width = parseInt(meta.width, 10) || 0;
    var height = parseInt(meta.height, 10) || 0;
    if (!width || !height) return null;
    var sourceRatio = Math.min(width, height) / Math.max(width, height);
    var computedResolution = _roundToMultiple(targetLongEdge * sourceRatio, 16);
    computedResolution = Math.max(512, Math.min(targetLongEdge, computedResolution));
    fields[resolutionKey] = computedResolution;
    fields.__video_upscale_long_edge = targetLongEdge;
    fields.__video_upscale_source_size = width + 'x' + height;
    return {
      key: resolutionKey,
      targetLongEdge: targetLongEdge,
      computedResolution: computedResolution,
      width: width,
      height: height
    };
  }

function _promptFromReusableFields(fieldValues, fieldsMeta) {
    var values = fieldValues || {};
    var fields = fieldsMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      if (!_isPromptSubmitField(f)) continue;
      var metaKey = _fieldKeyForMeta(f);
      if (!Object.prototype.hasOwnProperty.call(values, metaKey)) continue;
      var metaValue = _promptTextValue(values[metaKey]);
      if (metaValue) return metaValue;
    }
    var entries = Object.entries(values);
    var predicates = [
      function(field) { return field.indexOf('prompt') >= 0 || field.indexOf('positive') >= 0; },
      function(field) { return field === 'value'; },
      function(field) { return field === 'text'; }
    ];
    for (var p = 0; p < predicates.length; p++) {
      for (var j = 0; j < entries.length; j++) {
        var key = String(entries[j][0] || '');
        var field = key.split('::').pop().toLowerCase();
        if (!predicates[p](field)) continue;
        var text = _promptTextValue(entries[j][1]);
        if (text) return text;
      }
    }
    return '';
  }

function _isFlux2SchedulerSizeField(f, dim) {
    return !!(f && f.class_type === 'Flux2Scheduler' && f.field === dim);
  }

function _isLatentDimensionField(f, dim) {
    var cls = String((f && f.class_type) || '');
    return !!(f && f.field === dim && (cls.indexOf('LatentImage') >= 0 || cls.indexOf('LatentVideo') >= 0));
  }

function _isVideoModeField(f) {
    return !!(f && f.type === 'video_mode');
  }

function _readFieldControlValue(el) {
    if (!el) return '';
    if (el.type === 'checkbox') return !!el.checked;
    if (el.dataset && (el.dataset.type === 'video_mode' || el.dataset.type === 'bool')) {
      return String(el.value) === 'true';
    }
    if (el.type === 'number' || el.dataset.type === 'number') return parseFloat(el.value) || 0;
    return el.value;
  }

function _getVideoModeBypassInput() {
    return document.querySelector('#quickFormFields [data-type="video_mode"]');
  }

function _isVideoI2VMode() {
    var el = _getVideoModeBypassInput();
    return !!(el && String(el.value) === 'false');
  }

function _syncVideoModeUi() {
    var input = _getVideoModeBypassInput();
    if (!input) return;
    var mode = _isVideoI2VMode() ? 'i2v' : 't2v';
    $$('.video-mode-btn').forEach(function(btn) {
      var active = btn.dataset.mode === mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    $$('.ref-image-section').forEach(function(section) {
      var show = mode === 'i2v';
      section.style.display = show ? '' : 'none';
      section.classList.toggle('is-required', show);
      section.setAttribute('aria-hidden', show ? 'false' : 'true');
    });
  }

function setVideoMode(mode) {
    var input = _getVideoModeBypassInput();
    if (!input) return;
    input.value = mode === 'i2v' ? 'false' : 'true';
    _syncVideoModeUi();
  }

function _initVideoModeControl() {
    $$('.video-mode-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        setVideoMode(btn.dataset.mode || 't2v');
      });
    });
    _syncVideoModeUi();
  }

function _setFieldControlValue(key, value) {
    var el = document.querySelector('#advFields [data-key="' + key + '"], #quickFormFields [data-key="' + key + '"]');
    if (!el) return false;
    if (el.type === 'checkbox') {
      el.checked = !!value && value !== 'false' && value !== 'False';
      el.value = el.checked;
    } else {
      el.value = value;
    }
    if (el.dataset && el.dataset.type === 'video_mode') _syncVideoModeUi();
    return true;
  }

function toggleSeedRandom(btnEl) {
    var btn = btnEl || document.querySelector('.btn-dice[data-seed-random]');
    if (!btn) return;
    _setSeedRandomEnabled(!btn.classList.contains('is-active'));
  }

function _clearPromptOptimizationVariants() {
    var old = $('#promptOptimizeVariants');
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }

function _showPromptOptimizationVariants(data) {
    var optimized = String((data && (data.optimized_prompt || data.cleaned_prompt)) || '').trim();
    var structured = String((data && data.structured_prompt_json) || '').trim();
    if (!optimized || !structured) {
      _clearPromptOptimizationVariants();
      return;
    }
    var promptField = $('#promptInput');
    var promptGroup = promptField && promptField.closest ? promptField.closest('.prompt-fg') : null;
    var labelRow = promptGroup ? promptGroup.querySelector('.prompt-label-row') : null;
    if (!labelRow) return;
    _clearPromptOptimizationVariants();
    var panel = document.createElement('div');
    panel.id = 'promptOptimizeVariants';
    panel.className = 'prompt-variant-panel';
    panel.innerHTML = ''
      + '<button class="prompt-variant-btn active" type="button" data-kind="text">纯词汇</button>'
      + '<button class="prompt-variant-btn" type="button" data-kind="json">JSON格式</button>';
    var buttons = panel.querySelectorAll('.prompt-variant-btn');
    function activate(kind) {
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].classList.toggle('active', buttons[i].getAttribute('data-kind') === kind);
      }
      _setPromptInputValue(kind === 'json' ? structured : optimized);
    }
    for (var j = 0; j < buttons.length; j++) {
      buttons[j].addEventListener('click', function() {
        activate(this.getAttribute('data-kind') || 'text');
      });
    }
    labelRow.appendChild(panel);
  }

function _quickGenerationLabel() {
    var prompt = ($('#promptInput') || {}).value || '';
    if (prompt.trim()) return prompt.slice(0, 300);
    var meta = (A._wfMeta || {})[A.currentWF] || {};
    var tags = meta.tags || [];
    var typeTag = window.CW && CW.getWFType ? CW.getWFType(A.currentWF || '') : null;
    var isUpscale = (typeTag && typeTag.text === '放大') || tags.indexOf('放大') >= 0 || /upscale|seedvr/i.test(A.currentWF || '');
    if (!isUpscale) return '';
    var resolution = 0;
    var fields = A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if (f.field === 'resolution') {
        var el = document.querySelector('#advFields [data-key="' + f.key + '"], #quickFormFields [data-key="' + f.key + '"]');
        resolution = parseInt((el && el.value) || f.value || 0, 10) || 0;
        break;
      }
    }
    if (resolution >= 3840) return '4K 放大';
    if (resolution >= 1920) return '2K 放大';
    return resolution > 0 ? (resolution + 'P 放大') : '放大';
  }

  function _historyKey(item) {
    return String((item && (item.id || item.filename || item.thumb)) || '');
  }

  function _historyItemByKey(key) {
    key = String(key || '');
    if (!key) return null;
    for (var i = 0; i < historyItems.length; i++) {
      if (_historyKey(historyItems[i]) === key) return historyItems[i];
    }
    return null;
  }

async function fillFormFromHistory(idx, key) {
    const h = _historyItemByKey(key) || historyItems[idx];
    if (!h) return;
    if (!h.workflow) return;
    // Always find and switch to the correct workflow + tab
    var targetWf = null;
    // 1. Direct match in current workflow cards
    var wfExists = [...$$('.wf-card')].some(el => el.dataset.name === h.workflow);
    if (wfExists) {
      targetWf = h.workflow;
    }
    // 2. Try server-side find-closest (by wf_id or tags)
    if (!targetWf) {
      try {
        var params = new URLSearchParams();
        if (h.wf_id) params.set('wf_id', h.wf_id);
        if (h.wf_tags) params.set('wf_tags', JSON.stringify(h.wf_tags));
        params.set('workflow', h.workflow);
        var r = await fetch(API + '/api/workflows/find-closest?' + params.toString());
        if (r.ok) {
          var d = await r.json();
          targetWf = d.filename;
          console.log('[fillFormFromHistory] fuzzy matched:', h.workflow, '→', targetWf, 'by', d.matched_by);
        }
      } catch(e) { console.warn('[fillFormFromHistory] find-closest failed:', e); }
    }
    if (targetWf) {
      var meta = (A._wfMeta || {})[targetWf] || {};
      var tag = window.CW.wfTag ? window.CW.wfTag(targetWf, meta.tags) : null;
      var tabName = tag ? tag.text : '';
      if (!tabName) {
        var tags = meta.tags || [];
        tabName = tags[0] || '全部';
      }
      // Always switch tab (even if same workflow — user may have switched tabs)
      window.CW.switchTab(tabName);
      // Only re-fetch fields if workflow actually changed
      if (targetWf !== A.currentWF) {
        await window.CW.selectWF(targetWf);
      } else if (window.CW.highlightWF) {
        window.CW.highlightWF();
      }
      requestAnimationFrame(function() {
        var card = Array.prototype.slice.call(document.querySelectorAll('.wf-card')).find(function(el) {
          return el.dataset && el.dataset.name === targetWf;
        });
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
      });
    } else {
      console.warn('[fillFormFromHistory] no match for workflow:', h.workflow, '— restoring common fields only');
    }
    var reuseFieldsMeta = [];
    try {
      reuseFieldsMeta = await _getSubmitFieldsMeta();
    } catch (e) {
      reuseFieldsMeta = A._wfFieldMeta || [];
    }
    var reusedPrompt = _promptFromReusableFields(h.field_values || {}, reuseFieldsMeta);
    // Scale dimensions to fit the selected workflow's model-family policy.
    if (h.width && h.height) {
      var wi = $('#widthInput'), hi = $('#heightInput');
      if (wi && hi) {
        const [w, h2] = _limitDimensions(h.width, h.height, _workflowSizeLimits());
        wi.value = w;
        hi.value = h2;
        highlightRatio(w, h2);
      }
    }
    // Restore advanced fields if available
    if (h.field_values) {
      for (const [k, v] of Object.entries(h.field_values)) {
        _setFieldControlValue(k, v);
      }
      // Restore ref image from LoadImage field_values
      for (const [k, v] of Object.entries(h.field_values)) {
        if (k.endsWith('::image') && v) {
          var vInput = document.querySelector('#refImageValue');
          var preview = document.querySelector('#refImagePreview');
          var ph = document.querySelector('#refImagePlaceholder');
          if (vInput) vInput.value = v;
          if (preview) { preview.src = API + '/api/input-image/' + encodeURIComponent(v); preview.style.display = ''; }
          if (ph) ph.style.display = 'none';
          break;
        }
      }
    }
    if (reusedPrompt || h.prompt) {
      _setPromptInputValue(reusedPrompt || h.prompt);
    }
    // Restore seed only for old records that do not have workflow seed fields.
    if (h.seed && !_hasRestorableSeedFieldValues(h.field_values || {})) {
      const seedInput = _getSeedInput();
      if (seedInput) seedInput.value = h.seed;
      _setSeedRandomEnabled(true);
    }
    document.querySelector('.col-left').scrollTop = 0;
  }

async function restoreJob(jobId) {
    // Try local snapshot first (submitted this session)
    const snap = jobFields[jobId];
    if (snap) {
      if (snap.prompt) { _setPromptInputValue(snap.prompt); }
      if (snap.width) { var wi = $('#widthInput'); if (wi) wi.value = snap.width; }
      if (snap.height) { var hi = $('#heightInput'); if (hi) hi.value = snap.height; }
      for (const [k, v] of Object.entries(snap.adv || {})) {
        _setFieldControlValue(k, v);
      }
      if (Object.keys(snap.adv || {}).some(function(k) { return k.endsWith('::seed'); })) _setSeedRandomEnabled(true);
      return;
    }
    // Fallback: restore from server job data
    const j = jobs[jobId];
    if (!j) return;
    // Switch to correct workflow: try direct → wf_id fuzzy match → skip
    if (j.workflow && (!A.currentWF || j.workflow.replace('.json','') !== A.currentWF.replace('.json',''))) {
      var targetWf = null;
      var wfExists = [...$$('.wf-card')].some(el => el.dataset.name === j.workflow);
      if (wfExists) {
        targetWf = j.workflow;
      }
      if (!targetWf) {
        try {
          var params = new URLSearchParams();
          if (j.wf_id) params.set('wf_id', j.wf_id);
          if (j.wf_tags) params.set('wf_tags', JSON.stringify(j.wf_tags));
          params.set('workflow', j.workflow);
          var r = await fetch(API + '/api/workflows/find-closest?' + params.toString());
          if (r.ok) {
            var d = await r.json();
            targetWf = d.filename;
            console.log('[restoreJob] fuzzy matched:', j.workflow, '→', targetWf, 'by', d.matched_by);
          }
        } catch(e) { console.warn('[restoreJob] find-closest failed:', e); }
      }
      if (targetWf) {
        var meta = (A._wfMeta || {})[targetWf] || {};
        var tag = window.CW.wfTag ? window.CW.wfTag(targetWf, meta.tags) : null;
        if (tag) window.CW.switchTab(tag.text);
        await window.CW.selectWF(targetWf);
      } else {
        console.warn('[restoreJob] no match for workflow:', j.workflow, '— skipping switch');
      }
    }
    // Restore prompt
    if (j.prompt_preview) {
      _setPromptInputValue(j.prompt_preview);
    }
    // Restore dimensions
    if (j.width && j.height) {
      var wi = $('#widthInput'), hi = $('#heightInput');
      if (wi && hi) {
        wi.value = j.width;
        hi.value = j.height;
      }
      if (typeof highlightRatio === 'function') highlightRatio(j.width, j.height);
    }
    // Restore advanced fields from server fields data
    if (j.fields && typeof j.fields === 'object') {
      for (const [k, v] of Object.entries(j.fields)) {
        if (k === 'prompt_preview') continue;
        _setFieldControlValue(k, v);
      }
    }
    // Restore seed only for old job records that do not have workflow seed fields.
    if (j.seed && !_hasRestorableSeedFieldValues(j.fields || {})) {
      const seedEl = _getSeedInput() || document.querySelector('[data-field="seed"]') || document.querySelector('input[placeholder*="seed"]');
      if (seedEl) seedEl.value = j.seed;
      _setSeedRandomEnabled(true);
    }
  }

async function doGenerate() {
    if (!A.currentWF) {
      alert('请先选择 workflow');
      return;
    }
    // 未登录可看可选，但提交前再要求登录
    if (!window.CW.auth.isLoggedIn()) {
      window.CW.auth.showLogin();
      return;
    }
    const btn = $('#btnGenerate');
    btn.disabled = true;
    btn.textContent = '提交中...';

    const fields = {};
    const prompt = ($('#promptInput') || {}).value || '';
    _applyCurrentSizeLimit();
    const snapshot = { prompt, width: ($('#widthInput') || {}).value || 0, height: ($('#heightInput') || {}).value || 0, adv: {} };
    let submitFieldsMeta = [];

    try {
      await _waitForRefImageUpload();
      await _waitForRefVideoUpload();
      submitFieldsMeta = await _getSubmitFieldsMeta();
      let promptFieldCount = 0;
      for (const f of submitFieldsMeta || []) {
        // Pre-set default value for this field (including hidden)
        fields[f.node_id + '::' + f.field] = f.value;
        const zone = f.zone || 'advanced';
        const key = `${f.node_id}::${f.field}`;
        // Text-encode in user_input zone → main prompt
        if (_isPromptSubmitField(f)) {
          fields[key] = prompt;
          promptFieldCount += 1;
          continue;
        }
        // LatentImage size
        if (_isLatentDimensionField(f, 'width')) {
          fields[key] = parseInt(($('#widthInput') || {}).value) || 1024;
          continue;
        }
        if (_isLatentDimensionField(f, 'height')) {
          fields[key] = parseInt(($('#heightInput') || {}).value) || 1920;
          continue;
        }
        if (_isFlux2SchedulerSizeField(f, 'width')) {
          fields[key] = parseInt(($('#widthInput') || {}).value) || 1024;
          continue;
        }
        if (_isFlux2SchedulerSizeField(f, 'height')) {
          fields[key] = parseInt(($('#heightInput') || {}).value) || 1920;
          continue;
        }
        // LoadImage ref
        if (f.class_type === 'LoadImage' && f.field === 'image' && (zone === 'user_input' || !f.zone)) {
          const refVal = $('#refImageValue')?.value || '';
          if (_isVideoI2VMode() && !refVal) {
            throw new Error('图生视频需要先上传参考图');
          }
          if (refVal) fields[key] = refVal;
          continue;
        }
        if (f.class_type === 'LoadVideo' && f.field === 'file' && (zone === 'user_input' || !f.zone)) {
          const refVal = $('#refVideoValue')?.value || '';
          if (!refVal) {
            throw new Error('视频放大需要先上传参考视频');
          }
          fields[key] = refVal;
          continue;
        }
      }
      if (prompt && $('#promptInput') && promptFieldCount === 0) {
        throw new Error('未找到可提交的提示词字段，请重新选择工作流后再出图');
      }
    } catch (e) {
      console.error(e);
      alert('出图失败: ' + (e.message || '提示词字段读取失败'));
      btn.disabled = false;
      btn.innerHTML = CW.icon('play') + ' 出图';
      return;
    }

    $$('#quickFormFields [data-key]').forEach((el) => {
      fields[el.dataset.key] = _readFieldControlValue(el);
      snapshot.adv[el.dataset.key] = fields[el.dataset.key];
    });

    $$('#advFields [data-key]').forEach((el) => {
      fields[el.dataset.key] = _readFieldControlValue(el);
      snapshot.adv[el.dataset.key] = fields[el.dataset.key];
    });

    var videoUpscaleSizing = _applyVideoUpscaleLongEdgeResolution(fields, submitFieldsMeta);
    if (videoUpscaleSizing) {
      snapshot.adv[videoUpscaleSizing.key] = videoUpscaleSizing.computedResolution;
      snapshot.adv.__video_upscale_long_edge = videoUpscaleSizing.targetLongEdge;
      snapshot.adv.__video_upscale_source_size = videoUpscaleSizing.width + 'x' + videoUpscaleSizing.height;
    }

    try {
      const manualSeed = _getManualSeedValue();
      const requestBody = {
        workflow: A.currentWF,
        fields,
        width: parseInt(($('#widthInput') || {}).value) || 0,
        height: parseInt(($('#heightInput') || {}).value) || 0,
        preferred_instance: '',
        preferred_node_id: '',
      };
      if (!_isSeedRandomEnabled() && manualSeed === null) throw new Error('请输入种子数字，或开启随机种子');
      if (!_isSeedRandomEnabled()) requestBody.seed = manualSeed;
      const authHeaders = window.CW.auth.getAuthHeaders();
      const r = await fetch(`${API}/api/generate`, {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders),
        body: JSON.stringify(requestBody),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '提交失败');
      jobFields[d.job_id] = snapshot;
      // Add job to local store immediately so the card appears without waiting for poll
      jobs[d.job_id] = {
        id: d.job_id,
        status: 'queued',
        message: '排队中...',
        workflow: A.currentWF,
        seed: String(d.seed),
        prompt_preview: _quickGenerationLabel(),
        width: parseInt(($('#widthInput') || {}).value) || 0,
        height: parseInt(($('#heightInput') || {}).value) || 0,
        preferred_instance: '',
        preferred_node_id: '',
        queued_at: new Date().toLocaleTimeString('en-GB'),
      };
      try {
        if (window.CW && CW.toast) CW.toast('排队中', 'queued');
      } catch (e) {}
      // Trigger onJobUpdate to kick off active job polling
      window.CW.onJobUpdate(jobs[d.job_id]);
      if (window.CW.forceGalleryRerender) window.CW.forceGalleryRerender();
      else window.CW.renderGallery();
    } catch (e) {
      alert('出图失败: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = CW.icon('play') + ' 出图';
    }
  }


async function optimizePrompt() {
    var input = $('#promptInput');
    var btn = $('#optimizePromptBtn');
    if (!input) return;
    var copy = _promptOptimizeCopy();
    var raw = (input.value || '').trim();
    if (!raw) {
      if (window.CW && CW.toast) CW.toast(copy.empty, 'warn');
      input.focus();
      return;
    }
    var oldHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.classList.add('is-loading');
      btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' ' + copy.loading;
    }
    try {
      var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
      var response = await fetcher(API + '/api/prompt/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: raw,
          max_new_tokens: copy.mode === 'video_script' ? 768 : 384,
          mode: copy.mode,
          prompt_context: copy.mode === 'video_script' ? _videoScriptTimingContext() : {}
        })
      });
      var data = await response.json().catch(function() { return {}; });
      if (!response.ok) throw new Error(data.detail || data.message || copy.error);
      var optimized = String(data.optimized_prompt || data.cleaned_prompt || '').trim();
      if (!optimized) throw new Error('优化结果为空');
      window.CW.lastPromptOptimization = data;
      _setPromptInputValue(optimized);
      _showPromptOptimizationVariants(data);
      if (window.CW && CW.toast) CW.toast(data.structured_prompt_json ? copy.doneJson : copy.done, 'ok');
    } catch (e) {
      console.warn('[optimizePrompt] failed:', e);
      if (window.CW && CW.toast) CW.toast(e.message || copy.error, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.innerHTML = oldHtml || ((window.CW && CW.icon ? CW.icon('zap') : '') + ' ' + copy.label);
      }
    }
  }


async function translatePromptLanguage() {
    var input = $('#promptInput');
    var btn = $('#translatePromptBtn');
    if (!input) return;
    var raw = (input.value || '').trim();
    if (!raw) {
      if (window.CW && CW.toast) CW.toast('先输入提示词', 'warn');
      input.focus();
      return;
    }
    var targetLanguage = _detectPromptTargetLanguage(raw);
    var cachedTranslation = _getPromptTranslationCache(raw, targetLanguage);
    if (cachedTranslation) {
      _setPromptInputValue(cachedTranslation);
      if (window.CW && typeof CW.clearPromptOptimizationVariants === 'function') CW.clearPromptOptimizationVariants();
      if (window.CW && CW.toast) CW.toast(targetLanguage === 'en' ? '已快速切换为英文提示词' : '已快速切换为中文提示词', 'ok');
      return;
    }
    var oldHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.classList.add('is-loading');
      btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 翻译中';
    }
    try {
      var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
      var response = await fetcher(API + '/api/prompt/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: raw, target_language: targetLanguage })
      });
      var data = await response.json().catch(function() { return {}; });
      if (!response.ok) throw new Error(data.detail || data.message || '提示词翻译失败');
      var translated = String(data.translated_prompt || data.prompt_zh || data.prompt_en || '').trim();
      if (!translated) throw new Error('翻译结果为空');
      _rememberPromptTranslationPair(raw, data.target_language || targetLanguage, translated);
	      _setPromptInputValue(translated);
      if (window.CW && typeof CW.clearPromptOptimizationVariants === 'function') CW.clearPromptOptimizationVariants();
      if (window.CW && CW.toast) CW.toast(data.target_language === 'en' ? '已切换为英文提示词' : '已切换为中文提示词', 'ok');
    } catch (e) {
      console.warn('[translatePromptLanguage] failed:', e);
      if (window.CW && CW.toast) CW.toast(e.message || '提示词翻译失败', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.innerHTML = oldHtml || ((window.CW && CW.icon ? CW.icon('globe') : '') + ' 中英切换');
      }
      if (window.CW && CW.syncClearPromptButton) CW.syncClearPromptButton();
    }
  }


var _promptInterrogateRunning = false;

  function _setPromptInterrogateLoading(isLoading, label) {
    var buttons = [$('#interrogatePromptBtn'), $('#promptInterrogateRunBtn')];
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!btn) continue;
      btn.disabled = !!isLoading;
      btn.classList.toggle('is-loading', !!isLoading);
      if (isLoading) {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' ' + (label || '反推中');
      } else if (btn.id === 'interrogatePromptBtn') {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">图片反推</span>';
      } else {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推';
      }
    }
  }

  function _startPromptInterrogateTask(refVal) {
    if (!refVal) return;
    if (_promptInterrogateRunning) {
      if (window.CW && CW.toast) CW.toast('图片反推正在后台运行', 'info');
      return;
    }
    _promptInterrogateRunning = true;
    _setPromptInterrogateLoading(true, '后台反推中');
    if (window.CW && CW.closePromptInterrogateModal) CW.closePromptInterrogateModal();
    if (window.CW && typeof CW.showPromptInterrogatePendingToast === 'function') {
      CW.showPromptInterrogatePendingToast();
    } else if (window.CW && CW.toast) {
      CW.toast('后台努力反推中，请稍后……', 'info');
    }
    _runPromptInterrogate(refVal).then(function(result) {
      var prompt = result && result.prompt ? result.prompt : '';
      if (window.CW && typeof CW.showPromptResultToast === 'function') {
        CW.showPromptResultToast(prompt, result && result.data ? result.data : {});
      } else if (window.CW && CW.toast) {
        CW.toast('反推完成', 'done');
      }
    }).catch(function(e) {
      console.warn('[interrogatePromptFromImage] failed:', e);
      if (window.CW && typeof CW.clearPromptInterrogateToast === 'function') {
        CW.clearPromptInterrogateToast();
      }
      if (window.CW && CW.toast) CW.toast(e.message || '图片反推失败', 'error');
    }).finally(function() {
      _promptInterrogateRunning = false;
      _setPromptInterrogateLoading(false);
    });
  }

async function interrogatePromptFromImage() {
    var refVal = ($('#refImageValue') || {}).value || '';
    openPromptInterrogateModal(refVal);
  }

  async function _runPromptInterrogate(refVal) {
    var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
    var response = await fetcher(API + '/api/prompt/interrogate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: refVal })
    });
    var data = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(data.detail || data.message || '图片反推失败');
    var prompt = String(data.prompt || data.promptgen || data.wd14_tags || '').trim();
    if (!prompt) throw new Error('反推结果为空');
    return { prompt: prompt, data: data };
  }

  function openPromptInterrogateModal(initialImage) {
    if (!window.CW || !CW.auth || !CW.auth.isLoggedIn || !CW.auth.isLoggedIn()) {
      if (window.CW && CW.auth && CW.auth.showLogin) CW.auth.showLogin();
      return;
    }
    var old = document.getElementById('promptInterrogateModal');
    if (old) old.remove();
    var html = '<div class="v4-overlay prompt-interrogate-modal" id="promptInterrogateModal" onclick="if(event.target===this)CW.closePromptInterrogateModal()">' +
      '<div class="v4-card narrow prompt-interrogate-card">' +
        '<div class="auth-modal-header"><span class="auth-modal-title">' + (window.CW && CW.icon ? CW.icon('image', 18) : '') + '图片反推提示词</span>' +
        '<button class="auth-modal-close" type="button" onclick="CW.closePromptInterrogateModal()">×</button></div>' +
        '<div class="auth-modal-body">' +
          '<div class="prompt-interrogate-upload" id="promptInterrogateZone">' +
            '<div class="img-upload-placeholder"><span>' + (window.CW && CW.icon ? CW.icon('upload', 26) : '') + '</span><span>点击或拖入图片</span></div>' +
            '<img id="promptInterrogatePreview" class="img-upload-preview hidden" alt="">' +
            '<input type="file" id="promptInterrogateFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden">' +
          '</div>' +
          '<div class="prompt-interrogate-actions">' +
            '<button class="prompt-tool-btn" type="button" id="promptInterrogateRunBtn" disabled>' + (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
    var modal = document.getElementById('promptInterrogateModal');
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        if (modal) modal.classList.add('open');
      });
    });
    _initPromptInterrogateModal(initialImage);
  }

  function closePromptInterrogateModal() {
    var modal = document.getElementById('promptInterrogateModal');
    if (!modal) return;
    modal.classList.remove('open');
    setTimeout(function() {
      if (modal.parentNode) modal.parentNode.removeChild(modal);
    }, 300);
  }

  function _initPromptInterrogateModal(initialImage) {
    var zone = $('#promptInterrogateZone');
    var fileInput = $('#promptInterrogateFile');
    var preview = $('#promptInterrogatePreview');
    var runBtn = $('#promptInterrogateRunBtn');
    var uploadedName = String(initialImage || '').trim();
    if (!zone || !fileInput || !runBtn) return;

    if (uploadedName) {
      if (preview) {
        preview.src = API + '/api/input-image/' + encodeURIComponent(uploadedName);
        preview.style.display = '';
        preview.classList.remove('hidden');
      }
      var ph = zone.querySelector('.img-upload-placeholder');
      if (ph) ph.style.display = 'none';
      runBtn.disabled = false;
    }

    async function useFile(file) {
      if (!file) return;
      runBtn.disabled = true;
      runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 上传中';
      runBtn.classList.add('is-loading');
      try {
        var d = await _uploadRefImage(file);
        uploadedName = d.filename;
        if (preview) {
          preview.src = API + '/api/input-image/' + encodeURIComponent(uploadedName);
          preview.style.display = '';
          preview.classList.remove('hidden');
        }
        var ph = zone.querySelector('.img-upload-placeholder');
        if (ph) ph.style.display = 'none';
        runBtn.disabled = false;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推';
      } catch (e) {
        if (window.CW && CW.toast) CW.toast(e.message || '图片上传失败', 'error');
        runBtn.disabled = true;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 开始反推';
      } finally {
        runBtn.classList.remove('is-loading');
        fileInput.value = '';
      }
    }

    zone.addEventListener('click', function(e) {
      if (e.target && e.target.tagName === 'IMG') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', function() {
      useFile(fileInput.files && fileInput.files[0]);
    });
    zone.addEventListener('dragover', function(e) {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
      zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', function(e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      useFile(e.dataTransfer.files && e.dataTransfer.files[0]);
    });
    runBtn.addEventListener('click', async function() {
      if (!uploadedName) return;
      _startPromptInterrogateTask(uploadedName);
    });
  }


  // Shared across modules via __APP__
  var _wfFieldMeta = window.__APP__._wfFieldMeta || [];
  window.__APP__._wfFieldMeta = _wfFieldMeta;

  var _loadImageFields = window.__APP__._loadImageFields || [];
  window.__APP__._loadImageFields = _loadImageFields;

function renderQuickForm(fields) {
    var container = $('#quickFormFields');
    if (!container) return;
    if (!fields || !fields.length) { container.innerHTML = ''; return; }
    // Preserve prompt text across workflow switches
    var _savedPrompt = ($('#promptInput') || {}).value || '';
    var hasZones = fields.some(function(f) { return f.zone; });
    var html = '', hasTextEncode = false, hasLoadImage = false, hasLoadVideo = false, quickImageRendered = false, quickVideoRendered = false, sizeRendered = false;
    var hasLatentW = false, hasLatentH = false, latentW = 1024, latentH = 1024;
    for (var si = 0; si < fields.length; si++) {
      var sf = fields[si] || {};
      var szone = sf.zone || (hasZones ? 'hidden' : 'advanced');
      if (hasZones && szone !== 'user_input') continue;
      if (_isLatentDimensionField(sf, 'width')) { hasLatentW = true; latentW = sf.value || 1024; }
      else if (_isLatentDimensionField(sf, 'height')) { hasLatentH = true; latentH = sf.value || 1024; }
    }
    function sizeSectionHtml() {
      if (!hasLatentW && !hasLatentH) return '';
      var limits = _workflowSizeLimits(fields);
      var baseSize = _limitDimensions(hasLatentW ? latentW : 1024, hasLatentH ? latentH : 1024, limits);
      var sw = baseSize[0], sh = baseSize[1];
      var out = '<div class="fg" id="sizeSection"><label>出图比例</label><div class="ratio-grid" id="ratioGrid">';
      var presets = _ratioPresetsForLimits(limits);
      for (var spi = 0; spi < presets.length; spi++) {
        var p = presets[spi];
        out += '<button class="ratio-btn' + (p[0]===sw&&p[1]===sh?' active':'') + '" data-w="' + p[0] + '" data-h="' + p[1] + '" title="' + p[0] + '×' + p[1] + '"><span class="ratio-shape" style="width:' + p[3] + ';height:' + p[4] + '"></span><span class="ratio-label">' + p[2] + '</span></button>';
      }
      var inputMax = limits.inputMax || 2048;
      var minW = limits.minWidth || limits.minSide;
      var minH = limits.minHeight || limits.minSide;
      out += '</div><div class="ratio-custom"><input type="number" id="widthInput" value="' + sw + '" step="' + limits.multiple + '" min="' + minW + '" max="' + inputMax + '"><span class="sep-dim" aria-label="乘以">×</span><input type="number" id="heightInput" value="' + sh + '" step="' + limits.multiple + '" min="' + minH + '" max="' + inputMax + '"></div></div>';
      return out;
    }
    for (var fi = 0; fi < fields.length; fi++) {
      var f = fields[fi], zone = f.zone || (hasZones ? 'hidden' : 'advanced');
      if (zone !== 'user_input') {
        if (hasZones) continue;
        if (f.class_type === 'LoadImage' && f.field === 'image') hasLoadImage = true;
        else if (f.class_type === 'LoadVideo' && f.field === 'file') hasLoadVideo = true;
        else if (_isPromptLikeField(f)) hasTextEncode = true;
        continue;
      }
      if (_isPromptLikeField(f)) {
        hasTextEncode = true;
        var labelText = f.label || 'Prompt', nodeInfo = f.node_title ? ' [' + f.node_title.split('(')[0].trim() + ']' : '';
        var optimizeCopy = _promptOptimizeCopy(fields);
        html += '<div class="fg prompt-fg"><div class="prompt-label-row"><label>' + escH(labelText + nodeInfo) + '</label></div><div class="prompt-input-wrap"><textarea id="promptInput" placeholder="' + escA(labelText) + '..."></textarea></div><div class="prompt-actions"><button id="interrogatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-image" type="button" title="图片反推" onclick="CW.interrogatePromptFromImage()">' + (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">图片反推</span></button><button id="optimizePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant is-compact-disabled" type="button" title="' + escA(optimizeCopy.label) + '" data-optimize-mode="' + escA(optimizeCopy.mode) + '" onclick="CW.optimizePrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('zap') : '') + ' <span class="prompt-tool-label">' + escH(optimizeCopy.label) + '</span></button><button id="translatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-translate is-compact-disabled" type="button" title="中文/英文提示词切换" onclick="CW.translatePromptLanguage()" disabled>' + (window.CW && CW.icon ? CW.icon('globe') : '') + ' <span class="prompt-tool-label">中英切换</span></button><button id="clearPromptBtn" class="prompt-tool-btn prompt-tool-btn-clear clear-btn is-compact-disabled" type="button" title="清除文字" onclick="CW.clearPrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' <span class="prompt-tool-label">清除文字</span></button></div></div>';
      } else if (_isVideoModeField(f)) {
        var modeKey = `${f.node_id}::${f.field}`;
        var isBypass = f.value !== false && f.value !== 'false' && f.value !== 'False';
        html += '<div class="fg video-mode-fg"><label>' + escH(f.label || '生成模式') + '</label><div class="video-mode-control" data-video-mode-key="' + escA(modeKey) + '"><button type="button" class="video-mode-btn' + (isBypass ? ' active' : '') + '" data-mode="t2v" aria-pressed="' + (isBypass ? 'true' : 'false') + '">文生视频</button><button type="button" class="video-mode-btn' + (!isBypass ? ' active' : '') + '" data-mode="i2v" aria-pressed="' + (!isBypass ? 'true' : 'false') + '">图生视频</button><input type="hidden" data-key="' + escA(modeKey) + '" data-type="video_mode" value="' + (isBypass ? 'true' : 'false') + '"></div></div>';
      } else if (f.class_type === 'LoadImage' && f.field === 'image') {
        hasLoadImage = true;
        quickImageRendered = true;
        html += '<div class="ref-image-section"><label>' + escH(f.label || 'Reference Image') + '</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden"></div></div>';
      } else if (f.class_type === 'LoadVideo' && f.field === 'file') {
        hasLoadVideo = true;
        quickVideoRendered = true;
        html += '<div class="ref-image-section ref-video-section"><label>' + escH(f.label || 'Reference Video') + '</label><div class="img-upload-zone video-upload-zone" id="refVideoZone"><div id="refVideoPlaceholder" class="img-upload-placeholder">Click or drag video</div><video id="refVideoPreview" class="img-upload-preview video-upload-preview hidden" muted playsinline controls></video><input type="hidden" id="refVideoValue" value=""><input type="file" id="refVideoFile" accept="video/*,.mp4,.webm,.mov,.m4v" class="hidden"></div></div>';
      } else if (_isLatentDimensionField(f, 'width') || _isLatentDimensionField(f, 'height')) {
        if (!sizeRendered) {
          html += sizeSectionHtml();
          sizeRendered = true;
        }
      }
      else if (f.type === 'number') {
        var numberKey = `${f.node_id}::${f.field}`;
        var numVal = f.value ?? '';
        html += '<div class="fg quick-number-fg"><label>' + escH(f.label || f.field) + '</label><input type="number" data-key="' + escA(numberKey) + '" data-type="number" value="' + escA(String(numVal)) + '"' + _numberAttr('min', f.min) + _numberAttr('max', f.max) + _numberAttr('step', f.step || 1) + '></div>';
      } else if (f.type === 'select') {
        var selectKey = `${f.node_id}::${f.field}`;
        var selectVal = f.value ?? '';
        var selectOpts = (f.options || []).map(function(o) {
          return '<option value="' + escA(o) + '" ' + (o === selectVal ? 'selected' : '') + '>' + escH(o) + '</option>';
        }).join('');
        html += '<div class="fg quick-select-fg"><label>' + escH(f.label || f.field) + '</label><select data-key="' + escA(selectKey) + '">' + selectOpts + '</select></div>';
      } else if (f.type === 'text') {
        var textKey = `${f.node_id}::${f.field}`;
        var textVal = f.value ?? '';
        html += '<div class="fg quick-text-fg"><label>' + escH(f.label || f.field) + '</label><input type="text" data-key="' + escA(textKey) + '" value="' + escA(String(textVal)) + '"></div>';
      }
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadImage && !quickImageRendered) {
      html += '<div class="ref-image-section"><label>Reference Image</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden"></div></div>';
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadVideo && !quickVideoRendered) {
      html += '<div class="ref-image-section ref-video-section"><label>Reference Video</label><div class="img-upload-zone video-upload-zone" id="refVideoZone"><div id="refVideoPlaceholder" class="img-upload-placeholder">Click or drag video</div><video id="refVideoPreview" class="img-upload-preview video-upload-preview hidden" muted playsinline controls></video><input type="hidden" id="refVideoValue" value=""><input type="file" id="refVideoFile" accept="video/*,.mp4,.webm,.mov,.m4v" class="hidden"></div></div>';
    }
    if ((hasLatentW || hasLatentH) && !sizeRendered) html += sizeSectionHtml();
    container.innerHTML = html;
    if (hasLatentW || hasLatentH) {
      window.CW.initRatioGrid && window.CW.initRatioGrid();
      var wi = $('#widthInput');
      var hi = $('#heightInput');
      window.CW.highlightRatio && CW.highlightRatio(parseInt((wi && wi.value) || 0, 10), parseInt((hi && hi.value) || 0, 10));
    }
    // Restore saved prompt text after DOM rebuild (non-latent path)
    if (_savedPrompt) {
      var pi2 = $('#promptInput');
      if (pi2 && !pi2.value) pi2.value = _savedPrompt;
    }
    var promptInput = $('#promptInput');
    if (promptInput && window.CW.syncClearPromptButton) {
      promptInput.addEventListener('input', window.CW.syncClearPromptButton);
      window.CW.syncClearPromptButton();
    }
    _initVideoModeControl();
    if (hasLoadImage) { _refImageInited = false; setTimeout(function() { _initRefImageZone(); }, 50); }
    if (hasLoadVideo) { _refVideoInited = false; setTimeout(function() { _initRefVideoZone(); }, 50); }
  }

function renderAdvFields(fields) {
    const box = $('#advFields');

    // ── Zone-aware field routing ──
    // user_input text-encode fields → main prompt textarea (handled in doGenerate)
    // user_input LoadImage → ref image section
    // user_input LatentImage size → size section
    // advanced → advanced params
    // hidden → not shown

    // Detect LoadImage in user_input zone
  _loadImageFields = fields.filter((f) => {
      if (f.class_type !== 'LoadImage' || f.field !== 'image') return false;
      const zone = f.zone || 'advanced';
      return zone === 'user_input';
    });
    var _loadVideoFields = fields.filter((f) => {
      if (f.class_type !== 'LoadVideo' || f.field !== 'file') return false;
      const zone = f.zone || 'advanced';
      return zone === 'user_input';
    });
    // Fallback: if no zone info, use old logic
    if (!_loadImageFields.length && !fields.some((f) => f.zone)) {
      _loadImageFields = fields.filter((f) => f.class_type === 'LoadImage' && f.field === 'image');
    }
    const hasLoadImage = _loadImageFields.length > 0;
    const hasLoadVideo = _loadVideoFields.length > 0;
    const section = $('#refImageSection');
    if (section) section.style.display = hasLoadImage ? '' : 'none';
    if (hasLoadImage) _initRefImageZone();
    else _resetRefImage();
    if (!hasLoadVideo) _resetRefVideo();

    // Build advanced fields: only 'advanced' zone (or fallback for unzoned)
    const hasZones = fields.some((f) => f.zone);
    const advFields = fields.filter((f) => {
      const zone = f.zone || 'advanced';
      // Skip hidden zone OR explicitly invisible fields
      if (zone === 'hidden') return false;
      if (f.visible === false) return false;
      // Skip user_input fields that are handled by dedicated sections
      if (zone === 'user_input') {
        // Text-encode → main prompt
        if (_isPromptLikeField(f)) return false;
        // LoadImage → ref image section
        if (f.class_type === 'LoadImage' && f.field === 'image') return false;
        if (f.class_type === 'LoadVideo' && f.field === 'file') return false;
        if (_isVideoModeField(f)) return false;
        // LatentImage size → size section
        if (_isLatentDimensionField(f, 'width') || _isLatentDimensionField(f, 'height'))
          return false;
        return false;
      }
      // For unzoned workflows, use old filtering
      if (!hasZones) {
        if (_isPromptLikeField(f)) return false;
        if (_isLatentDimensionField(f, 'width') || _isLatentDimensionField(f, 'height'))
          return false;
        if (f.class_type === 'LoadImage' && f.field === 'image') return false;
        if (f.class_type === 'LoadVideo' && f.field === 'file') return false;
      }
      // Skip output zone (read-only, handled by SaveImage)
      if (zone === 'output') return false;
      return true;
    });

    if (!advFields.length) {
      box.innerHTML = '<div class="gen-empty">无可编辑参数</div>';
      return;
    }
    let html = '';
    for (const f of advFields) {
      const key = `${f.node_id}::${f.field}`;
      const val = f.value ?? '';
      html += `<div class="fg"><label>${escH(f.label)} <span class="node-tag">[${escH(f.node_title)}]</span></label>`;
      switch (f.type) {
        case 'select': {
          const opts = (f.options || [])
            .map((o) => `<option value="${escA(o)}" ${o === val ? 'selected' : ''}>${escH(o)}</option>`)
            .join('');
          html += `<select data-key="${key}">${opts}</select>`;
          break;
        }
        case 'toggle':
        case 'bool':
          html += `<label class="toggle-label bool-toggle"><input type="checkbox" data-key="${key}" ${val === true || val === 'True' || val === 'true' ? 'checked' : ''} onchange="this.value=this.checked"><span class="toggle-slider"></span><span class="toggle-state" data-on="开启" data-off="关闭"></span></label>`;
          break;
        case 'seed':
          html += `<div class="seed-group"><input type="number" data-key="${key}" data-type="number" value="${val}"${_numberAttr('min', f.min)}${_numberAttr('max', f.max)}${_numberAttr('step', f.step || 1)} oninput="CW.setSeedRandomEnabled(false)"><button type="button" class="btn-dice seed-random-toggle is-active" data-seed-random="1" aria-pressed="true" title="随机种子" aria-label="随机种子" onclick="CW.toggleSeedRandom(this)">${CW.icon('shuffle')}</button></div>`;
          break;
        case 'number': {
          const step = f.step || 1,
            mn = f.min ?? '',
            mx = f.max ?? '';
          html += `<input type="number" data-key="${key}" value="${val}" step="${step}" ${mn !== '' ? `min="${mn}"` : ''} ${mx !== '' ? `max="${mx}"` : ''}>`;
          break;
        }
        default:
          html += `<input type="text" data-key="${key}" value="${escH(String(val))}">`;
      }
      html += `</div>`;
    }
    box.innerHTML = html;
  }

function toggleGenForm() {
    const form = $('#genForm');
    if (!form) return;
    const footer = $('.gen-footer');
    const btn = $('#genToggleMobile');
    const title = $('#genTitle');
    const arrow = $('#genArrow');
    const open = !form.classList.contains('mobile-open');
    form.classList.toggle('mobile-open', open);
    if (footer) footer.classList.toggle('mobile-open', open);
    if (title) title.classList.toggle('is-open', open);
    if (arrow) arrow.textContent = open ? '\u25B4' : '\u25BE';
    if (btn) btn.innerHTML = open ? CW.icon('zap') + ' 收起 \u25B4' : CW.icon('zap') + ' 快速出图 \u25BE';
  }

var _refImageInited = false;
var _refImageUploadPromise = null;
var _refImageUploadToken = 0;
var _refVideoInited = false;
var _refVideoUploadPromise = null;
var _refVideoUploadToken = 0;
function _resetRefImage() {
    _refImageInited = false;
    _refImageUploadPromise = null;
    _refImageUploadToken += 1;
    var preview = $('#refImagePreview');
    var placeholder = $('#refImagePlaceholder');
    var valueInput = $('#refImageValue');
    if (preview) { preview.src = ''; preview.style.display = 'none'; }
    if (placeholder) placeholder.style.display = '';
    if (valueInput) valueInput.value = '';
    _setRefImageUploading(false);
  }

function _resetRefVideo() {
    _refVideoInited = false;
    _refVideoUploadPromise = null;
    _refVideoUploadToken += 1;
    var preview = $('#refVideoPreview');
    var placeholder = $('#refVideoPlaceholder');
    var valueInput = $('#refVideoValue');
    if (preview) { preview.removeAttribute('src'); preview.load && preview.load(); preview.style.display = 'none'; }
    if (placeholder) placeholder.style.display = '';
    if (valueInput) valueInput.value = '';
    _setRefVideoMetadata({});
    _setRefVideoUploading(false);
  }

var __curZone = null;
  async function _parseUploadResponse(resp) {
    var text = await resp.text();
    var data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        data = { detail: text };
      }
    }
    if (!resp.ok || !data.ok) {
      throw new Error((data && (data.detail || data.error || data.message)) || ('upload fail (' + resp.status + ')'));
    }
    return data;
  }

  function _uploadRefImage(file) {
    var fd = new FormData();
    fd.append('file', file);
    var upload = (window.CW && window.CW.auth && typeof window.CW.auth.apiFetch === 'function')
      ? window.CW.auth.apiFetch(API + '/api/upload-image', { method: 'POST', body: fd })
      : fetch(API + '/api/upload-image', { method: 'POST', body: fd });
    return upload.then(_parseUploadResponse);
  }

  function _uploadRefVideo(file) {
    var fd = new FormData();
    fd.append('file', file);
    var upload = (window.CW && window.CW.auth && typeof window.CW.auth.apiFetch === 'function')
      ? window.CW.auth.apiFetch(API + '/api/upload-video', { method: 'POST', body: fd })
      : fetch(API + '/api/upload-video', { method: 'POST', body: fd });
    return upload.then(_parseUploadResponse);
  }

  function _setRefVideoMetadata(meta) {
    var width = parseInt((meta && meta.width) || 0, 10) || 0;
    var height = parseInt((meta && meta.height) || 0, 10) || 0;
    [$('#refVideoValue'), $('#refVideoPreview')].forEach(function(el) {
      if (!el) return;
      if (width && height) {
        el.setAttribute('data-video-width', String(width));
        el.setAttribute('data-video-height', String(height));
      } else {
        el.removeAttribute('data-video-width');
        el.removeAttribute('data-video-height');
      }
    });
  }

  function _readVideoFileMetadata(file) {
    return new Promise(function(resolve) {
      if (!file || typeof document === 'undefined') {
        resolve({});
        return;
      }
      var video = document.createElement('video');
      var url = '';
      var done = false;
      function finish(meta) {
        if (done) return;
        done = true;
        try {
          if (url && window.URL && URL.revokeObjectURL) URL.revokeObjectURL(url);
        } catch (e) {}
        resolve(meta || {});
      }
      try {
        if (!window.URL || !URL.createObjectURL) {
          finish({});
          return;
        }
        url = URL.createObjectURL(file);
        video.preload = 'metadata';
        video.onloadedmetadata = function() {
          finish({
            width: video.videoWidth || 0,
            height: video.videoHeight || 0,
            duration: video.duration || 0
          });
        };
        video.onerror = function() { finish({}); };
        setTimeout(function() { finish({}); }, 4000);
        video.src = url;
        video.load && video.load();
      } catch (e) {
        finish({});
      }
    });
  }

  function _setRefImageUploading(uploading) {
    var zone = $('#refImageZone');
    if (!zone) return;
    if (uploading) {
      if (zone.setAttribute) zone.setAttribute('data-uploading', '1');
      else if (zone.dataset) zone.dataset.uploading = '1';
    } else if (zone.removeAttribute) {
      zone.removeAttribute('data-uploading');
    } else if (zone.dataset) {
      delete zone.dataset.uploading;
    }
  }

  function _setRefVideoUploading(uploading) {
    var zone = $('#refVideoZone');
    if (!zone) return;
    if (uploading) {
      if (zone.setAttribute) zone.setAttribute('data-uploading', '1');
      else if (zone.dataset) zone.dataset.uploading = '1';
    } else if (zone.removeAttribute) {
      zone.removeAttribute('data-uploading');
    } else if (zone.dataset) {
      delete zone.dataset.uploading;
    }
  }

  async function _waitForRefImageUpload() {
    if (!_refImageUploadPromise) return;
    if (window.CW && CW.toast) CW.toast('参考图仍在上传，完成后继续提交', 'info');
    try {
      await _refImageUploadPromise;
    } catch (e) {
      throw new Error('参考图仍在上传失败，请重新上传后再出图');
    }
  }

  async function _waitForRefVideoUpload() {
    if (!_refVideoUploadPromise) return;
    if (window.CW && CW.toast) CW.toast('参考视频仍在上传，完成后继续提交', 'info');
    try {
      await _refVideoUploadPromise;
    } catch (e) {
      throw new Error('参考视频上传失败，请重新上传后再出图');
    }
  }

  function _applyUploadedRefImage(file, fileInput, zone, preview, valueInput, placeholder) {
    if (!file) return Promise.resolve(null);
    var token = ++_refImageUploadToken;
    if (valueInput) valueInput.value = '';
    if (preview) {
      preview.src = '';
      preview.style.display = 'none';
    }
    if (placeholder) placeholder.style.display = '';
    _setRefImageUploading(true);
    var upload = _uploadRefImage(file).then(function(d) {
      if (token !== _refImageUploadToken) return d;
      if (valueInput) valueInput.value = d.filename;
      if (preview) {
        preview.src = API + '/api/input-image/' + encodeURIComponent(d.filename);
        preview.style.display = '';
      }
      if (placeholder) placeholder.style.display = 'none';
      return d;
    }).finally(function() {
      if (token === _refImageUploadToken) {
        _refImageUploadPromise = null;
        _setRefImageUploading(false);
      }
      if (fileInput) fileInput.value = '';
    });
    _refImageUploadPromise = upload;
    return upload;
  }

  function _applyUploadedRefVideo(file, fileInput, zone, preview, valueInput, placeholder) {
    if (!file) return Promise.resolve(null);
    var token = ++_refVideoUploadToken;
    if (valueInput) valueInput.value = '';
    if (preview) {
      preview.removeAttribute('src');
      preview.load && preview.load();
      preview.style.display = 'none';
    }
    if (placeholder) placeholder.style.display = '';
    _setRefVideoUploading(true);
    var upload = Promise.all([_uploadRefVideo(file), _readVideoFileMetadata(file)]).then(function(results) {
      var d = results[0];
      var meta = results[1] || {};
      if (token !== _refVideoUploadToken) return d;
      if (valueInput) valueInput.value = d.filename;
      _setRefVideoMetadata(meta);
      if (preview) {
        preview.src = API + '/api/input-video/' + encodeURIComponent(d.filename);
        preview.style.display = '';
        preview.load && preview.load();
      }
      if (placeholder) placeholder.style.display = 'none';
      return d;
    }).finally(function() {
      if (token === _refVideoUploadToken) {
        _refVideoUploadPromise = null;
        _setRefVideoUploading(false);
      }
      if (fileInput) fileInput.value = '';
    });
    _refVideoUploadPromise = upload;
    return upload;
  }

  function _initRefImageZone() {
    if (_refImageInited) return;
    _refImageInited = true;
    var zone = $('#refImageZone');
    var fileInput = $('#refImageFile');
    var preview = $('#refImagePreview');
    var valueInput = $('#refImageValue');
    var placeholder = $('#refImagePlaceholder');
    if (!zone || !fileInput) return;
    zone.addEventListener('click', function(e) {
      if (e.target.tagName === 'IMG') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', async function() {
      if (!fileInput.files.length) return;
      var file = fileInput.files[0];
      try {
        await _applyUploadedRefImage(file, fileInput, zone, preview, valueInput, placeholder);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
    if (preview) {
      preview.addEventListener('click', function() {
        _refImageUploadPromise = null;
        _refImageUploadToken += 1;
        _setRefImageUploading(false);
        preview.src = '';
        preview.style.display = 'none';
        if (placeholder) placeholder.style.display = '';
        valueInput.value = '';
      });
    }
    zone.addEventListener('dragover', function(e) {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
      zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', async function(e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      var file = e.dataTransfer.files[0];
      if (!file) return;
      try {
        await _applyUploadedRefImage(file, fileInput, zone, preview, valueInput, placeholder);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
  }

  function _initRefVideoZone() {
    if (_refVideoInited) return;
    _refVideoInited = true;
    var zone = $('#refVideoZone');
    var fileInput = $('#refVideoFile');
    var preview = $('#refVideoPreview');
    var valueInput = $('#refVideoValue');
    var placeholder = $('#refVideoPlaceholder');
    if (!zone || !fileInput) return;
    zone.addEventListener('click', function(e) {
      if (e.target.tagName === 'VIDEO') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', async function() {
      if (!fileInput.files.length) return;
      var file = fileInput.files[0];
      try {
        await _applyUploadedRefVideo(file, fileInput, zone, preview, valueInput, placeholder);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
    if (preview) {
      preview.addEventListener('loadedmetadata', function() {
        _setRefVideoMetadata({
          width: preview.videoWidth || 0,
          height: preview.videoHeight || 0
        });
      });
      preview.addEventListener('click', function(e) {
        e.stopPropagation();
      });
    }
    zone.addEventListener('dragover', function(e) {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
      zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', async function(e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      var file = e.dataTransfer.files[0];
      if (!file) return;
      try {
        await _applyUploadedRefVideo(file, fileInput, zone, preview, valueInput, placeholder);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
  }

function renderQuickGen() {
    // No-op: quick gen is rendered inline
  }

  if (!window.CW) window.CW = {};
  window.CW.toggleGenForm = toggleGenForm;
  window.CW.restoreJob = restoreJob;
  window.CW.fillFormFromHistory = fillFormFromHistory;
  window.CW.doGenerate = doGenerate;
  window.CW.optimizePrompt = optimizePrompt;
  window.CW.translatePromptLanguage = translatePromptLanguage;
  window.CW.registerPromptTranslationPair = registerPromptTranslationPair;
  window.CW.clearPromptOptimizationVariants = _clearPromptOptimizationVariants;
  window.CW.interrogatePromptFromImage = interrogatePromptFromImage;
  window.CW.openPromptInterrogateModal = openPromptInterrogateModal;
  window.CW.closePromptInterrogateModal = closePromptInterrogateModal;
  window.CW.renderAdvFields = renderAdvFields;
  window.CW.renderQuickGen = renderQuickGen;
  window.CW.renderQuickForm = renderQuickForm;
  window.CW.setVideoMode = setVideoMode;
  window.CW.toggleSeedRandom = toggleSeedRandom;
  window.CW.setSeedRandomEnabled = _setSeedRandomEnabled;
  window.CW.initRatioGrid = initRatioGrid;
  window.CW.highlightRatio = highlightRatio;
})();
