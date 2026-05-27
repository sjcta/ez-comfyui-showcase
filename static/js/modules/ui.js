/**
 * UI Module
 */
(function () {
  'use strict';
  var A = window.__APP__ || {};
  var $ = A.$, $$ = A.$$, escH = A.escH, escA = A.escA;
var API = A.API, jobs = A.jobs;

function _ensureToastContainer() {
  var container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  return container;
}

function initResizeHandle() {
    const handle = $('#resizeHandle');
    const colLeft = $('#colLeft');
    if (!handle || !colLeft) return;
    let startX, startW;
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      startX = e.clientX;
      startW = colLeft.offsetWidth;
      handle.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      const onMove = (e2) => {
        const dx = e2.clientX - startX;
        const nw = Math.max(280, Math.min(startW + dx, window.innerWidth * 0.5));
        colLeft.style.width = nw + 'px';
        colLeft.style.flex = 'none';
      };
      const onUp = () => {
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    // Clear inline width on mobile so CSS media query takes effect
    window.addEventListener('resize', () => {
      if (window.innerWidth <= 900) {
        colLeft.style.width = '';
        colLeft.style.flex = '';
      }
    });
  }

function clearPrompt() {
  var inp = $('#promptInput');
  if (inp) { inp.value = ''; inp.dispatchEvent(new Event('input')); inp.focus(); }
  if (window.CW && typeof CW.clearPromptOptimizationVariants === 'function') CW.clearPromptOptimizationVariants();
}

function syncClearPromptButton() {
  var inp = $('#promptInput');
  var clearBtn = $('#clearPromptBtn');
  var optimizeBtn = $('#optimizePromptBtn');
  var translateBtn = $('#translatePromptBtn');
  if (!clearBtn && !optimizeBtn && !translateBtn) return;
  var hasText = !!(inp && inp.value.trim());
  if (translateBtn) {
    translateBtn.classList.remove('hidden');
    translateBtn.classList.toggle('is-compact-disabled', !hasText);
    translateBtn.disabled = !hasText;
  }
  if (clearBtn) {
    clearBtn.classList.remove('hidden');
    clearBtn.classList.toggle('is-compact-disabled', !hasText);
    clearBtn.disabled = !hasText;
  }
  if (optimizeBtn) {
    optimizeBtn.classList.remove('hidden');
    optimizeBtn.classList.toggle('is-compact-disabled', !hasText);
    optimizeBtn.disabled = !hasText;
  }
  var anchor = clearBtn || optimizeBtn;
  var actions = anchor && anchor.closest ? anchor.closest('.prompt-actions') : null;
  if (actions) actions.classList.toggle('has-content', hasText);
}

function _isGenerationStartToast(message, type) {
  return /开始出图/.test(String(message || '')) &&
    (type === 'generating' || type === 'queued' || type === 'info' || !type);
}

function _isGenerationStatusToastAllowed(message, type) {
  var text = String(message || '');
  if (type === 'done' || type === 'error') return true;
  if (type === 'queued') return /排队中/.test(text);
  if (type === 'generating') return /出图中/.test(text);
  return false;
}

function _isGenerationStatusToast(message, type) {
  var text = String(message || '');
  if (type === 'queued' || type === 'generating') return true;
  if (_isGenerationStartToast(text, type)) return true;
  if ((type === 'done' && /结束出图/.test(text)) || (type === 'error' && /失败/.test(text))) return true;
  return /(排队中|出图中|保存结果|提交|准备|queued|preparing|starting_comfyui|submitting|generating|downloading)/i.test(text);
}

function _hasChinese(text) {
  return /[\u3400-\u9fff]/.test(String(text || ''));
}

function _cleanPromptResultChinese(text) {
  var cleaned = String(text || '').trim();
  if (!cleaned || !_hasChinese(cleaned)) return cleaned;
  cleaned = cleaned.replace(/\s*(?:英文|英语|English|Original(?:\s+prompt)?|Prompt|Source|原文|原始提示词)\s*[:：][\s\S]*$/i, '').trim();
  var lines = cleaned.split(/\r?\n/);
  var kept = [];
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) continue;
    if (!_hasChinese(line) && /[A-Za-z][A-Za-z'’.-]*(?:\s+[A-Za-z][A-Za-z'’.-]*){5,}/.test(line)) continue;
    if (_hasChinese(line)) {
      line = line.replace(/(^|[\s。！？；;，,、])[A-Za-z][A-Za-z'’.-]*(?:\s+[A-Za-z][A-Za-z'’.-]*){5,}[\s\S]*$/, '$1').replace(/[ ，,；;。]+$/, '。').trim();
      line = _dropEnglishPromptFragments(line);
    }
    if (line) kept.push(line);
  }
  return kept.join('\n').trim();
}

function _dropEnglishPromptFragments(line) {
  var text = String(line || '').trim();
  if (!text || !_hasChinese(text)) return text;
  text = text.replace(/([。！？!?])\s*[A-Za-z0-9][A-Za-z0-9'’._+/-]*(?:[\s,，、；;]+[A-Za-z0-9][A-Za-z0-9'’._+/-]*)+\s*$/g, '$1').trim();
  var pieces = text.split(/[，,、；;]/);
  var kept = [];
  for (var i = 0; i < pieces.length; i++) {
    var piece = pieces[i].trim().replace(/^[，,、；;\s]+|[，,、；;\s]+$/g, '');
    if (!piece) continue;
    if (!_hasChinese(piece)) {
      if (/[A-Za-z][A-Za-z0-9'’._+/-]*/.test(piece)) continue;
      kept.push(piece);
      continue;
    }
    piece = piece.replace(/\s+[A-Za-z0-9][A-Za-z0-9'’._+/-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'’._+/-]*){0,4}\s*$/g, '').trim();
    if (piece) kept.push(piece);
  }
  return kept.join('，').trim();
}

function _removePromptInterrogateToast() {
  var container = _ensureToastContainer();
  var existing = container.querySelectorAll('.toast');
  for (var i = 0; i < existing.length; i++) {
    if (existing[i].getAttribute && existing[i].getAttribute('data-toast-scope') === 'prompt-interrogate') {
      existing[i].parentNode.removeChild(existing[i]);
      if (container.classList) container.classList.remove('has-prompt-result-expanded');
    }
  }
  if (container.classList) container.classList.remove('has-prompt-result-active');
  return container;
}

function clearPromptInterrogateToast() {
  _removePromptInterrogateToast();
}

function showPromptInterrogatePendingToast() {
  var container = _removePromptInterrogateToast();
  if (container.classList) container.classList.add('has-prompt-result-active');
  var t = document.createElement('div');
  t.className = 'toast toast-info toast-prompt-result prompt-result-toast prompt-result-pending is-persistent';
  if (t.setAttribute) t.setAttribute('data-toast-scope', 'prompt-interrogate');
  t.innerHTML = ''
    + '<span class="toast-icon">' + (window.CW && CW.icon ? CW.icon('loader', 16) : '') + '</span>'
    + '<span class="toast-content">'
    +   '<span class="toast-title">图片反推中</span>'
    + '</span>'
    + '<button class="toast-close" type="button" title="关闭">×</button>';
  var closeBtn = t.querySelector('.toast-close');
  if (closeBtn) closeBtn.addEventListener('click', function () {
    clearPromptInterrogateToast();
  });
  container.appendChild(t);
}

function showPromptResultToast(prompt, meta) {
  var text = String(prompt || '').trim();
  if (!text) return;
  var container = _removePromptInterrogateToast();
  if (container.classList) container.classList.add('has-prompt-result-active');
  var t = document.createElement('div');
  t.className = 'toast toast-done toast-prompt-result prompt-result-toast is-persistent is-collapsed';
  if (t.setAttribute) t.setAttribute('data-toast-scope', 'prompt-interrogate');
  var provider = meta && meta.provider ? String(meta.provider) : '';
  var promptEn = String((meta && (meta.prompt_en || meta.english_prompt)) || (_hasChinese(text) ? '' : text) || '').trim();
  var promptZh = _cleanPromptResultChinese(String((meta && (meta.prompt_zh || meta.zh_prompt || meta.chinese_prompt || meta.translated_prompt)) || (_hasChinese(text) ? text : '') || '').trim());
  var negativePrompt = String((meta && (meta.negative_prompt || meta.negativePrompt)) || '').trim();
  var expertData = meta && meta.expert_interrogate ? meta.expert_interrogate : null;
  var currentLang = promptZh ? 'zh' : 'en';
  function stringifyStructured(value) {
    if (!value) return '';
    if (typeof value === 'string') {
      var raw = value.trim();
      if (!raw) return '';
      try { return JSON.stringify(JSON.parse(raw), null, 2); } catch (err) { return raw; }
    }
    try { return JSON.stringify(value, null, 2); } catch (err) { return ''; }
  }
  function buildExpertFallbackStructuredJson() {
    if (!expertData) return '';
    var experts = Array.isArray(expertData.experts) ? expertData.experts : [];
    var description = {};
    var negativeItems = [];
    var merged = getPromptText();
    if (merged) description['合并提示词'] = merged;
    for (var ei = 0; ei < experts.length; ei++) {
      var expert = experts[ei] || {};
      var label = String(expert.label || expert.id || ('专家 ' + (ei + 1))).trim();
      var section = {};
      if (expert.fields && typeof expert.fields === 'object') section['字段'] = expert.fields;
      if (Array.isArray(expert.observations) && expert.observations.length) section['观察'] = expert.observations;
      else if (expert.summary) section['观察'] = [String(expert.summary)];
      if (Object.keys(section).length) description[label] = section;
      if (Array.isArray(expert.negative_constraints)) {
        for (var ni = 0; ni < expert.negative_constraints.length; ni++) {
          var neg = String(expert.negative_constraints[ni] || '').trim();
          if (neg) negativeItems.push(neg);
        }
      }
    }
    if (negativePrompt) negativeItems.push(negativePrompt);
    return stringifyStructured({
      '画面描述': description,
      '负面提示词': { '专家负面': Array.from(new Set(negativeItems)) }
    });
  }
  var structuredJson = '';
  var structuredSource = meta && (meta.structured_prompt_json || meta.prompt_json || meta.json_prompt || meta.structured_prompt);
  structuredJson = stringifyStructured(structuredSource);
  var structuredJsonEn = stringifyStructured(meta && (meta.structured_prompt_json_en || meta.english_prompt_json || meta.json_prompt_en || meta.structured_prompt_en));
  if (!structuredJson && expertData) structuredJson = buildExpertFallbackStructuredJson();
  var hasStructuredJson = !!structuredJson;
  var currentFormat = (expertData && hasStructuredJson) ? 'json' : 'text';
  function getPromptText() {
    return currentLang === 'zh' ? promptZh : (promptEn || text);
  }
  function getStructuredText() {
    if (currentLang === 'en' && structuredJsonEn) return structuredJsonEn;
    return structuredJson;
  }
  function canShowLanguage() {
    if (currentFormat === 'json') return !!(structuredJson && structuredJsonEn);
    return !!(promptZh && promptEn);
  }
  function renderExpertPanel(data, resultMeta) {
    if (!data) return '';
    var experts = Array.isArray(data.experts) ? data.experts : [];
    var merged = String((resultMeta && (resultMeta.structured_optimized_prompt || resultMeta.prompt || resultMeta.prompt_zh)) || '').trim();
    var html = '<span class="prompt-result-expert-title">专家组反推</span>';
    if (merged) {
      html += '<span class="prompt-result-expert-merged"><strong>合并结果</strong><span>' + escH(merged) + '</span></span>';
    }
    html += '<span class="prompt-result-expert-list">';
    for (var ei = 0; ei < experts.length; ei++) {
      var expert = experts[ei] || {};
      var label = String(expert.label || expert.id || ('专家 ' + (ei + 1))).trim();
      var summary = String(expert.summary || '').trim();
      var confidence = typeof expert.confidence === 'number' ? Math.round(expert.confidence * 100) + '%' : '';
      html += '<span class="prompt-result-expert-item"><strong>' + escH(label) + (confidence ? ' · ' + escH(confidence) : '') + '</strong><span>' + escH(summary || '已完成该维度观察') + '</span></span>';
    }
    html += '</span>';
    return html;
  }
  function parseStructuredText() {
    var raw = getStructuredText();
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (err) { return null; }
  }
  function isNegativePromptKey(key) {
    var normalized = String(key || '').toLowerCase();
    return normalized === '负面提示词'
      || normalized === 'negative_prompt'
      || normalized === 'negative'
      || normalized.indexOf('negative') >= 0
      || normalized.indexOf('负面') >= 0;
  }
  function cloneWithoutNegative(value) {
    if (Array.isArray(value)) {
      var list = [];
      for (var ai = 0; ai < value.length; ai++) {
        var cleanedItem = cloneWithoutNegative(value[ai]);
        if (cleanedItem !== '' && cleanedItem !== null && cleanedItem !== undefined) list.push(cleanedItem);
      }
      return list;
    }
    if (value && typeof value === 'object') {
      var out = {};
      Object.keys(value).forEach(function(key) {
        if (isNegativePromptKey(key)) return;
        var cleanedValue = cloneWithoutNegative(value[key]);
        if (cleanedValue === '' || cleanedValue === null || cleanedValue === undefined) return;
        if (Array.isArray(cleanedValue) && !cleanedValue.length) return;
        if (typeof cleanedValue === 'object' && !Array.isArray(cleanedValue) && !Object.keys(cleanedValue).length) return;
        out[key] = cleanedValue;
      });
      return out;
    }
    return value;
  }
  function collectTextValues(value, output) {
    if (Array.isArray(value)) {
      for (var vi = 0; vi < value.length; vi++) collectTextValues(value[vi], output);
      return;
    }
    if (value && typeof value === 'object') {
      Object.keys(value).forEach(function(key) { collectTextValues(value[key], output); });
      return;
    }
    var item = String(value || '').trim();
    if (item) output.push(item);
  }
  function collectNegativeSections(value, output) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) {
      for (var ni = 0; ni < value.length; ni++) collectNegativeSections(value[ni], output);
      return;
    }
    Object.keys(value).forEach(function(key) {
      if (isNegativePromptKey(key)) {
        collectTextValues(value[key], output);
      } else {
        collectNegativeSections(value[key], output);
      }
    });
  }
  function expertFullPromptText() {
    if (currentFormat === 'json' && getStructuredText()) return getStructuredText();
    var full = getPromptText();
    if (negativePrompt) full += '\n\n负面提示词：' + negativePrompt;
    return full;
  }
  function expertPositivePromptText() {
    if (currentFormat === 'json') {
      var parsed = parseStructuredText();
      if (parsed) return JSON.stringify(cloneWithoutNegative(parsed), null, 2);
    }
    return getPromptText();
  }
  function expertNegativePromptText() {
    var parsed = currentFormat === 'json' ? parseStructuredText() : null;
    if (parsed) {
      var items = [];
      collectNegativeSections(parsed, items);
      if (items.length) return Array.from(new Set(items)).join('，');
    }
    return negativePrompt;
  }
  function promptCopyControlsHtml() {
    if (expertData) {
      return ''
        + '<button class="prompt-result-action is-primary is-copy hidden" type="button" data-action="replicate-full">复刻完整提示词</button>'
        + '<button class="prompt-result-action is-primary is-copy hidden" type="button" data-action="replicate-positive">复刻正向提示词</button>'
        + '<button class="prompt-result-action is-primary is-copy hidden" type="button" data-action="replicate-negative">复刻负面提示词</button>';
    }
    return '<button class="prompt-result-action is-primary is-copy hidden" type="button" data-action="copy">复制到输入框</button>';
  }
  var currentText = currentFormat === 'json' ? getStructuredText() : getPromptText();
  function langLabel(lang) { return lang === 'zh' ? '中文' : 'English'; }
  t.innerHTML = ''
    + '<span class="toast-icon">' + (window.CW && CW.icon ? CW.icon('check-circle', 16) : '') + '</span>'
    + '<span class="toast-content">'
    +   '<span class="toast-title">反推完成</span>'
    +   '<span class="prompt-result-panel">'
    +     '<span class="prompt-result-meta">' + escH(provider || '图片反推提示词') + '</span>'
    +     '<span class="prompt-result-body" data-lang="' + escA(currentLang) + '" data-format="' + escA(currentFormat) + '">' + escH(currentText) + '</span>'
    +     '<span class="prompt-result-negative' + (negativePrompt ? '' : ' hidden') + '"><strong>负面提示词</strong><span>' + escH(negativePrompt) + '</span></span>'
    +     '<span class="prompt-result-expert-panel' + (expertData ? '' : ' hidden') + '">' + renderExpertPanel(expertData, meta || {}) + '</span>'
    +     '<span class="prompt-result-controls">'
    +       '<span class="prompt-result-control-left">'
    +         '<span class="prompt-result-format' + (hasStructuredJson ? '' : ' hidden') + '">'
    +           '<button class="prompt-result-format-btn' + (currentFormat === 'text' ? ' active' : '') + '" type="button" data-format="text">纯词汇</button>'
    +           '<button class="prompt-result-format-btn' + (currentFormat === 'json' ? ' active' : '') + '" type="button" data-format="json">JSON格式</button>'
    +         '</span>'
    +         '<span class="prompt-result-language' + (promptZh && promptEn ? '' : ' hidden') + '">'
    +         '<button class="prompt-result-lang-btn' + (currentLang === 'zh' ? ' active' : '') + '" type="button" data-lang="zh">中文</button>'
    +         '<button class="prompt-result-lang-btn' + (currentLang === 'en' ? ' active' : '') + '" type="button" data-lang="en">English</button>'
    +         '</span>'
    +       '</span>'
    +       '<span class="prompt-result-copy-row">'
    +         promptCopyControlsHtml()
    +       '</span>'
    +     '</span>'
    +   '</span>'
    + '</span>'
    + '<span class="prompt-result-actions">'
    +   '<button class="prompt-result-action" type="button" data-action="view">点击查看</button>'
    + '</span>'
    + '<button class="toast-close" type="button" title="关闭">×</button>';
  function setContainerExpanded(expanded) {
    if (container && container.classList) {
      container.classList.toggle('has-prompt-result-expanded', !!expanded);
    }
  }
  function closePromptResultToast() {
    setContainerExpanded(false);
    if (container && container.classList) container.classList.remove('has-prompt-result-active');
    if (t.parentNode) t.parentNode.removeChild(t);
  }
  function setLanguage(lang) {
    currentLang = (lang === 'zh' && promptZh) ? 'zh' : 'en';
    currentText = currentFormat === 'json' ? getStructuredText() : getPromptText();
    var body = t.querySelector('.prompt-result-body');
    if (body) {
      body.textContent = currentText;
      body.setAttribute('data-lang', currentFormat === 'json' ? currentLang : currentLang);
    }
    var langBtns = t.querySelectorAll('.prompt-result-lang-btn');
    for (var li = 0; li < langBtns.length; li++) {
      langBtns[li].classList.toggle('active', langBtns[li].getAttribute('data-lang') === currentLang);
    }
  }
  function setFormat(format) {
    currentFormat = (format === 'json' && hasStructuredJson) ? 'json' : 'text';
    currentText = currentFormat === 'json' ? getStructuredText() : getPromptText();
    var body = t.querySelector('.prompt-result-body');
    if (body) {
      body.textContent = currentText;
      body.setAttribute('data-format', currentFormat);
      body.setAttribute('data-lang', currentLang);
    }
    var formatBtns = t.querySelectorAll('.prompt-result-format-btn');
    for (var fi = 0; fi < formatBtns.length; fi++) {
      formatBtns[fi].classList.toggle('active', formatBtns[fi].getAttribute('data-format') === currentFormat);
    }
    var langBox = t.querySelector('.prompt-result-language');
    if (langBox) {
      langBox.classList.toggle('hidden', !canShowLanguage());
    }
  }
  var closeBtn = t.querySelector('.toast-close');
  if (closeBtn) closeBtn.addEventListener('click', function () {
    closePromptResultToast();
  });
  var viewBtn = t.querySelector('[data-action="view"]');
  var copyBtn = t.querySelector('[data-action="copy"]');
  var copyButtons = t.querySelectorAll('.prompt-result-action.is-copy');
  var formatButtons = t.querySelectorAll('.prompt-result-format-btn');
  for (var fbi = 0; fbi < formatButtons.length; fbi++) {
    formatButtons[fbi].addEventListener('click', function () {
      setFormat(this.getAttribute('data-format'));
    });
  }
  var langButtons = t.querySelectorAll('.prompt-result-lang-btn');
  for (var bi = 0; bi < langButtons.length; bi++) {
    langButtons[bi].addEventListener('click', function () {
      setLanguage(this.getAttribute('data-lang'));
    });
  }
  if (viewBtn) viewBtn.addEventListener('click', function () {
    t.classList.add('is-expanded');
    t.classList.remove('is-collapsed');
    setContainerExpanded(true);
    for (var cbi = 0; cbi < copyButtons.length; cbi++) copyButtons[cbi].classList.remove('hidden');
    viewBtn.classList.add('hidden');
  });
  function setPromptControlValue(input, content) {
    if (!input) return false;
    var value = String(content || '').trim();
    if (!value) return false;
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  function _fieldTextForControl(el) {
    if (!el) return '';
    var parts = [
      el.getAttribute('data-key'),
      el.getAttribute('name'),
      el.getAttribute('id'),
      el.getAttribute('placeholder'),
      el.getAttribute('aria-label'),
      el.getAttribute('title')
    ];
    var fieldBox = el.closest ? el.closest('.fg, .quick-text-fg, .prompt-fg, .ref-image-section') : null;
    if (fieldBox) parts.push(fieldBox.textContent || '');
    return parts.join(' ').toLowerCase();
  }
  function _isNegativePromptControl(el) {
    var text = _fieldTextForControl(el);
    return /negative|neg[_ -]?prompt|反向提示词|负面提示词|负向提示词|负面|反向/.test(text);
  }
  function findMainPromptInput() {
    var inputs = document.querySelectorAll('#promptInput');
    for (var i = 0; i < inputs.length; i++) {
      if (!_isNegativePromptControl(inputs[i])) return inputs[i];
    }
    return inputs[0] || null;
  }
  function findNegativePromptInput(mainInput) {
    var selectors = [
      '#quickFormFields textarea',
      '#quickFormFields input[type="text"]',
      '#advFields textarea',
      '#advFields input[type="text"]',
      'textarea[data-key]',
      'input[type="text"][data-key]'
    ];
    var seen = [];
    var candidates = document.querySelectorAll(selectors.join(','));
    for (var i = 0; i < candidates.length; i++) {
      var el = candidates[i];
      if (!el || el === mainInput || seen.indexOf(el) >= 0) continue;
      seen.push(el);
      if (el.disabled || el.type === 'hidden') continue;
      if (_isNegativePromptControl(el)) return el;
    }
    return null;
  }
  function replicateExpertPrompt(kind) {
    var positive = expertPositivePromptText();
    var negative = expertNegativePromptText();
    var mainInput = findMainPromptInput();
    var negativeInput = findNegativePromptInput(mainInput);
    var wrote = false;
    if (kind === 'negative') {
      wrote = setPromptControlValue(negativeInput || mainInput, negative);
    } else if (kind === 'full') {
      var fullFallback = negativeInput ? positive : expertFullPromptText();
      wrote = setPromptControlValue(mainInput, fullFallback);
      if (negativeInput && negative) wrote = setPromptControlValue(negativeInput, negative) || wrote;
    } else {
      wrote = setPromptControlValue(mainInput, positive);
    }
    if (!wrote) {
      if (window.CW && CW.showToast) CW.showToast('没有可复刻的提示词', 'info');
      return;
    }
    if (window.CW && typeof CW.registerPromptTranslationPair === 'function') {
      CW.registerPromptTranslationPair(promptZh, promptEn);
    }
    if (window.CW && CW.syncClearPromptButton) CW.syncClearPromptButton();
    var focusTarget = (kind === 'negative' && negativeInput) ? negativeInput : mainInput;
    if (focusTarget && focusTarget.focus) focusTarget.focus();
    t.classList.add('is-copied');
    closePromptResultToast();
  }
  var copyFullBtn = t.querySelector('[data-action="replicate-full"]');
  var copyPositiveBtn = t.querySelector('[data-action="replicate-positive"]');
  var copyNegativeBtn = t.querySelector('[data-action="replicate-negative"]');
  if (copyFullBtn) copyFullBtn.addEventListener('click', function () {
    replicateExpertPrompt('full');
  });
  if (copyPositiveBtn) copyPositiveBtn.addEventListener('click', function () {
    replicateExpertPrompt('positive');
  });
  if (copyNegativeBtn) copyNegativeBtn.addEventListener('click', function () {
    replicateExpertPrompt('negative');
  });
  if (copyBtn) copyBtn.addEventListener('click', function () {
	    var input = findMainPromptInput();
	    if (window.CW && typeof CW.registerPromptTranslationPair === 'function') {
	      CW.registerPromptTranslationPair(promptZh, promptEn);
	    }
	    if (input) {
	      input.value = currentText;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }
    if (window.CW && CW.syncClearPromptButton) CW.syncClearPromptButton();
    t.classList.add('is-copied');
    closePromptResultToast();
  });
  container.appendChild(t);
}

function showToast(message, type) {
  var container = _ensureToastContainer();
  type = type || 'info';
  var aliases = {
    success: 'done',
    warning: 'warn',
    danger: 'error',
    loading: 'generating'
  };
		  var resolvedType = aliases[type] || type;
  if (_isGenerationStatusToast(message, resolvedType) && !_isGenerationStatusToastAllowed(message, resolvedType)) {
    return;
  }
  var generationSlot = _isGenerationStatusToast(message, resolvedType);
				  var iconMap = {
		    info: 'info',
		    queued: 'clock',
		    generating: 'loader',
		    done: 'check-circle',
		    favorite: 'heart',
		    unfavorite: 'heart',
		    warn: 'alert-triangle',
		    error: 'x-circle'
		  };
  // Dedup: remove existing toast with same message
  var existing = container.querySelectorAll('.toast');
  for (var ei = 0; ei < existing.length; ei++) {
    if ((generationSlot && existing[ei].getAttribute && existing[ei].getAttribute('data-toast-scope') === 'generation') ||
        existing[ei].textContent.indexOf(message) >= 0) {
      existing[ei].parentNode.removeChild(existing[ei]);
      if (!generationSlot) break;
    }
  }
  var t = document.createElement('div');
	  t.className = 'toast toast-' + resolvedType;
  if (generationSlot && t.setAttribute) t.setAttribute('data-toast-scope', 'generation');
	  t.innerHTML = ''
	    + '<span class="toast-icon">' + (window.CW && CW.icon ? CW.icon(iconMap[resolvedType] || 'bell', 16) : '') + '</span>'
	    + '<span class="toast-content">'
	    +   '<span class="toast-message">' + escH(message) + '</span>'
	    + '</span>'
    + '<button class="toast-close" type="button" title="关闭">×</button>';
  var closeBtn = t.querySelector('.toast-close');
  if (closeBtn) closeBtn.addEventListener('click', function () {
    if (t.parentNode) t.parentNode.removeChild(t);
  });
  container.appendChild(t);
  setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 4000);
}

function initDragScroll(selector) {
    var el = document.querySelector(selector);
    if (!el) return;
    if (el.dataset.dragScrollBound === '1') return;
    el.dataset.dragScrollBound = '1';
    var isDown = false, hasDragged = false, startX, scrollLeft;
    var threshold = 6;
    function wheelDeltaPx(e) {
      var unit = 1;
      if (e.deltaMode === 1) unit = 16;
      else if (e.deltaMode === 2) unit = el.clientWidth || 1;
      return {
        x: e.deltaX * unit,
        y: e.deltaY * unit
      };
    }
    function canWheelHorizontally(delta) {
      var maxLeft = Math.max(0, el.scrollWidth - el.clientWidth);
      if (maxLeft <= 1) return false;
      if (delta < 0) return el.scrollLeft > 0;
      if (delta > 0) return el.scrollLeft < maxLeft - 1;
      return false;
    }
    el.addEventListener("mousedown", function(e) {
      isDown = true;
      hasDragged = false;
      startX = e.pageX - el.offsetLeft;
      scrollLeft = el.scrollLeft;
    });
    el.addEventListener("mouseleave", function() {
      if (!isDown) return;
      isDown = false;
      hasDragged = false;
      el.classList.remove("dragging");
    });
    el.addEventListener("mouseup", function() {
      if (!isDown) return;
      isDown = false;
      hasDragged = false;
      el.classList.remove("dragging");
    });
    el.addEventListener("mousemove", function(e) {
      if (!isDown) return;
      var x = e.pageX - el.offsetLeft;
      var walk = (x - startX);
      if (!hasDragged) {
        if (Math.abs(walk) < threshold) return;
        hasDragged = true;
        el.classList.add("dragging");
      }
      e.preventDefault();
      el.scrollLeft = scrollLeft - walk;
    });
    el.addEventListener("wheel", function(e) {
      var delta = wheelDeltaPx(e);
      var dominant = Math.abs(delta.y) >= Math.abs(delta.x) ? delta.y : delta.x;
      if (!canWheelHorizontally(dominant)) return;
      e.preventDefault();
      el.scrollLeft += dominant;
    }, { passive: false });
  }

function rndSeed(btnEl) {
    const input = btnEl ? btnEl.parentElement.querySelector('input[type="number"]') : null;
    if (input) input.value = Math.floor(Math.random() * 2 ** 53);
  }

async function wfUploadOverlay(files) {
    const zone = $('#wfUploadZone');
    let ok = 0,
      fail = 0;
    for (const file of files) {
      if (!file.name.endsWith('.json')) {
        fail++;
        continue;
      }
      const fd = new FormData();
      fd.append('file', file);
      try {
        const r = await fetch(`${API}/api/workflows/upload`, { method: 'POST', body: fd });
        if (!r.ok) throw new Error('upload');
        ok++;
      } catch (e) {
        fail++;
      }
    }
    // Show result briefly
    const msg = document.createElement('div');
    msg.className = 'wf-upload-progress ' + (fail ? 'wf-upload-err' : 'wf-upload-ok');
    msg.textContent = fail ? `完成：${ok} 成功，${fail} 失败` : `成功上传 ${ok} 个工作流`;
    zone.parentElement.appendChild(msg);
    setTimeout(() => msg.remove(), 3000);
    window.CW.loadWorkflows();
    window.CW.loadWfMeta();
  }

function initOverlayUpload() {
    const zone = $('#wfUploadZone');
    const input = $('#wfUploadInput');
    if (!zone || !input) return;
    zone.addEventListener('click', (e) => {
      if (e.target.tagName === 'LABEL') return; // let label click through
      input.click();
    });
    input.addEventListener('change', () => {
      if (input.files.length) wfUploadOverlay(Array.from(input.files));
      input.value = '';
    });
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      const files = Array.from(e.dataTransfer.files).filter((f) => f.name.endsWith('.json'));
      if (files.length) wfUploadOverlay(files);
    });
  }

function initAdvToggle() {
    $('#advToggle').addEventListener('click', () => {
      A.advOpen = !A.advOpen;
      $('#advToggle').classList.toggle('open', A.advOpen);
      $('#advBody').classList.toggle('open', A.advOpen);
    });
  }

  if (!window.CW) window.CW = {};
  window.CW.clearPrompt = clearPrompt;
  window.CW.initAdvToggle = initAdvToggle;
  window.CW.initOverlayUpload = initOverlayUpload;
  window.CW.initResizeHandle = initResizeHandle;
  window.CW.initDragScroll = initDragScroll;
  window.CW.toast = showToast;
  window.CW.showPromptInterrogatePendingToast = showPromptInterrogatePendingToast;
  window.CW.showPromptResultToast = showPromptResultToast;
  window.CW.clearPromptInterrogateToast = clearPromptInterrogateToast;
  window.CW.syncClearPromptButton = syncClearPromptButton;
})();
