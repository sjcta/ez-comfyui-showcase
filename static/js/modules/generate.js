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
  var ERNIE_IMAGE_RATIO_PRESETS = [
    [1024, 1024, '1:1', '22px', '22px'],
    [1264, 848, '3:2', '26px', '17px'],
    [1376, 768, '16:9', '28px', '16px'],
    [1200, 896, '4:3', '24px', '18px'],
    [896, 1200, '3:4', '18px', '24px'],
    [848, 1264, '2:3', '16px', '24px'],
    [768, 1376, '9:16', '14px', '24px']
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
      return { name: 'ernie-image', maxSide: 1376, maxPixels: null, multiple: 16, minSide: 64, inputMax: 1376, presets: ERNIE_IMAGE_RATIO_PRESETS };
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
        node_title: f.node_title,
        zone: f.zone,
        visible: f.visible !== false,
        type: f.type,
        label: f.label,
        value: f.value,
        role: f.role,
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

function _timingKindForField(f) {
    if (!f) return '';
    var label = String(f.label || '');
    var field = String(f.field || '');
    var key = _fieldKeyForMeta(f);
    var cls = String(f.class_type || '');
    var title = String(f.node_title || '');
    var haystack = (label + ' ' + field + ' ' + key + ' ' + cls + ' ' + title).toLowerCase();
    if (/帧率|fps|frame[_ -]?rate|framerate|\bframes?\s*per\s*second\b/.test(haystack)) {
      return 'fps';
    }
    if (/帧数|总帧|number\s+of\s+frames|frames[_ -]?number|frame[_ -]?count|num[_ -]?frames/.test(haystack)) {
      return 'frame_count';
    }
    if (/长度.*秒|时长|秒|duration|seconds|duration_sec|\bsec(?:onds?)?\b/.test(haystack)) {
      return 'duration_seconds';
    }
    if (/^(?:length|frames_number)$/.test(field) && /video|ltxv|latent/i.test(cls + ' ' + title)) {
      return 'frame_count';
    }
    if (/\blength\b/.test(haystack) && /video|ltx|sulphur/i.test(String(A.currentWF || '') + ' ' + cls + ' ' + title)) {
      return 'frame_count';
    }
    return '';
  }

function _videoScriptTimingContext() {
    var context = {};
    var fields = A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      var kind = _timingKindForField(f);
      if (!kind) continue;
      var raw = _currentFieldValueForMeta(f);
      var value = parseFloat(raw);
      if (!isFinite(value) || value <= 0) continue;
      if (kind === 'fps') {
        context.fps = value;
      } else if (kind === 'duration_seconds') {
        context.duration_seconds = value;
      } else if (kind === 'frame_count') {
        context.frame_count = value;
      }
    }
    if (!context.duration_seconds && context.frame_count && context.fps) {
      context.duration_seconds = Math.round((context.frame_count / context.fps) * 100) / 100;
    }
    if (!context.frame_count && context.duration_seconds && context.fps) {
      context.frame_count = Math.max(1, Math.round(context.duration_seconds * context.fps));
    }
    if (A.currentWF) context.workflow = A.currentWF;
    return context;
  }

function _promptInterrogatePayload(refVal, options) {
    var copy = _promptOptimizeCopy();
    options = options || {};
    var level = Number(options.level);
    if (!isFinite(level)) level = options.expertTeam ? 2 : (options.expert ? 1 : 0);
    level = Math.max(0, Math.min(2, Math.round(level)));
    return {
      image: refVal,
      mode: level > 0 ? 'image' : copy.mode,
      level: level,
      expert: level > 0,
      expert_team: level >= 2,
      prompt_context: (level === 0 && copy.mode === 'video_script') ? _videoScriptTimingContext() : {}
    };
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
    if (f && f.role === dim) return true;
    return !!(f && f.field === dim && (cls.indexOf('LatentImage') >= 0 || cls.indexOf('LatentVideo') >= 0));
  }

function _isVideoModeField(f) {
    return !!(f && f.type === 'video_mode');
  }

function _isQwenAngleField(f) {
    return !!(f && f.class_type === 'QwenMultiangleCameraNode' && /^(horizontal_angle|vertical_angle|zoom|camera_view|default_prompts)$/.test(String(f.field || '')));
  }

function _qwenAngleGroups(fields) {
    var groups = [];
    var byNode = {};
    (fields || []).forEach(function(f) {
      if (!_isQwenAngleField(f)) return;
      var zone = f.zone || ((fields || []).some(function(item) { return item && item.zone; }) ? 'hidden' : 'advanced');
      if (zone !== 'user_input') return;
      var nodeId = String(f.node_id || '');
      if (!nodeId) return;
      if (!byNode[nodeId]) {
        byNode[nodeId] = { node_id: nodeId, title: f.node_title || 'Qwen Multiangle Camera', fields: {} };
        groups.push(byNode[nodeId]);
      }
      byNode[nodeId].fields[f.field] = f;
    });
    return groups.filter(function(group) {
      return group.fields.horizontal_angle && group.fields.vertical_angle && group.fields.zoom;
    });
  }

function _qwenSignedYaw(horizontal) {
    var h = ((parseFloat(horizontal) || 0) % 360 + 360) % 360;
    return h > 180 ? h - 360 : h;
  }

function _isQwenAngleNeutral(horizontal, vertical, zoom, roll) {
    var signedYaw = _qwenSignedYaw(horizontal);
    var v = parseFloat(vertical);
    if (!Number.isFinite(v)) v = 0;
    var z = parseFloat(zoom);
    if (!Number.isFinite(z)) z = 5;
    var r = parseFloat(roll);
    if (!Number.isFinite(r)) r = 0;
    return Math.abs(signedYaw) < 0.5
      && Math.abs(v) < 0.5
      && Math.abs(z - 5) < 0.05
      && Math.abs(r) < 0.5;
  }

function _qwenNativeHorizontalText(horizontal) {
    var h = ((parseFloat(horizontal) || 0) % 360 + 360) % 360;
    if (h < 22.5 || h >= 337.5) return 'front view';
    if (h < 67.5) return 'front-right quarter view';
    if (h < 112.5) return 'right side view';
    if (h < 157.5) return 'back-right quarter view';
    if (h < 202.5) return 'back view';
    if (h < 247.5) return 'back-left quarter view';
    if (h < 292.5) return 'left side view';
    return 'front-left quarter view';
  }

function _qwenNativeVerticalText(vertical) {
    var v = parseFloat(vertical);
    if (!Number.isFinite(v)) v = 0;
    if (v < -15) return 'low-angle shot';
    if (v < 15) return 'eye-level shot';
    if (v < 45) return 'elevated shot';
    return 'high-angle shot';
  }

function _qwenNativeDistanceText(zoom) {
    var z = parseFloat(zoom);
    if (!Number.isFinite(z)) z = 5;
    if (z < 2) return 'wide shot';
    if (z < 6) return 'medium shot';
    return 'close-up';
  }

function _qwenRollCompositionText(direction, degrees) {
    return '调整画面构图，用' + direction + '约' + degrees + '度 对角线构图';
  }

function _qwenAngleDescriptor(horizontal, vertical, zoom, roll, mode) {
    var h = ((parseFloat(horizontal) || 0) % 360 + 360) % 360;
    var v = parseFloat(vertical);
    if (!Number.isFinite(v)) v = 0;
    var z = parseFloat(zoom);
    if (!Number.isFinite(z)) z = 5;
    var r = parseFloat(roll);
    if (!Number.isFinite(r)) r = 0;
    if (_isQwenAngleNeutral(h, v, z, r)) return '';
    var rollDirectionZh = r > 0 ? '顺时针' : '逆时针';
    var rollDegrees = Math.abs(Math.round(r));
    var rollText = Math.abs(r) < 1 ? ''
      : '，' + _qwenRollCompositionText(rollDirectionZh, rollDegrees);
    return '<sks> ' + _qwenNativeHorizontalText(h) + ' '
      + _qwenNativeVerticalText(v) + ' '
      + _qwenNativeDistanceText(z)
      + rollText;
  }

function _qwenAnglePromptFromFieldValues(fieldValues) {
    var values = fieldValues || {};
    for (var key in values) {
      if (!Object.prototype.hasOwnProperty.call(values, key) || key.indexOf('::') < 0) continue;
      var parts = String(key).split('::');
      if (parts.length !== 2 || parts[1] !== 'horizontal_angle') continue;
      var nodeId = parts[0];
      var h = values[nodeId + '::horizontal_angle'];
      var v = values[nodeId + '::vertical_angle'];
      var z = values[nodeId + '::zoom'];
      if (h === undefined || v === undefined || z === undefined) continue;
      return _qwenAngleDescriptor(h, v, z, _currentQwenRoll(), _currentQwenAngleMode());
    }
    return '';
  }

function _currentQwenAngleRoot() {
    return document.querySelector('#quickFormFields .qwen-angle-control');
  }

function _isQwenAngleControlEnabled(root) {
    return !!(root && root.dataset && root.dataset.angleEnabled === '1');
  }

function _isCurrentQwenAngleEnabled() {
    return _isQwenAngleControlEnabled(_currentQwenAngleRoot());
  }

function _isQwenAngleControlNeutral(root) {
    if (!root) return true;
    var h = root.querySelector('[data-angle-field="horizontal_angle"]');
    var v = root.querySelector('[data-angle-field="vertical_angle"]');
    var z = root.querySelector('[data-angle-field="zoom"]');
    var r = root.querySelector('[data-angle-roll]');
    return _isQwenAngleNeutral(
      h ? h.value : 0,
      v ? v.value : 0,
      z ? z.value : 5,
      r ? r.value : 0
    );
  }

function _isQwenAngleControlActive(root) {
    return _isQwenAngleControlEnabled(root) && !_isQwenAngleControlNeutral(root);
  }

function _isCurrentQwenAngleActive() {
    return _isQwenAngleControlActive(_currentQwenAngleRoot());
  }

function _qwenAngleMode(root) {
    return root && root.dataset && root.dataset.angleMode === 'subject' ? 'subject' : 'camera';
  }

function _currentQwenAngleMode() {
    return _qwenAngleMode(_currentQwenAngleRoot());
  }

function _setQwenAngleMode(root, mode) {
    if (!root) return;
    var next = mode === 'subject' ? 'subject' : 'camera';
    root.dataset.angleMode = next;
    root.querySelectorAll('[data-angle-mode]').forEach(function(btn) {
      var active = btn.dataset.angleMode === next;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    _syncQwenAngleControl(root);
  }

function _setQwenAngleCollapsed(root, collapsed) {
    if (!root) return;
    var isCollapsed = !!collapsed;
    root.dataset.angleCollapsed = isCollapsed ? '1' : '0';
    root.classList.toggle('is-collapsed', isCollapsed);
    var body = root.querySelector('[data-angle-body]');
    if (body) body.hidden = isCollapsed;
    var btn = root.querySelector('[data-angle-collapse]');
    if (btn) btn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  }

function _setQwenAngleEnabled(root, enabled, expand) {
    if (!root) return;
    var isEnabled = !!enabled;
    root.dataset.angleEnabled = isEnabled ? '1' : '0';
    root.classList.toggle('is-active', isEnabled);
    root.classList.toggle('is-disabled', !isEnabled);
    var btn = root.querySelector('[data-angle-enable]');
    if (btn) {
      btn.setAttribute('aria-pressed', isEnabled ? 'true' : 'false');
      var label = btn.querySelector('[data-angle-enable-label]');
      if (label) label.textContent = isEnabled ? '已开启' : '开启';
    }
    var state = root.querySelector('[data-angle-state]');
    if (state) state.textContent = isEnabled ? '启用' : '关闭';
    if (expand) _setQwenAngleCollapsed(root, false);
    _syncQwenAngleControl(root);
  }

function _currentQwenRoll() {
    var root = _currentQwenAngleRoot();
    if (!_isQwenAngleControlEnabled(root)) return 0;
    var input = root.querySelector('[data-angle-roll]');
    if (!input) return 0;
    var r = parseFloat(input.value);
    return Number.isFinite(r) ? r : 0;
  }

function _currentQwenAnglePrompt(fieldValues) {
    var root = _currentQwenAngleRoot();
    if (root && !_isQwenAngleControlEnabled(root)) return '';
    var fromFields = _qwenAnglePromptFromFieldValues(fieldValues);
    if (fromFields) return fromFields;
    if (!root) return '';
    var h = root.querySelector('[data-angle-field="horizontal_angle"]');
    var v = root.querySelector('[data-angle-field="vertical_angle"]');
    var z = root.querySelector('[data-angle-field="zoom"]');
    if (!h || !v || !z) return '';
    return _qwenAngleDescriptor(h.value, v.value, z.value, _currentQwenRoll(), _currentQwenAngleMode());
  }

function _stripExistingQwenAngleMarkers(prompt) {
    return String(prompt || '')
      .replace(/(^|[\n\r])\s*<sks>[^\n\r。！？!?;；]*(?:[。！？!?;；])?/gi, '$1')
      .replace(/\s*<sks>[^\n\r。！？!?;；]*(?:[。！？!?;；])?/gi, ' ');
  }

function _isConflictingQwenCameraClause(text) {
    var s = String(text || '').toLowerCase();
    if (!s.trim()) return false;
    if (s.indexOf('<sks>') >= 0) return true;
    var hasCameraContext = /(镜头|机位|相机|摄像机|手机|拍摄|视角|视点|透视|焦距|景深|构图镜头|camera|lens|viewpoint|shot|angle|perspective|focal|depth of field)/i.test(s);
    var hasCameraAngle = /(俯视|俯拍|仰视|仰拍|平视|低角度|高角度|正面视角|侧面视角|背面视角|四分之三|三分之二|水平偏转|画面\s*roll|roll\s*倾斜|顺时针|逆时针|yaw|pitch|front view|side view|back view|low-angle|high-angle|eye-level|elevated|close-up|wide shot|medium shot)/i.test(s);
    var standaloneCameraAngle = /^\s*(?:约|大约|轻微|明显|近似|略微|slightly|strongly)?\s*(?:低角度|高角度|俯视|俯拍|仰视|仰拍|平视|正面视角|侧面视角|背面视角|front view|side view|back view|low-angle|high-angle|eye-level|elevated|close-up|wide shot|medium shot)/i.test(s);
    return standaloneCameraAngle || (hasCameraContext && hasCameraAngle);
  }

function _removePromptClausesMatching(prompt, matcher) {
    var text = String(prompt || '');
    var parts = text.split(/([，,。！？!?；;\n\r]+)/);
    var kept = [];
    for (var i = 0; i < parts.length; i += 2) {
      var clause = parts[i] || '';
      var delimiter = parts[i + 1] || '';
      if (matcher(clause)) continue;
      kept.push(clause + delimiter);
    }
    return kept.join('');
  }

function _sanitizePromptForQwenAngle(prompt) {
    var cleaned = _stripExistingQwenAngleMarkers(prompt);
    cleaned = _removePromptClausesMatching(cleaned, _isConflictingQwenCameraClause);
    return cleaned
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/\s+([，,。！？!?；;])/g, '$1')
      .replace(/([，,；;]){2,}/g, '$1')
      .replace(/^[\s，,。！？!?；;]+|[\s，,。！？!?；;]+$/g, '')
      .replace(/[\n\r]{3,}/g, '\n\n')
      .trim();
  }

function _preparePromptForCurrentQwenAngle(prompt) {
    if (!_currentQwenAnglePrompt()) return String(prompt || '');
    return _sanitizePromptForQwenAngle(prompt);
  }

  function _promptWithQwenAngle(prompt, fieldValues) {
    var anglePrompt = _currentQwenAnglePrompt(fieldValues);
    if (!anglePrompt) return prompt;
    var base = _sanitizePromptForQwenAngle(prompt);
    if (!base) return anglePrompt;
    return anglePrompt + '\n' + base;
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
    if (key === '__qwen_frame_roll') {
      var rollRoot = _currentQwenAngleRoot();
      if (rollRoot) {
        var rollInput = _qwenAngleInput(rollRoot, 'roll');
        if (rollInput) rollInput.value = String(Math.round(_clampQwenAngleValue(rollInput, value)));
        if (Math.abs(parseFloat(value) || 0) >= 0.5) _setQwenAngleEnabled(rollRoot, true, true);
        else _syncQwenAngleControl(rollRoot);
      }
      return true;
    }
    if (key === '__qwen_angle_mode') {
      var modeRoot = _currentQwenAngleRoot();
      if (modeRoot) {
        _setQwenAngleMode(modeRoot, value === 'subject' ? 'subject' : 'camera');
      }
      return true;
    }
    var el = document.querySelector('#advFields [data-key="' + key + '"], #quickFormFields [data-key="' + key + '"]');
    if (!el) return false;
    if (el.type === 'checkbox') {
      el.checked = !!value && value !== 'false' && value !== 'False';
      el.value = el.checked;
    } else {
      el.value = value;
    }
    if (el.dataset && el.dataset.type === 'video_mode') _syncVideoModeUi();
    if (el.dataset && el.dataset.angleField) {
      var root = el.closest('.qwen-angle-control');
      if (root && String(value) !== String(el.dataset.angleDefault || '')) _setQwenAngleEnabled(root, true, true);
      if (root) _syncQwenAngleControl(root);
    }
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

function _isReusableLoadImageField(key, fieldsMeta) {
    key = String(key || '');
    var fields = fieldsMeta || A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if ((f.node_id + '::' + f.field) !== key) continue;
      return f.class_type === 'LoadImage' && f.field === 'image';
    }
    return key.endsWith('::image');
  }

function _restoreRefImageValue(value) {
    var refValue = String(value || '').trim();
    if (!refValue) return false;
    var vInput = document.querySelector('#refImageValue');
    var preview = document.querySelector('#refImagePreview');
    var ph = document.querySelector('#refImagePlaceholder');
    if (!vInput) return false;
    vInput.value = refValue;
    if (preview) {
      preview.src = API + '/api/input-image/' + encodeURIComponent(refValue);
      preview.style.display = '';
      preview.classList.remove('hidden');
    }
    if (ph) ph.style.display = 'none';
    _syncQwenAngleReferencePreview();
    return true;
  }

function _restoreRefImageFromFieldValues(fieldValues, fieldsMeta) {
    var values = fieldValues || {};
    for (const [k, v] of Object.entries(values)) {
      if (!_isReusableLoadImageField(k, fieldsMeta)) continue;
      if (_restoreRefImageValue(v)) return true;
    }
    return false;
  }

async function fillFormFromHistory(idx, key) {
    let h = _historyItemByKey(key) || historyItems[idx];
    if (!h) return;
    if (h.__compact && window.CW && typeof window.CW.getHistoryDetail === 'function') {
      try {
        h = await window.CW.getHistoryDetail(h) || h;
      } catch (e) {
        if (window.CW && CW.toast) CW.toast(e && e.message ? e.message : '加载复刻信息失败', 'error');
        return;
      }
    }
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
      _restoreRefImageFromFieldValues(h.field_values, reuseFieldsMeta);
    }
    if (reusedPrompt || h.prompt) {
      _setPromptInputValue(_preparePromptForCurrentQwenAngle(reusedPrompt || h.prompt));
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
      if (snap.workflow && (!A.currentWF || snap.workflow.replace('.json','') !== A.currentWF.replace('.json','')) && window.CW.selectWF) {
        await window.CW.selectWF(snap.workflow);
      }
      if (snap.prompt) { _setPromptInputValue(snap.prompt); }
      if (snap.width) { var wi = $('#widthInput'); if (wi) wi.value = snap.width; }
      if (snap.height) { var hi = $('#heightInput'); if (hi) hi.value = snap.height; }
      for (const [k, v] of Object.entries(snap.adv || {})) {
        _setFieldControlValue(k, v);
      }
      _restoreRefImageFromFieldValues(snap.adv || {});
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
      _restoreRefImageFromFieldValues(j.fields);
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
    const rawPrompt = ($('#promptInput') || {}).value || '';
    _applyCurrentSizeLimit();
    const snapshot = { workflow: A.currentWF, prompt: rawPrompt, width: ($('#widthInput') || {}).value || 0, height: ($('#heightInput') || {}).value || 0, adv: {} };
    let submitFieldsMeta = [];
    const promptKeys = [];
    let qwenAngleEnabled = false;

    try {
      await _waitForRefImageUpload();
      await _waitForRefVideoUpload();
      await _waitForDirectorUploads();
      qwenAngleEnabled = _isCurrentQwenAngleActive();
      submitFieldsMeta = await _getSubmitFieldsMeta();
      let promptFieldCount = 0;
      for (const f of submitFieldsMeta || []) {
        // Pre-set default value for this field (including hidden)
        if (_isQwenAngleField(f) && !qwenAngleEnabled) continue;
        fields[f.node_id + '::' + f.field] = f.value;
        const zone = f.zone || 'advanced';
        const key = `${f.node_id}::${f.field}`;
        // Text-encode in user_input zone → main prompt
        if (_isPromptSubmitField(f)) {
          fields[key] = rawPrompt;
          promptKeys.push(key);
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
          if (refVal) {
            fields[key] = refVal;
            snapshot.adv[key] = refVal;
          }
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
      if (rawPrompt && $('#promptInput') && promptFieldCount === 0) {
        throw new Error('未找到可提交的提示词字段，请重新选择工作流后再出图');
      }
    } catch (e) {
      console.error(e);
      alert('出图失败: ' + (e.message || '提示词字段读取失败'));
      btn.disabled = false;
      btn.innerHTML = CW.icon('play') + ' 开始生成';
      return;
    }

    _syncDirectorInputs();
    const seenSubmitControls = new Set();
    const collectSubmitControl = (el) => {
      if (!el || seenSubmitControls.has(el)) return;
      seenSubmitControls.add(el);
      const angleRoot = el.closest && el.closest('.qwen-angle-control');
      if (angleRoot && !_isQwenAngleControlActive(angleRoot)) return;
      fields[el.dataset.key] = _readFieldControlValue(el);
      snapshot.adv[el.dataset.key] = fields[el.dataset.key];
    };
    $$('#quickFormFields [data-key]').forEach(collectSubmitControl);
    $$('#directorPanel [data-key]').forEach(collectSubmitControl);

    $$('#advFields [data-key]').forEach(collectSubmitControl);

    if (qwenAngleEnabled) {
      const qwenFrameRoll = _currentQwenRoll();
      snapshot.adv.__qwen_frame_roll = qwenFrameRoll;
      snapshot.adv.__qwen_angle_mode = _currentQwenAngleMode();
    }

    const prompt = _promptWithQwenAngle(rawPrompt, fields);
    promptKeys.forEach((key) => {
      fields[key] = prompt;
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
        _local_submitted_at: Date.now(),
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
      btn.innerHTML = CW.icon('play') + ' 开始生成';
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
    var buttons = [$('#interrogatePromptBtn'), $('#promptInterrogateRunBtn'), $('#promptInterrogateExpertRunBtn'), $('#promptInterrogateTeamRunBtn')];
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!btn) continue;
      btn.disabled = !!isLoading;
      btn.classList.toggle('is-loading', !!isLoading);
      if (isLoading) {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' ' + (label || '反推中');
      } else if (btn.id === 'interrogatePromptBtn') {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">图片反推</span>';
      } else if (btn.id === 'promptInterrogateExpertRunBtn') {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('zap') : '') + ' 加强';
      } else if (btn.id === 'promptInterrogateTeamRunBtn') {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('users') : '') + ' 专家';
      } else {
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 标准';
      }
    }
  }

  function _startPromptInterrogateTask(refVal, options) {
    if (!refVal) return;
    options = options || {};
    if (_promptInterrogateRunning) {
      if (window.CW && CW.toast) CW.toast('图片反推正在后台运行', 'info');
      return;
    }
    _promptInterrogateRunning = true;
    var level = Number(options.level);
    if (!isFinite(level)) level = options.expertTeam ? 2 : (options.expert ? 1 : 0);
    _setPromptInterrogateLoading(true, level >= 2 ? '专家反推中' : (level >= 1 ? '加强反推中' : '标准反推中'));
    if (window.CW && CW.closePromptInterrogateModal) CW.closePromptInterrogateModal();
    if (window.CW && typeof CW.showPromptInterrogatePendingToast === 'function') {
      CW.showPromptInterrogatePendingToast();
    } else if (window.CW && CW.toast) {
      CW.toast('后台努力反推中，请稍后……', 'info');
    }
    _runPromptInterrogate(refVal, options).then(function(result) {
      var prompt = result && result.prompt ? result.prompt : '';
      if (window.CW && typeof CW.showPromptResultToast === 'function') {
        var meta = result && result.data ? result.data : {};
        meta._source_image = refVal;
        if (!meta.source_image) meta.source_image = refVal;
        CW.showPromptResultToast(prompt, meta);
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

  async function _runPromptInterrogate(refVal, options) {
    var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
    var response = await fetcher(API + '/api/prompt/interrogate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_promptInterrogatePayload(refVal, options || {}))
    });
    var data = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(data.detail || data.message || '图片反推失败');
    var prompt = String(data.structured_optimized_prompt || data.prompt || data.promptgen || data.wd14_tags || '').trim();
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
            '<button class="prompt-tool-btn" type="button" id="promptInterrogateRunBtn" disabled>' + (window.CW && CW.icon ? CW.icon('image') : '') + ' 标准</button>' +
            '<button class="prompt-tool-btn prompt-interrogate-expert-btn" type="button" id="promptInterrogateExpertRunBtn" disabled>' + (window.CW && CW.icon ? CW.icon('zap') : '') + ' 加强</button>' +
            '<button class="prompt-tool-btn prompt-interrogate-team-btn" type="button" id="promptInterrogateTeamRunBtn" disabled>' + (window.CW && CW.icon ? CW.icon('users') : '') + ' 专家</button>' +
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
    var expertRunBtn = $('#promptInterrogateExpertRunBtn');
    var teamRunBtn = $('#promptInterrogateTeamRunBtn');
    var uploadedName = String(initialImage || '').trim();
    if (!zone || !fileInput || !runBtn || !expertRunBtn || !teamRunBtn) return;

    if (uploadedName) {
      if (preview) {
        preview.src = API + '/api/input-image/' + encodeURIComponent(uploadedName);
        preview.style.display = '';
        preview.classList.remove('hidden');
      }
      var ph = zone.querySelector('.img-upload-placeholder');
      if (ph) ph.style.display = 'none';
      runBtn.disabled = false;
      expertRunBtn.disabled = false;
      teamRunBtn.disabled = false;
    }

    async function useFile(file) {
      if (!file) return;
      runBtn.disabled = true;
      expertRunBtn.disabled = true;
      teamRunBtn.disabled = true;
      runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 上传中';
      expertRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 上传中';
      teamRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 上传中';
      runBtn.classList.add('is-loading');
      expertRunBtn.classList.add('is-loading');
      teamRunBtn.classList.add('is-loading');
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
        expertRunBtn.disabled = false;
        teamRunBtn.disabled = false;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 标准';
        expertRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('zap') : '') + ' 加强';
        teamRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('users') : '') + ' 专家';
      } catch (e) {
        if (window.CW && CW.toast) CW.toast(e.message || '图片上传失败', 'error');
        runBtn.disabled = true;
        expertRunBtn.disabled = true;
        teamRunBtn.disabled = true;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 标准';
        expertRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('zap') : '') + ' 加强';
        teamRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('users') : '') + ' 专家';
      } finally {
        runBtn.classList.remove('is-loading');
        expertRunBtn.classList.remove('is-loading');
        teamRunBtn.classList.remove('is-loading');
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
      _startPromptInterrogateTask(uploadedName, { level: 0 });
    });
    expertRunBtn.addEventListener('click', async function() {
      if (!uploadedName) return;
      _startPromptInterrogateTask(uploadedName, { level: 1 });
    });
    teamRunBtn.addEventListener('click', async function() {
      if (!uploadedName) return;
      _startPromptInterrogateTask(uploadedName, { level: 2 });
    });
  }


  // Shared across modules via __APP__
  var _wfFieldMeta = window.__APP__._wfFieldMeta || [];
  window.__APP__._wfFieldMeta = _wfFieldMeta;

  var _loadImageFields = window.__APP__._loadImageFields || [];
  window.__APP__._loadImageFields = _loadImageFields;

function _qwenAngleFieldValue(field, fallback) {
    if (!field) return fallback;
    var value = field.value;
    if (value === undefined || value === null || value === '') return fallback;
    return value;
  }

function _qwenAngleNumberInput(field, axis, fallback) {
    var key = String(field.node_id || '') + '::' + String(field.field || '');
    var value = _qwenAngleFieldValue(field, fallback);
    var step = axis === 'zoom' ? 0.5 : (field.step || 1);
    return '<input class="qwen-angle-value" type="hidden" data-key="' + escA(key) + '" data-type="number" data-angle-field="' + escA(axis) + '" data-angle-default="' + escA(String(value)) + '" value="' + escA(String(value)) + '"' + _numberAttr('min', field.min) + _numberAttr('max', field.max) + _numberAttr('step', step) + '>';
  }

function _qwenAngleHiddenInput(field, fallback) {
    if (!field) return '';
    var key = String(field.node_id || '') + '::' + String(field.field || '');
    var type = field.type === 'toggle' ? 'bool' : 'number';
    return '<input type="hidden" data-key="' + escA(key) + '" data-type="' + escA(type) + '" value="' + escA(String(_qwenAngleFieldValue(field, fallback))) + '">';
  }

function _qwenAngleControlHtml(group) {
    var fields = group.fields || {};
    var h = fields.horizontal_angle;
    var v = fields.vertical_angle;
    var z = fields.zoom;
    var cameraIcon = window.CW && CW.icon ? CW.icon('camera') : '<span>CAM</span>';
    var resetIcon = window.CW && CW.icon ? CW.icon('refresh-cw') : '<span aria-hidden="true">↺</span>';
    var slidersIcon = window.CW && CW.icon ? CW.icon('sliders') : '<span aria-hidden="true">▣</span>';
    var collapseIcon = window.CW && CW.icon ? CW.icon('chevron-right') : '<span aria-hidden="true">›</span>';
    var zoomTickHtml = '<span style="left:0%">0</span><span style="left:25%">2.5</span><span style="left:50%">5</span><span style="left:75%">7.5</span><span style="left:100%">10</span>';
    var rollTickHtml = '<span style="left:0%">-45°</span><span style="left:16.666%">-30°</span><span style="left:33.333%">-15°</span><span style="left:50%">0°</span><span style="left:66.666%">15°</span><span style="left:83.333%">30°</span><span style="left:100%">45°</span>';
    var orbitTickHtml = '<span class="qwen-angle-orbit-ring" style="--qwen-orbit-size:12.666%"><b>15°</b></span>'
      + '<span class="qwen-angle-orbit-ring" style="--qwen-orbit-size:25.333%"><b>30°</b></span>'
      + '<span class="qwen-angle-orbit-ring" style="--qwen-orbit-size:38%"><b>45°</b></span>'
      + '<span class="qwen-angle-orbit-ring" style="--qwen-orbit-size:50.666%"><b>60°</b></span>';
    var zoomListId = 'qwenZoomTicks-' + escA(group.node_id || '0');
    var rollListId = 'qwenRollTicks-' + escA(group.node_id || '0');
    return '' +
      '<div class="fg qwen-angle-control is-disabled is-collapsed" data-qwen-angle-node="' + escA(group.node_id || '') + '" data-angle-enabled="0" data-angle-collapsed="1" data-angle-mode="camera">' +
        '<div class="qwen-angle-head">' +
          '<div class="qwen-angle-title">' +
            '<label>相机调整</label>' +
            '<span data-angle-state>关闭</span>' +
          '</div>' +
          '<div class="qwen-angle-head-actions">' +
            '<button class="qwen-angle-enable" type="button" data-angle-enable aria-pressed="false" title="开启相机调整" aria-label="开启相机调整">' + slidersIcon + '<span data-angle-enable-label>开启</span></button>' +
            '<button class="qwen-angle-collapse" type="button" data-angle-collapse aria-expanded="false" title="收展相机调整" aria-label="收展相机调整">' + collapseIcon + '</button>' +
          '</div>' +
        '</div>' +
        '<span class="qwen-angle-prompt" data-angle-prompt></span>' +
        '<div class="qwen-angle-body" data-angle-body hidden>' +
        '<div class="qwen-angle-mode" role="group" aria-label="控制目标">' +
          '<button class="active" type="button" data-angle-mode="camera" aria-pressed="true">控制相机</button>' +
          '<button type="button" data-angle-mode="subject" aria-pressed="false">只控制主体</button>' +
        '</div>' +
        '<div class="qwen-angle-stage" data-angle-plane tabindex="0" role="application" aria-label="拖动相机点调整上下左右方向">' +
          '<div class="qwen-angle-scene">' +
            '<div class="qwen-angle-plane">' +
              orbitTickHtml +
              '<div class="qwen-angle-axis qwen-angle-axis-x"></div>' +
              '<div class="qwen-angle-axis qwen-angle-axis-y"></div>' +
              '<span class="qwen-angle-axis-label qwen-angle-axis-left">L</span>' +
              '<span class="qwen-angle-axis-label qwen-angle-axis-right">R</span>' +
              '<span class="qwen-angle-axis-label qwen-angle-axis-top">UP</span>' +
              '<span class="qwen-angle-axis-label qwen-angle-axis-bottom">DOWN</span>' +
              '<div class="qwen-angle-reference-frame" aria-hidden="true"></div>' +
              '<div class="qwen-angle-card">' +
                '<div class="qwen-angle-card-face qwen-angle-card-front"><span>IMG</span></div>' +
                '<div class="qwen-angle-card-face qwen-angle-card-side qwen-angle-card-right"></div>' +
                '<div class="qwen-angle-card-face qwen-angle-card-side qwen-angle-card-left"></div>' +
                '<div class="qwen-angle-card-face qwen-angle-card-side qwen-angle-card-top"></div>' +
                '<div class="qwen-angle-card-face qwen-angle-card-side qwen-angle-card-bottom"></div>' +
              '</div>' +
              '<div class="qwen-angle-camera-ray" aria-hidden="true"></div>' +
              '<button class="qwen-angle-camera" type="button" data-angle-camera aria-label="当前相机位置"><span class="qwen-angle-camera-frame">' + cameraIcon + '</span></button>' +
              '<div class="qwen-angle-readout" aria-label="当前坐标参数">' +
                '<span>X/Yaw <b data-angle-output="horizontal_angle"></b></span>' +
                '<span>Y/Pitch <b data-angle-output="vertical_angle"></b></span>' +
                '<span>C-axis <b data-angle-output="zoom"></b></span>' +
                '<span>Z/Roll <b data-angle-output="roll"></b></span>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="qwen-angle-presets" aria-label="角度预设">' +
          '<button type="button" data-angle-reset title="复原" aria-label="复原">' + resetIcon + '<span>复原</span></button>' +
          '<button type="button" data-angle-preset="h:0,v:0,z:5">正面</button>' +
          '<button type="button" data-angle-preset="h:180,v:0,z:5">背面</button>' +
        '</div>' +
        '<div class="qwen-angle-slider qwen-angle-distance" aria-label="距离">' +
          '<div class="qwen-angle-slider-head"><span>C-axis 距离</span><b data-angle-slider-value="zoom"></b></div>' +
          '<input class="qwen-angle-range" type="range" data-angle-slider="zoom" min="0" max="10" step="0.5" list="' + zoomListId + '" value="' + escA(String(_qwenAngleFieldValue(z, 5))) + '" aria-label="镜头距离">' +
          '<datalist id="' + zoomListId + '"><option value="0"></option><option value="2.5"></option><option value="5"></option><option value="7.5"></option><option value="10"></option></datalist>' +
          '<div class="qwen-angle-slider-ticks" aria-hidden="true">' + zoomTickHtml + '</div>' +
        '</div>' +
        '<div class="qwen-angle-slider qwen-angle-roll" aria-label="Z轴倾角">' +
          '<div class="qwen-angle-slider-head"><span>Z/Roll 图片旋转</span><b data-angle-slider-value="roll"></b></div>' +
          '<input class="qwen-angle-range qwen-angle-roll-value" type="range" data-angle-slider="roll" data-angle-roll data-angle-default="0" min="-45" max="45" step="1" list="' + rollListId + '" value="0" aria-label="图片旋转角度">' +
          '<datalist id="' + rollListId + '"><option value="-45"></option><option value="-30"></option><option value="-15"></option><option value="0"></option><option value="15"></option><option value="30"></option><option value="45"></option></datalist>' +
          '<div class="qwen-angle-slider-ticks" aria-hidden="true">' + rollTickHtml + '</div>' +
        '</div>' +
        _qwenAngleNumberInput(h, 'horizontal_angle', 0) +
        _qwenAngleNumberInput(v, 'vertical_angle', 0) +
        _qwenAngleNumberInput(z, 'zoom', 5) +
        _qwenAngleHiddenInput(fields.default_prompts, true) +
        _qwenAngleHiddenInput(fields.camera_view, false) +
        '</div>' +
      '</div>';
  }

function _syncQwenAngleReferencePreview() {
    var preview = $('#refImagePreview');
    var src = preview && preview.src && preview.style.display !== 'none' ? preview.src : '';
    $$('.qwen-angle-card-front').forEach(function(face) {
      var old = face.querySelector('img');
      if (!src) {
        if (old) old.remove();
        if (!face.querySelector('span')) face.innerHTML = '<span>IMG</span>';
        return;
      }
      if (!old) {
        face.innerHTML = '<img alt="">';
        old = face.querySelector('img');
      }
      old.src = src;
    });
  }

function _syncQwenAngleRange(root, axis, value, label) {
    var slider = root && root.querySelector('[data-angle-slider="' + axis + '"]');
    if (slider) {
      var next = String(value);
      if (slider.value !== next) slider.value = next;
      var min = parseFloat(slider.getAttribute('min'));
      var max = parseFloat(slider.getAttribute('max'));
      var pct = 0;
      if (Number.isFinite(min) && Number.isFinite(max) && max !== min) {
        pct = (parseFloat(value) - min) / (max - min) * 100;
      }
      pct = Math.max(0, Math.min(100, pct));
      slider.style.setProperty('--qwen-slider-fill', pct.toFixed(1) + '%');
    }
    var output = root && root.querySelector('[data-angle-slider-value="' + axis + '"]');
    if (output) output.textContent = label;
  }

function _qwenPitchToMarkerY(pitch) {
    return 50 - _qwenPitchToNorm(pitch) * _qwenOrbitRadius();
  }

function _qwenMarkerYToPitch(y) {
    var normalized = Math.max(0, Math.min(1, y));
    return _qwenNormToPitch((0.5 - normalized) / 0.38);
  }

function _qwenOrbitRadius() {
    return 38;
  }

function _qwenPitchToNorm(pitch) {
    var clamped = Math.max(-30, Math.min(60, parseFloat(pitch) || 0));
    return clamped >= 0 ? clamped / 60 : clamped / 30;
  }

function _qwenNormToPitch(norm) {
    var n = Math.max(-1, Math.min(1, parseFloat(norm) || 0));
    return n >= 0 ? n * 60 : n * 30;
  }

function _qwenOrbitVector(horizontal, vertical) {
    var x = Math.max(-1, Math.min(1, _qwenSignedYaw(horizontal) / 90));
    var y = Math.max(-1, Math.min(1, _qwenPitchToNorm(vertical)));
    var len = Math.sqrt(x * x + y * y);
    if (len > 1) {
      x = x / len;
      y = y / len;
    }
    return { x: x, y: y };
  }

function _syncQwenAngleControl(root) {
    if (!root) return;
    var hEl = root.querySelector('[data-angle-field="horizontal_angle"]');
    var vEl = root.querySelector('[data-angle-field="vertical_angle"]');
    var zEl = root.querySelector('[data-angle-field="zoom"]');
    var rEl = root.querySelector('[data-angle-roll]');
    if (!hEl || !vEl || !zEl) return;
    var h = parseFloat(hEl.value) || 0;
    var v = parseFloat(vEl.value) || 0;
    var z = parseFloat(zEl.value);
    if (!Number.isFinite(z)) z = 5;
    var r = parseFloat(rEl && rEl.value);
    if (!Number.isFinite(r)) r = 0;
    root.style.setProperty('--qwen-angle-y', (-h) + 'deg');
    root.style.setProperty('--qwen-angle-x', Math.max(-60, Math.min(60, v)) + 'deg');
    root.style.setProperty('--qwen-image-scale', (0.72 + Math.max(0, Math.min(10, z)) * 0.058).toFixed(3));
    root.style.setProperty('--qwen-image-roll', r.toFixed(1) + 'deg');
    var signedYaw = _qwenSignedYaw(h);
    var pitch = Math.max(-30, Math.min(60, v));
    var depth = Math.max(0, Math.min(10, z));
    var orbit = _qwenOrbitVector(h, pitch);
    var radius = _qwenOrbitRadius();
    var markerX = 50 + orbit.x * radius;
    var markerY = 50 - orbit.y * radius;
    var markerScale = 0.94 + depth * 0.018;
    markerX = Math.max(10, Math.min(90, markerX));
    markerY = Math.max(8, Math.min(88, markerY));
    var rayAngle = Math.atan2(50 - markerY, 50 - markerX) * 180 / Math.PI;
    var rayLength = Math.sqrt(Math.pow(50 - markerX, 2) + Math.pow(50 - markerY, 2));
    root.style.setProperty('--qwen-camera-left', markerX.toFixed(2) + '%');
    root.style.setProperty('--qwen-camera-top', markerY.toFixed(2) + '%');
    root.style.setProperty('--qwen-camera-scale', markerScale.toFixed(3));
    root.style.setProperty('--qwen-camera-ray-angle', rayAngle.toFixed(2) + 'deg');
    root.style.setProperty('--qwen-camera-ray-length', rayLength.toFixed(2) + '%');
    root.style.setProperty('--qwen-distance-fill', Math.max(0, Math.min(100, depth * 10)).toFixed(1) + '%');
    root.style.setProperty('--qwen-roll-fill', Math.max(0, Math.min(100, ((r + 45) / 90) * 100)).toFixed(1) + '%');
    _syncQwenAngleRange(root, 'zoom', depth.toFixed(1), z.toFixed(1));
    _syncQwenAngleRange(root, 'roll', Math.round(r), Math.round(r) + '°');
    var outputs = {
      horizontal_angle: Math.round(signedYaw) + '°',
      vertical_angle: Math.round(v) + '°',
      zoom: z.toFixed(1),
      roll: Math.round(r) + '°'
    };
    Object.keys(outputs).forEach(function(axis) {
      var output = root.querySelector('[data-angle-output="' + axis + '"]');
      if (output) output.textContent = outputs[axis];
    });
    var prompt = root.querySelector('[data-angle-prompt]');
    if (prompt) prompt.textContent = _isQwenAngleControlEnabled(root) ? _qwenAngleDescriptor(h, v, z, r, _qwenAngleMode(root)) : '';
    _syncQwenAngleReferencePreview();
  }

function _qwenAngleInput(root, axis) {
    if (axis === 'roll') return root ? root.querySelector('[data-angle-roll]') : null;
    return root ? root.querySelector('[data-angle-field="' + axis + '"]') : null;
  }

function _clampQwenAngleValue(input, value) {
    var n = parseFloat(value);
    if (!Number.isFinite(n)) n = 0;
    var min = parseFloat(input.getAttribute('min'));
    var max = parseFloat(input.getAttribute('max'));
    if (Number.isFinite(min)) n = Math.max(min, n);
    if (Number.isFinite(max)) n = Math.min(max, n);
    return n;
  }

function _setQwenAngleValue(root, axis, value) {
    var input = _qwenAngleInput(root, axis);
    if (!input) return;
    var next = _clampQwenAngleValue(input, value);
    var step = parseFloat(input.getAttribute('step') || '1');
    if (Number.isFinite(step) && step > 0) next = Math.round(next / step) * step;
    input.value = String(next);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

function _setQwenAngles(root, values, activate) {
    values = values || {};
    if (activate !== false) _setQwenAngleEnabled(root, true, true);
    Object.keys(values).forEach(function(axis) {
      _setQwenAngleValue(root, axis, values[axis]);
    });
    _syncQwenAngleControl(root);
  }

function _applyQwenAngleSpherePoint(root, ev) {
    var stage = root && root.querySelector('[data-angle-plane]');
    if (!stage) return;
    var rect = stage.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var radiusPx = Math.min(rect.width, rect.height) * (_qwenOrbitRadius() / 100);
    var x = (ev.clientX - (rect.left + rect.width / 2)) / radiusPx;
    var y = ((rect.top + rect.height / 2) - ev.clientY) / radiusPx;
    var len = Math.sqrt(x * x + y * y);
    if (len > 1) {
      x = x / len;
      y = y / len;
    }
    var signedYaw = x * 90;
    _setQwenAngles(root, {
      horizontal_angle: signedYaw < 0 ? 360 + signedYaw : signedYaw,
      vertical_angle: _qwenNormToPitch(y)
    });
  }

function _resetQwenAngleControl(root) {
    ['horizontal_angle', 'vertical_angle', 'zoom', 'roll'].forEach(function(axis) {
      var input = _qwenAngleInput(root, axis);
      if (!input) return;
      _setQwenAngleValue(root, axis, input.dataset.angleDefault || input.value || 0);
    });
    _syncQwenAngleControl(root);
  }

function _initQwenAngleControls() {
    $$('.qwen-angle-control').forEach(function(root) {
      if (root.dataset.angleInited === '1') {
        _syncQwenAngleControl(root);
        return;
      }
      root.dataset.angleInited = '1';
      root.querySelectorAll('[data-angle-field], [data-angle-roll]').forEach(function(input) {
        input.addEventListener('input', function() { _syncQwenAngleControl(root); });
        input.addEventListener('change', function() { _syncQwenAngleControl(root); });
      });
      root.querySelectorAll('[data-angle-slider]').forEach(function(slider) {
        var syncSlider = function() {
          var sliderValue = slider.value;
          _setQwenAngleEnabled(root, true, true);
          var axis = slider.dataset.angleSlider;
          if (axis === 'zoom') _setQwenAngleValue(root, 'zoom', sliderValue);
          else _syncQwenAngleControl(root);
        };
        slider.addEventListener('input', syncSlider);
        slider.addEventListener('change', syncSlider);
      });
      root.querySelectorAll('[data-angle-mode]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          _setQwenAngleEnabled(root, true, true);
          _setQwenAngleMode(root, btn.dataset.angleMode || 'camera');
        });
      });
      var stage = root.querySelector('[data-angle-plane]');
      if (stage) {
        var dragging = false;
        var startDrag = function(ev) {
          dragging = true;
          _applyQwenAngleSpherePoint(root, ev);
        };
        var moveDrag = function(ev) {
          if (dragging) _applyQwenAngleSpherePoint(root, ev);
        };
        var stopDrag = function(ev) {
          dragging = false;
        };
        stage.addEventListener('pointerdown', function(ev) {
          stage.setPointerCapture && stage.setPointerCapture(ev.pointerId);
          startDrag(ev);
        });
        stage.addEventListener('pointermove', moveDrag);
        stage.addEventListener('pointerup', function(ev) {
          stage.releasePointerCapture && stage.releasePointerCapture(ev.pointerId);
          stopDrag(ev);
        });
        stage.addEventListener('pointercancel', function() { dragging = false; });
        stage.addEventListener('mousedown', startDrag);
        window.addEventListener('mousemove', moveDrag);
        window.addEventListener('mouseup', stopDrag);
        stage.addEventListener('touchstart', function(ev) {
          if (ev.touches && ev.touches[0]) startDrag(ev.touches[0]);
          ev.preventDefault();
        }, { passive: false });
        stage.addEventListener('touchmove', function(ev) {
          if (dragging && ev.touches && ev.touches[0]) moveDrag(ev.touches[0]);
          ev.preventDefault();
        }, { passive: false });
        stage.addEventListener('touchend', stopDrag);
        stage.addEventListener('keydown', function(ev) {
          var h = parseFloat((_qwenAngleInput(root, 'horizontal_angle') || {}).value) || 0;
          var v = parseFloat((_qwenAngleInput(root, 'vertical_angle') || {}).value) || 0;
          if (ev.key === 'ArrowLeft') { _setQwenAngles(root, { horizontal_angle: h - 5 }); ev.preventDefault(); }
          else if (ev.key === 'ArrowRight') { _setQwenAngles(root, { horizontal_angle: h + 5 }); ev.preventDefault(); }
          else if (ev.key === 'ArrowUp') { _setQwenAngles(root, { vertical_angle: v + 5 }); ev.preventDefault(); }
          else if (ev.key === 'ArrowDown') { _setQwenAngles(root, { vertical_angle: v - 5 }); ev.preventDefault(); }
          else if (ev.key === 'Home') { _resetQwenAngleControl(root); ev.preventDefault(); }
        });
      }
      root.querySelectorAll('[data-angle-enable]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var next = !_isQwenAngleControlEnabled(root);
          _setQwenAngleEnabled(root, next, next);
        });
      });
      root.querySelectorAll('[data-angle-collapse]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          _setQwenAngleCollapsed(root, root.dataset.angleCollapsed !== '1');
        });
      });
      root.querySelectorAll('[data-angle-reset]').forEach(function(btn) {
        btn.addEventListener('click', function() { _resetQwenAngleControl(root); });
      });
      root.querySelectorAll('[data-angle-preset]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var values = {};
          String(btn.dataset.anglePreset || '').split(',').forEach(function(part) {
            var spec = part.split(':');
            if (spec.length !== 2) return;
            var selector = spec[0] === 'h' ? 'horizontal_angle' : spec[0] === 'v' ? 'vertical_angle' : 'zoom';
            values[selector] = spec[1];
          });
          _setQwenAngles(root, values);
        });
      });
      _syncQwenAngleControl(root);
    });
  }

var _directorState = { workflow: '', segments: [] };
var _directorUploadPromise = Promise.resolve();
var _directorPendingShotImageId = '';

function _hasDirectorWorkflow(fields) {
    return (fields || A._wfFieldMeta || []).some(function(f) {
      return f && f.class_type === 'LTXDirector';
    });
  }

function _directorFieldKey(fieldName) {
    var fields = A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if (f.class_type === 'LTXDirector' && f.field === fieldName) return f.node_id + '::' + f.field;
    }
    return '';
  }

function _directorTotalFrames() {
    var fps = parseInt(($('#quickFormFields [data-key="320:300::value"]') || {}).value || ($('#advFields [data-key="320:300::value"]') || {}).value || 25, 10) || 25;
    var seconds = parseFloat(($('#quickFormFields [data-key="320:301::value"]') || {}).value || ($('#advFields [data-key="320:301::value"]') || {}).value || 5) || 5;
    return Math.max(1, Math.round(seconds * fps) + 1);
  }

function _directorSegmentId() {
    return 'seg_' + Date.now().toString(36) + '_' + Math.floor(Math.random() * 10000).toString(36);
  }

function _directorImageSrc(name) {
    name = String(name || '').trim();
    return name ? API + '/api/input-image/' + encodeURIComponent(name) : '';
  }

function _directorTimeToFrames(value, unit, fps) {
    value = String(value || '').replace('：', ':').trim();
    unit = String(unit || '').toLowerCase();
    if (value.indexOf(':') >= 0) {
      var parts = value.split(':');
      var minutes = parseFloat(parts[0]) || 0;
      var seconds = parseFloat(parts[1]) || 0;
      return Math.round((minutes * 60 + seconds) * fps);
    }
    var n = parseFloat(value);
    if (!isFinite(n)) return 0;
    if (unit === '帧' || unit === 'f' || unit === 'frame' || unit === 'frames') return Math.round(n);
    return Math.round(n * fps);
  }

function _directorCleanSegmentPrompt(text) {
    return String(text || '')
      .replace(/^\s*(?:[-*#>•]\s*)?(?:第?\s*\d+\s*(?:镜头|镜|分镜|场景|场|段|shot|scene)\s*[：:、.\-\s]*)?/i, '')
      .trim();
  }

function _directorFallbackPrompt() {
    return String((($('#promptInput') || {}).value || '')).trim();
  }

function _directorDefaultSegmentPrompt(seg, idx, segments) {
    var base = _directorFallbackPrompt();
    var hasPrev = idx > 0;
    var hasNext = idx < Math.max(0, (segments || []).length - 1);
    var transition = hasNext
      ? 'Smooth cinematic transition from this reference image to the next reference image, preserve subject identity, scene continuity, lighting continuity, camera motion continuity, no abrupt cut.'
      : (hasPrev
        ? 'Continue from the previous reference image into this final reference image with subtle natural motion, stable composition, consistent lighting, no abrupt cut.'
        : 'Animate this reference image with subtle natural motion, stable composition, consistent lighting, no abrupt cut.');
    return base ? (base + '\n' + transition) : transition;
  }

function _directorParsePromptSegments(text) {
    var prompt = String(text || '').trim();
    if (!prompt) return [];
    var fps = parseInt(($('#quickFormFields [data-key="320:300::value"]') || {}).value || ($('#advFields [data-key="320:300::value"]') || {}).value || 25, 10) || 25;
    var total = _directorTotalFrames();
    var rangeRe = /(?:^|\n)\s*(?:[-*#>•]\s*)?(?:第?\s*\d+\s*(?:镜头|镜|分镜|场景|场|段|shot|scene)\s*[：:、.\-\s]*)?(\d+[:：]\d+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(秒|s|S|帧|f|frame|frames)?\s*(?:-|–|—|~|～|至|到)\s*(\d+[:：]\d+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(秒|s|S|帧|f|frame|frames)?\s*[：:、,\-\s]*/g;
    var matches = [], m;
    while ((m = rangeRe.exec(prompt)) !== null) {
      matches.push({ index: m.index, end: rangeRe.lastIndex, from: m[1], fromUnit: m[2] || m[4] || '', to: m[3], toUnit: m[4] || m[2] || '' });
    }
    if (matches.length) {
      return matches.map(function(item, idx) {
        var next = matches[idx + 1];
        var start = Math.max(0, Math.min(total - 1, _directorTimeToFrames(item.from, item.fromUnit, fps)));
        var end = Math.max(start + 1, Math.min(total, _directorTimeToFrames(item.to, item.toUnit, fps)));
        var body = _directorCleanSegmentPrompt(prompt.slice(item.end, next ? next.index : prompt.length));
        return { start: start, length: Math.max(1, end - start), prompt: body, label: '镜头 ' + (idx + 1), strength: 0.9 };
      }).filter(function(seg) { return seg.length > 0; });
    }

    var headingRe = /(?:^|\n)\s*(?:[-*#>•]\s*)?(?:第?\s*\d+\s*(?:镜头|镜|分镜|场景|场|段|shot|scene)\s*[：:、.\-\s]*)/ig;
    while ((m = headingRe.exec(prompt)) !== null) matches.push({ index: m.index, end: headingRe.lastIndex });
    if (matches.length > 1) {
      var len = Math.max(1, Math.round(total / matches.length));
      return matches.map(function(item, idx) {
        var next = matches[idx + 1];
        return {
          start: Math.min(total - 1, idx * len),
          length: idx === matches.length - 1 ? Math.max(1, total - idx * len) : len,
          prompt: _directorCleanSegmentPrompt(prompt.slice(item.end, next ? next.index : prompt.length)),
          label: '镜头 ' + (idx + 1),
          strength: 0.9
        };
      });
    }

    var lines = prompt.split(/\n+/).map(_directorCleanSegmentPrompt).filter(Boolean);
    if (lines.length > 1 && lines.length <= 12) {
      var lineLen = Math.max(1, Math.round(total / lines.length));
      return lines.map(function(line, idx) {
        return {
          start: Math.min(total - 1, idx * lineLen),
          length: idx === lines.length - 1 ? Math.max(1, total - idx * lineLen) : lineLen,
          prompt: line,
          label: '镜头 ' + (idx + 1),
          strength: 0.9
        };
      });
    }
    return [];
  }

function _directorNormalizeSegments() {
    var total = _directorTotalFrames();
    _directorState.segments = (_directorState.segments || []).map(function(seg, idx) {
      var start = Math.max(0, parseInt(seg.start || 0, 10) || 0);
      var length = Math.max(1, parseInt(seg.length || Math.round(total / Math.max(1, _directorState.segments.length || 1)), 10) || 1);
      if (start >= total) start = Math.max(0, total - 1);
      if (start + length > total) length = Math.max(1, total - start);
      return {
        id: seg.id || _directorSegmentId(),
        imageFile: String(seg.imageFile || ''),
        previewSrc: String(seg.previewSrc || ''),
        prompt: String(seg.prompt || ''),
        start: start,
        length: length,
        strength: Math.max(0, Math.min(1, parseFloat(seg.strength == null ? 0.9 : seg.strength) || 0.9)),
        label: String(seg.label || ('镜头 ' + (idx + 1)))
      };
    }).sort(function(a, b) { return a.start - b.start; });
  }

function _directorSegmentEnd(seg) {
    return (parseInt(seg.start || 0, 10) || 0) + (parseInt(seg.length || 1, 10) || 1);
  }

function _syncDirectorInputs() {
    if (!_hasDirectorWorkflow()) return;
    _directorNormalizeSegments();
    var sourceSegments = _directorState.segments || [];
    var segments = sourceSegments.map(function(seg, idx) {
      var prompt = String(seg.prompt || '').trim();
      if (!prompt) prompt = _directorDefaultSegmentPrompt(seg, idx, sourceSegments);
      return { id: seg.id, type: 'image', start: seg.start, length: seg.length, prompt: prompt, imageFile: seg.imageFile, strength: seg.strength };
    });
    var values = {
      timeline_data: JSON.stringify({ segments: segments, audioSegments: [] }),
      local_prompts: segments.map(function(seg) { return seg.prompt || ''; }).join('|'),
      segment_lengths: segments.map(function(seg) { return seg.length; }).join(','),
      guide_strength: segments.map(function(seg) { return seg.strength; }).join(','),
      use_custom_audio: 'false'
    };
    Object.keys(values).forEach(function(name) {
      var key = _directorFieldKey(name);
      var el = key ? document.querySelector('[data-key="' + key + '"]') : null;
      if (el) el.value = values[name];
    });
  }

function _directorEmptyPromptSegmentIndexes() {
    if (!_hasDirectorWorkflow()) return [];
    _directorNormalizeSegments();
    return [];
  }

function _directorSegmentById(id) {
    id = String(id || '');
    return (_directorState.segments || []).find(function(seg) { return String(seg.id || '') === id; }) || null;
  }

function _renderDirectorTrackOnly() {
    var root = $('#directorPanel');
    if (!root) return;
    var total = _directorTotalFrames();
    var track = root.querySelector('[data-director-track]');
    if (track) {
      track.innerHTML = (_directorState.segments || []).map(function(seg, idx) {
        var left = Math.max(0, Math.min(100, (parseInt(seg.start || 0, 10) || 0) / total * 100));
        var length = Math.max(1, parseInt(seg.length || 1, 10) || 1);
        var width = Math.max(2, Math.min(100 - left, length / total * 100));
        var end = Math.min(total, _directorSegmentEnd(seg));
        return '<div class="director-timeline-seg" data-shot-id="' + escA(seg.id) + '" data-director-drag="move" style="left:' + left + '%;width:' + width + '%" title="' + escA((seg.label || ('镜头 ' + (idx + 1))) + ' · ' + seg.start + '-' + end + ' 帧') + '">' +
          '<span class="director-timeline-handle is-start" data-director-drag="start" aria-hidden="true"></span>' +
          '<span class="director-timeline-label">' + (idx + 1) + '<small>' + seg.start + '-' + end + '</small></span>' +
          '<span class="director-timeline-handle is-end" data-director-drag="end" aria-hidden="true"></span>' +
        '</div>';
      }).join('');
    }
    var hint = root.querySelector('[data-director-summary]');
    if (hint) hint.textContent = (_directorState.segments.length || 0) + ' 个镜头 / ' + total + ' 帧';
  }

function _syncDirectorShotControls(seg) {
    if (!seg || !seg.id) return;
    var shot = document.querySelector('.director-shot[data-shot-id="' + String(seg.id).replace(/"/g, '\\"') + '"]');
    if (!shot) return;
    var startEl = shot.querySelector('[data-director-field="start"]');
    var endEl = shot.querySelector('[data-director-field="end"]');
    var lengthEl = shot.querySelector('[data-director-field="length"]');
    if (startEl) startEl.value = String(parseInt(seg.start || 0, 10) || 0);
    if (endEl) endEl.value = String(_directorSegmentEnd(seg));
    if (lengthEl) lengthEl.value = String(parseInt(seg.length || 1, 10) || 1);
  }

function _directorFrameFromPointer(track, ev) {
    var rect = track.getBoundingClientRect();
    var x = Math.max(rect.left, Math.min(rect.right, ev.clientX || 0));
    var ratio = rect.width ? ((x - rect.left) / rect.width) : 0;
    return Math.max(0, Math.min(_directorTotalFrames(), Math.round(ratio * _directorTotalFrames())));
  }

function _applyDirectorDragState(state, ev) {
    if (!state || !state.track || !state.seg) return;
    var total = _directorTotalFrames();
    var frame = _directorFrameFromPointer(state.track, ev);
    if (state.mode === 'start') {
      var end = _directorSegmentEnd(state.seg);
      state.seg.start = Math.max(0, Math.min(end - 1, frame));
      state.seg.length = Math.max(1, end - state.seg.start);
    } else if (state.mode === 'end') {
      var nextEnd = Math.max(state.seg.start + 1, Math.min(total, frame));
      state.seg.length = Math.max(1, nextEnd - state.seg.start);
    } else {
      var length = Math.max(1, parseInt(state.seg.length || 1, 10) || 1);
      state.seg.start = Math.max(0, Math.min(total - length, frame - state.grabOffset));
    }
    _renderDirectorTrackOnly();
    _syncDirectorShotControls(state.seg);
    _syncDirectorInputs();
  }

function _initDirectorTrackDrag(panel) {
    var track = panel && panel.querySelector ? panel.querySelector('[data-director-track]') : null;
    if (!track || track.dataset.bound) return;
    track.dataset.bound = '1';
    var dragState = null;
    track.addEventListener('pointerdown', function(ev) {
      var target = ev.target.closest && ev.target.closest('[data-director-drag]');
      var segEl = ev.target.closest && ev.target.closest('.director-timeline-seg');
      if (!target || !segEl) return;
      var seg = _directorSegmentById(segEl.dataset.shotId);
      if (!seg) return;
      ev.preventDefault();
      var mode = target.dataset.directorDrag || 'move';
      dragState = {
        track: track,
        seg: seg,
        mode: mode,
        grabOffset: Math.max(0, _directorFrameFromPointer(track, ev) - (parseInt(seg.start || 0, 10) || 0))
      };
      document.body.classList.add('director-dragging');
      _applyDirectorDragState(dragState, ev);
    });
    document.addEventListener('pointermove', function(ev) {
      if (!dragState) return;
      ev.preventDefault();
      _applyDirectorDragState(dragState, ev);
    });
    document.addEventListener('pointerup', function() {
      if (!dragState) return;
      dragState = null;
      document.body.classList.remove('director-dragging');
      _renderDirectorTimeline();
    });
    document.addEventListener('pointercancel', function() {
      if (!dragState) return;
      dragState = null;
      document.body.classList.remove('director-dragging');
      _renderDirectorTimeline();
    });
  }

function _renderDirectorTimeline() {
    var root = $('#directorPanel');
    if (!root) return;
    _directorNormalizeSegments();
    var total = _directorTotalFrames();
    var list = root.querySelector('[data-director-list]');
    var track = root.querySelector('[data-director-track]');
    if (list) {
      list.innerHTML = (_directorState.segments || []).map(function(seg, idx) {
        var src = seg.previewSrc || _directorImageSrc(seg.imageFile);
        return '<div class="director-shot" data-shot-id="' + escA(seg.id) + '">' +
          '<div class="director-shot-thumb' + (src ? '' : ' is-text-only') + '">' + (src ? '<img src="' + escA(src) + '" alt="">' : '<span>提示词</span>') + '</div>' +
          '<div class="director-shot-body">' +
            '<div class="director-shot-head"><strong>' + escH(seg.label || ('镜头 ' + (idx + 1))) + '</strong><div class="director-shot-actions"><button type="button" class="director-shot-image-btn" title="为该镜头上传参考图" onclick="CW.selectDirectorShotImage(\'' + escA(seg.id) + '\')">' + (window.CW && CW.icon ? CW.icon('image', 14) : '图') + '</button><button type="button" title="删除" onclick="CW.removeDirectorShot(\'' + escA(seg.id) + '\')">' + (window.CW && CW.icon ? CW.icon('trash-2', 14) : '×') + '</button></div></div>' +
            '<div class="director-shot-grid">' +
              '<label>开始帧<input type="number" min="0" max="' + total + '" value="' + escA(String(seg.start)) + '" data-director-field="start"></label>' +
              '<label>结束帧<input type="number" min="1" max="' + total + '" value="' + escA(String(_directorSegmentEnd(seg))) + '" data-director-field="end"></label>' +
              '<label>强度<input type="number" min="0" max="1" step="0.05" value="' + escA(String(seg.strength)) + '" data-director-field="strength"></label>' +
            '</div>' +
            '<textarea data-director-field="prompt" placeholder="该镜头动作、机位、转场...">' + escH(seg.prompt || '') + '</textarea>' +
          '</div>' +
        '</div>';
      }).join('');
    }
    _initDirectorTrackDrag(root);
    _renderDirectorTrackOnly();
    _syncDirectorInputs();
  }

function _directorAddSegment(imageFile, prompt, previewSrc) {
    imageFile = String(imageFile || '').trim();
    prompt = String(prompt || '');
    if (!imageFile && !prompt.trim()) return;
    var total = _directorTotalFrames();
    var count = (_directorState.segments || []).length + 1;
    var len = Math.max(1, Math.round(total / Math.max(1, count)));
    (_directorState.segments || []).forEach(function(seg, idx) {
      seg.start = idx * len;
      seg.length = len;
    });
    var start = Math.min(total - 1, (count - 1) * len);
    _directorState.segments.push({ id: _directorSegmentId(), imageFile: imageFile, previewSrc: previewSrc || '', start: start, length: Math.max(1, total - start), strength: 0.9, prompt: prompt, label: '镜头 ' + count });
    _renderDirectorTimeline();
  }

function _directorSetSegmentImage(id, filename, previewSrc) {
    var seg = _directorSegmentById(id);
    if (!seg || !filename) return false;
    seg.imageFile = String(filename || '');
    seg.previewSrc = previewSrc || '';
    _renderDirectorTimeline();
    return true;
  }

function selectDirectorShotImage(id) {
    if (!_directorSegmentById(id)) return;
    _directorPendingShotImageId = String(id || '');
    var input = $('#directorShotImageInput');
    if (input) input.click();
  }

function _handleDirectorShotFile(file, shotId) {
    shotId = String(shotId || '');
    if (!file || !shotId) return _directorUploadPromise;
    var run = _directorUploadPromise.then(async function() {
      var shot = document.querySelector('.director-shot[data-shot-id="' + shotId.replace(/"/g, '\\"') + '"]');
      if (shot) shot.setAttribute('data-uploading', '1');
      try {
        var data = await _uploadRefImage(file);
        if (data && data.filename) _directorSetSegmentImage(shotId, data.filename, '');
      } finally {
        if (shot) shot.removeAttribute('data-uploading');
      }
    });
    _directorUploadPromise = run.catch(function() {});
    return run;
  }

function importDirectorPromptSegments() {
    var prompt = (($('#promptInput') || {}).value || '').trim();
    var segments = _directorParsePromptSegments(prompt);
    if (!segments.length) {
      if (window.CW && CW.toast) CW.toast('没有识别到可导入的时间轴分段', 'warn');
      else alert('没有识别到可导入的时间轴分段');
      return;
    }
    var existing = (_directorState.segments || []).slice();
    _directorState.segments = segments.map(function(seg, idx) {
      var old = existing[idx] || {};
      return {
        id: old.id || _directorSegmentId(),
        imageFile: old.imageFile || '',
        previewSrc: old.previewSrc || '',
        start: seg.start,
        length: seg.length,
        strength: old.strength != null ? old.strength : seg.strength,
        prompt: seg.prompt,
        label: old.label || seg.label || ('镜头 ' + (idx + 1))
      };
    });
    if (existing.length > segments.length) {
      existing.slice(segments.length).forEach(function(seg) {
        _directorState.segments.push(seg);
      });
    }
    _renderDirectorTimeline();
    toggleDirectorPanel(true);
    var preserved = existing.filter(function(seg, idx) { return idx < segments.length && seg && seg.imageFile; }).length;
    var extra = Math.max(0, existing.length - segments.length);
    var msg = existing.length
      ? ('已填入 ' + segments.length + ' 个提示词分镜' + (preserved ? '，保留 ' + preserved + ' 张参考图' : '') + (extra ? '，未清空多出的 ' + extra + ' 个镜头' : ''))
      : ('已导入 ' + segments.length + ' 个提示词分镜');
    if (window.CW && CW.toast) CW.toast(msg, 'ok');
  }

function _directorPanelHtml() {
    function hidden(name) {
      var key = _directorFieldKey(name);
      return key ? '<input type="hidden" data-key="' + escA(key) + '" value="">' : '';
    }
    return '<div class="director-panel hidden" id="directorPanel">' +
      '<div class="director-head"><div><strong>导演模式</strong><span data-director-summary>0 个镜头</span></div><button type="button" onclick="CW.toggleDirectorPanel(false)" title="关闭">' + (window.CW && CW.icon ? CW.icon('x', 16) : '×') + '</button></div>' +
      '<div class="director-tools"><button type="button" onclick="CW.importDirectorPromptSegments()" title="自动导入提示词">' + (window.CW && CW.icon ? CW.icon('file-text', 16) : '') + ' 自动导入提示词</button><span>识别 0-2秒 / 1-24帧 / 镜头标题</span></div>' +
      '<div class="director-drop" id="directorDropZone"><input type="file" id="directorImageInput" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" multiple class="hidden"><input type="file" id="directorShotImageInput" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden"><button type="button" onclick="document.getElementById(&quot;directorImageInput&quot;).click()">' + (window.CW && CW.icon ? CW.icon('image', 16) : '') + ' 添加参考图</button><span>可拖入历史图片</span></div>' +
      '<div class="director-track" data-director-track></div><div class="director-shot-list" data-director-list></div>' +
      hidden('timeline_data') + hidden('local_prompts') + hidden('segment_lengths') + hidden('guide_strength') + hidden('use_custom_audio') +
    '</div>';
  }

function _removeBodyDirectorPanel() {
    var panel = document.body && document.body.querySelector('#directorPanel');
    if (panel && panel.parentElement === document.body) panel.remove();
  }

function _mountDirectorPanelToBody() {
    var panel = $('#directorPanel');
    if (!panel || !document.body) return panel;
    if (panel.parentElement !== document.body) document.body.appendChild(panel);
    return panel;
  }

function _handleDirectorFiles(files) {
    files = Array.prototype.slice.call(files || []).filter(function(file) { return file && /^image\//.test(file.type || ''); });
    if (!files.length) return _directorUploadPromise;
    var run = _directorUploadPromise.then(async function() {
      var drop = $('#directorDropZone');
      if (drop) drop.setAttribute('data-uploading', '1');
      try {
        for (var i = 0; i < files.length; i++) {
          var data = await _uploadRefImage(files[i]);
          if (data && data.filename) _directorAddSegment(data.filename, '');
        }
      } finally {
        if (drop) drop.removeAttribute('data-uploading');
      }
    });
    _directorUploadPromise = run.catch(function() {});
    return run;
  }

async function _waitForDirectorUploads() {
    if (!_hasDirectorWorkflow()) return;
    if (!_directorUploadPromise) return;
    await _directorUploadPromise;
  }

function _initDirectorHistoryDragBridge() {
    if (document.body.dataset.directorDragBridge) return;
    document.body.dataset.directorDragBridge = '1';
    document.addEventListener('mouseover', function(ev) {
      var card = ev.target.closest && ev.target.closest('.gi:not(.job-card)');
      if (card) card.setAttribute('draggable', 'true');
    });
    document.addEventListener('dragstart', function(ev) {
      var card = ev.target.closest && ev.target.closest('.gi:not(.job-card)');
      if (!card || !ev.dataTransfer) return;
      var idx = parseInt(card.dataset.histIdx || '-1', 10);
      var item = idx >= 0 ? (A.historyItems || [])[idx] : null;
      if (!item || /video/i.test(String(item.media_type || ''))) return;
      var name = item.filename || item.thumb || '';
      if (!name) return;
      ev.dataTransfer.setData('application/x-ez-history-image', JSON.stringify({ filename: name, thumb: item.thumb || '', prompt: item.prompt || item.prompt_preview || '', preview: item.thumb ? (API + '/api/thumbs/' + encodeURIComponent(item.thumb)) : '' }));
      ev.dataTransfer.effectAllowed = 'copy';
    });
  }

function _initDirectorPanel() {
    var panel = _mountDirectorPanelToBody();
    if (!panel) return;
    var current = String(A.currentWF || '');
    if (_directorState.workflow !== current) _directorState = { workflow: current, segments: [] };
    var input = $('#directorImageInput');
    if (input && !input.dataset.bound) {
      input.dataset.bound = '1';
      input.addEventListener('change', function() {
        _handleDirectorFiles(input.files)
          .catch(function(e) { alert('导演参考图上传失败: ' + (e.message || e)); })
          .finally(function() { input.value = ''; });
      });
    }
    var shotInput = $('#directorShotImageInput');
    if (shotInput && !shotInput.dataset.bound) {
      shotInput.dataset.bound = '1';
      shotInput.addEventListener('change', function() {
        var file = shotInput.files && shotInput.files[0];
        var shotId = _directorPendingShotImageId;
        _directorPendingShotImageId = '';
        _handleDirectorShotFile(file, shotId)
          .catch(function(e) { alert('镜头参考图上传失败: ' + (e.message || e)); })
          .finally(function() { shotInput.value = ''; });
      });
    }
    var drop = $('#directorDropZone');
    if (drop && !drop.dataset.bound) {
      drop.dataset.bound = '1';
      ['dragenter', 'dragover'].forEach(function(name) {
        drop.addEventListener(name, function(ev) { ev.preventDefault(); drop.classList.add('is-over'); });
      });
      drop.addEventListener('dragleave', function() { drop.classList.remove('is-over'); });
      drop.addEventListener('drop', function(ev) {
        ev.preventDefault();
        drop.classList.remove('is-over');
        var payload = '';
        try { payload = ev.dataTransfer.getData('application/x-ez-history-image'); } catch (e) {}
        if (payload) {
          try {
            var item = JSON.parse(payload);
            _directorAddSegment(item.filename || item.thumb || '', item.prompt || '', item.preview || '');
            return;
          } catch (e) {}
        }
        _handleDirectorFiles(ev.dataTransfer.files || []).catch(function(e) {
          alert('导演参考图上传失败: ' + (e.message || e));
        });
      });
    }
    var list = panel.querySelector('[data-director-list]');
    if (list && !list.dataset.bound) {
      list.dataset.bound = '1';
      list.addEventListener('input', function(ev) {
        var shot = ev.target.closest('.director-shot');
        if (!shot) return;
        var seg = (_directorState.segments || []).find(function(item) { return item.id === shot.dataset.shotId; });
        if (!seg) return;
        var field = ev.target.dataset.directorField;
        if (field === 'prompt') {
          seg.prompt = ev.target.value;
          _renderDirectorTrackOnly();
          _syncDirectorInputs();
          return;
        }
        if (field === 'strength') {
          seg.strength = parseFloat(ev.target.value) || 0;
          _syncDirectorInputs();
          return;
        }
        if (field === 'end') {
          var total = _directorTotalFrames();
          var end = Math.max((parseInt(seg.start || 0, 10) || 0) + 1, Math.min(total, parseInt(ev.target.value, 10) || 1));
          seg.length = Math.max(1, end - (parseInt(seg.start || 0, 10) || 0));
          _renderDirectorTrackOnly();
          _syncDirectorShotControls(seg);
          _syncDirectorInputs();
          return;
        }
        if (field) {
          seg[field] = parseInt(ev.target.value, 10) || 0;
          if (field === 'start') {
            var maxStart = Math.max(0, _directorTotalFrames() - (parseInt(seg.length || 1, 10) || 1));
            seg.start = Math.max(0, Math.min(maxStart, seg.start));
          }
          _renderDirectorTrackOnly();
          _syncDirectorShotControls(seg);
          _syncDirectorInputs();
        }
      });
    }
    _initDirectorHistoryDragBridge();
    _renderDirectorTimeline();
  }

function toggleDirectorPanel(force) {
    var panel = _mountDirectorPanelToBody();
    if (!panel) return;
    var show = force == null ? panel.classList.contains('hidden') : !!force;
    panel.classList.toggle('hidden', !show);
    if (show) _initDirectorPanel();
  }

function removeDirectorShot(id) {
    _directorState.segments = (_directorState.segments || []).filter(function(seg) { return seg.id !== id; });
    _renderDirectorTimeline();
  }

function renderQuickForm(fields) {
    var container = $('#quickFormFields');
    if (!container) return;
    _removeBodyDirectorPanel();
    if (!fields || !fields.length) { container.innerHTML = ''; return; }
    // Preserve prompt text across workflow switches
    var _savedPrompt = ($('#promptInput') || {}).value || '';
    var hasZones = fields.some(function(f) { return f.zone; });
    var hasDirector = _hasDirectorWorkflow(fields);
    var html = '', hasTextEncode = false, hasLoadImage = false, hasLoadVideo = false, quickImageRendered = false, quickVideoRendered = false, sizeRendered = false;
    var defaultPromptValue = '';
    var qwenAngleGroups = _qwenAngleGroups(fields);
    var qwenAngleByNode = {};
    var qwenAngleRendered = {};
    qwenAngleGroups.forEach(function(group) { qwenAngleByNode[String(group.node_id)] = group; });
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
      if (_isQwenAngleField(f)) {
        var angleGroup = qwenAngleByNode[String(f.node_id || '')];
        if (angleGroup && !qwenAngleRendered[angleGroup.node_id]) {
          html += _qwenAngleControlHtml(angleGroup);
          qwenAngleRendered[angleGroup.node_id] = true;
        }
        continue;
      }
      if (_isPromptLikeField(f)) {
        hasTextEncode = true;
        if (!defaultPromptValue && f.value !== undefined && f.value !== null) defaultPromptValue = String(f.value || '');
        var labelText = f.label || 'Prompt', nodeInfo = f.node_title ? ' [' + f.node_title.split('(')[0].trim() + ']' : '';
        var optimizeCopy = _promptOptimizeCopy(fields);
        var directorBtn = hasDirector ? '<button id="directorModeBtn" class="prompt-tool-btn prompt-tool-btn-vibrant" type="button" title="导演模式" onclick="CW.toggleDirectorPanel()">' + (window.CW && CW.icon ? CW.icon('clapperboard') : '') + ' <span class="prompt-tool-label">导演模式</span></button>' : '';
        html += '<div class="fg prompt-fg"><div class="prompt-label-row"><label>' + escH(labelText + nodeInfo) + '</label></div><div class="prompt-input-wrap"><textarea id="promptInput" placeholder="' + escA(labelText) + '...">' + escH(defaultPromptValue) + '</textarea></div><div class="prompt-actions">' + directorBtn + '<button id="interrogatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-image" type="button" title="图片反推" onclick="CW.interrogatePromptFromImage()">' + (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">图片反推</span></button><button id="optimizePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant is-compact-disabled" type="button" title="' + escA(optimizeCopy.label) + '" data-optimize-mode="' + escA(optimizeCopy.mode) + '" onclick="CW.optimizePrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('zap') : '') + ' <span class="prompt-tool-label">' + escH(optimizeCopy.label) + '</span></button><button id="translatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-translate is-compact-disabled" type="button" title="中文/英文提示词切换" onclick="CW.translatePromptLanguage()" disabled>' + (window.CW && CW.icon ? CW.icon('globe') : '') + ' <span class="prompt-tool-label">中英切换</span></button><button id="clearPromptBtn" class="prompt-tool-btn prompt-tool-btn-clear clear-btn is-compact-disabled" type="button" title="清除文字" onclick="CW.clearPrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' <span class="prompt-tool-label">清除文字</span></button></div></div>';
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
    if (hasDirector) html += _directorPanelHtml();
    container.innerHTML = html;
    if (hasLatentW || hasLatentH) {
      window.CW.initRatioGrid && window.CW.initRatioGrid();
      var wi = $('#widthInput');
      var hi = $('#heightInput');
      window.CW.highlightRatio && CW.highlightRatio(parseInt((wi && wi.value) || 0, 10), parseInt((hi && hi.value) || 0, 10));
    }
    // Restore user-entered prompt text after DOM rebuild; SkinTest workflows
    // intentionally show their LoRA trigger defaults for side-by-side tests.
    var preferWorkflowDefaultPrompt = !!(defaultPromptValue && /SkinTest/i.test(String(A.currentWF || '')));
    if (_savedPrompt && !preferWorkflowDefaultPrompt) {
      var pi2 = $('#promptInput');
      if (pi2) pi2.value = _savedPrompt;
    }
    var promptInput = $('#promptInput');
    if (promptInput && window.CW.syncClearPromptButton) {
      promptInput.addEventListener('input', window.CW.syncClearPromptButton);
      window.CW.syncClearPromptButton();
    }
    _initVideoModeControl();
    _initQwenAngleControls();
    if (hasDirector) _initDirectorPanel();
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
    _syncQwenAngleReferencePreview();
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
      _syncQwenAngleReferencePreview();
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
        _syncQwenAngleReferencePreview();
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
  window.CW.preparePromptForQwenAngle = _preparePromptForCurrentQwenAngle;
  window.CW.clearPromptOptimizationVariants = _clearPromptOptimizationVariants;
  window.CW.interrogatePromptFromImage = interrogatePromptFromImage;
  window.CW.openPromptInterrogateModal = openPromptInterrogateModal;
  window.CW.closePromptInterrogateModal = closePromptInterrogateModal;
  window.CW.renderAdvFields = renderAdvFields;
  window.CW.renderQuickGen = renderQuickGen;
  window.CW.renderQuickForm = renderQuickForm;
  window.CW.toggleDirectorPanel = toggleDirectorPanel;
  window.CW.removeDirectorShot = removeDirectorShot;
  window.CW.importDirectorPromptSegments = importDirectorPromptSegments;
  window.CW.selectDirectorShotImage = selectDirectorShotImage;
  window.CW.setVideoMode = setVideoMode;
  window.CW.toggleSeedRandom = toggleSeedRandom;
  window.CW.setSeedRandomEnabled = _setSeedRandomEnabled;
  window.CW.initRatioGrid = initRatioGrid;
  window.CW.highlightRatio = highlightRatio;
})();
