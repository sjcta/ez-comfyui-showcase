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
  var _ideogramCanvasState = { mode: 'text', activeTool: 'rect', shapes: [], selectedId: '', nextId: 1 };

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
  var WAN_VIDEO_MAX_PIXELS = 896 * 512;
  var WAN_VIDEO_RATIO_PRESETS = [
    [512, 896, '9:16', '14px', '24px'],
    [576, 768, '3:4', '18px', '24px'],
    [672, 672, '1:1', '22px', '22px'],
    [768, 576, '4:3', '24px', '18px'],
    [896, 512, '16:9', '28px', '16px']
  ];
  var STYLE_PROMPT_VERSION = 4;
  var STYLE_CATEGORIES = [
    { id: 'photography', label: '摄影/人像' },
    { id: 'film', label: '影像质感' },
    { id: 'game', label: '游戏制作' },
    { id: 'illustration', label: '插画/动漫' },
    { id: 'render3d', label: '3D/材质' },
    { id: 'commercial', label: '商业/设计' }
  ];
  var STYLE_PRESETS = [
    {
      id: 'hyperrealistic',
      category: 'photography',
      label: '超写实',
      summary: '真实皮肤、物理光照、镜头质感',
      lock: 'STYLE LOCK: final image must read as high-fidelity real-world photography. Preserve subject, pose, composition, and objects, but convert the rendering into real camera optics, physically plausible light, natural skin/material response, and photographic depth.',
      generic: 'Photorealistic visual treatment with natural skin texture, physically plausible lighting, realistic lens rendering, coherent material response, controlled high dynamic range, clean color grading, crisp detail without an overprocessed look.'
    },
    {
      id: 'realistic_photo',
      category: 'photography',
      label: '写实摄影',
      summary: '生活化摄影、自然光、真实色彩',
      lock: 'STYLE LOCK: final image must look like an authentic photograph captured in a believable real environment. Preserve the scene content while grounding lighting, color, texture, shadows, lens behavior, and retouching in natural photography.',
      generic: 'Realistic photography style with believable everyday atmosphere, natural ambient light, accurate color response, grounded shadows, authentic textures, restrained retouching, and a documentary sense of presence.'
    },
    {
      id: 'influencer_glam',
      category: 'photography',
      label: '网红',
      summary: '社媒大片、精致妆造、柔和补光',
      lock: 'STYLE LOCK: final image must become a polished social-media editorial beauty shot. Reinterpret the subject through refined styling, flattering soft light, clean separation, premium lifestyle color, and camera-ready glam presentation.',
      generic: 'Polished social-media editorial look with refined styling, flattering soft key light, clean background separation, smooth but natural retouching, bright engaging color, confident composition, and premium lifestyle energy.'
    },
    {
      id: 'beauty_portrait',
      category: 'photography',
      label: '美颜',
      summary: '高级修饰、均匀肤色、保留五官结构',
      lock: 'STYLE LOCK: final image must prioritize premium beauty-portrait retouching. Preserve identity and facial structure while improving skin finish, makeup clarity, hair detail, soft flattering light, and elegant portrait polish.',
      generic: 'Beauty portrait finish with even skin tone, soft facial lighting, refined makeup detail, gentle highlight control, elegant hair and fabric texture, natural face structure preservation, and premium portrait retouching.'
    },
    {
      id: 'film_noir',
      category: 'film',
      label: '黑色电影',
      summary: '低调光、高反差、硬阴影',
      lock: 'STYLE LOCK: final image must become a film noir still. Preserve subject and composition while converting the scene into low-key lighting, hard directional shadows, deep blacks, high contrast, restrained monochrome or near-monochrome color, Venetian-blind-like shadow geometry when appropriate, and tense dramatic staging.',
      generic: 'Film noir image language with chiaroscuro lighting, hard shadow shapes, deep contrast, restrained color, smoke or rain atmosphere when appropriate, and suspenseful cinematic framing.'
    },
    {
      id: 'vintage_film',
      category: 'film',
      label: '胶片复古',
      summary: '35mm颗粒、晕光、轻微褪色',
      lock: 'STYLE LOCK: final image must look like a vintage 35mm film photograph. Preserve the subject and layout while converting the image into analog film response, visible fine grain, soft halation around highlights, slight color fade, gentle lens softness, imperfect exposure, and period-photo texture.',
      generic: 'Vintage film photography look with 35mm grain, halation, faded color response, soft highlight bloom, organic lens imperfections, and nostalgic analog texture.'
    },
    {
      id: 'cyberpunk_neon',
      category: 'film',
      label: '赛博霓虹',
      summary: '霓虹雨夜、高饱和反光、未来街景',
      lock: 'STYLE LOCK: final image must become a cyberpunk neon scene. Preserve the subject and composition while converting the environment into saturated neon signage, wet reflective surfaces, dense urban night atmosphere, cyan-magenta color contrast, futuristic detail, and high-energy sci-fi lighting.',
      generic: 'Cyberpunk neon visual style with rainy night streets, saturated cyan-magenta lighting, glowing signage, reflective pavement, futuristic props, atmospheric haze, and dense urban depth.'
    },
    {
      id: 'aaa_game_asset',
      category: 'game',
      label: 'AAA游戏资产',
      summary: 'PBR设定图、硬表面、资产展示',
      lock: 'STYLE LOCK: final image must be AAA game character or prop asset concept art, not a real photograph. Preserve the exact subject category, including non-human, animal-like, robotic, mechanical, creature, vehicle, or object subjects; do not convert the subject into a human or ordinary animal. Present the subject as a production-ready game asset with clear silhouette, hard-surface or material design language, PBR material callouts, controlled key art lighting, and readable front-facing design.',
      generic: 'AAA game asset concept art with stylized non-photographic rendering, strong readable silhouette, hard-surface/mechanical or material design detail, production-ready asset clarity, controlled edge definition, and game key art lighting.'
    },
    {
      id: 'low_poly_game',
      category: 'game',
      label: '低多边形游戏',
      summary: '块面几何、简化材质、清晰轮廓',
      lock: 'STYLE LOCK: final image must become low-poly game art. Preserve the subject and composition while rebuilding forms with visible simplified polygon facets, angular geometry, flat or softly stepped shading, reduced texture detail, simple materials, clean silhouette, and stylized game diorama clarity.',
      generic: 'Low-poly game art style with simplified geometry, faceted surfaces, clean angular silhouette, minimal texture noise, flat-shaded or softly stepped lighting, and readable stylized game-scene composition.'
    },
    {
      id: 'pixel_game',
      category: 'game',
      label: '像素游戏',
      summary: '像素格、有限色板、Sprite感',
      lock: 'STYLE LOCK: final image must become pixel art game artwork. Preserve the subject and composition while converting all forms into deliberate pixel-grid construction, limited color palette, hard-edged clusters, sprite-like readability, no photographic texture, and retro game scene composition.',
      generic: 'Pixel art game style with visible pixel grid, limited palette, hard-edged color clusters, sprite readability, simplified lighting, retro game mood, and crisp non-photographic block detail.'
    },
    {
      id: 'isometric_game',
      category: 'game',
      label: '等距游戏场景',
      summary: '2.5D俯视、地图块、场景资产',
      lock: 'STYLE LOCK: final image must become an isometric 2.5D game scene. Preserve key subject identity while arranging the scene in a clear isometric camera angle, tile-like spatial organization, miniature game-world scale, readable props, simplified shadows, and game map asset clarity.',
      generic: 'Isometric game scene style with 2.5D camera angle, tile-like layout, miniature world readability, clean props, controlled shadows, stylized assets, and game map composition.'
    },
    {
      id: 'card_game_illustration',
      category: 'game',
      label: '卡牌游戏立绘',
      summary: '角色立绘、强轮廓、装备细节',
      lock: 'STYLE LOCK: final image must become premium trading-card game key art. Preserve the subject while converting it into heroic centered illustration, strong silhouette, dramatic rim light, detailed costume/armor/prop design, layered fantasy or sci-fi atmosphere, and collectible card splash-art polish.',
      generic: 'Trading-card game illustration style with heroic centered composition, strong silhouette, dramatic rim lighting, detailed equipment and materials, atmospheric background layers, and premium splash-art finish.'
    },
    {
      id: 'anime',
      category: 'illustration',
      label: '动漫',
      summary: '清晰线条、赛璐璐上色、角色表现',
      lock: 'STYLE LOCK: final image must be rendered as finished anime character artwork. Preserve subject identity, pose, composition, clothing, and scene objects while converting photographic cues into clean linework, cel shading, simplified shape language, and expressive anime facial design.',
      generic: 'Anime illustration style with clean linework, expressive character design, appealing facial features, cel-shaded color blocks, polished highlight accents, clear shape language, and dynamic composition.'
    },
    {
      id: 'premium_3d',
      category: 'render3d',
      label: '3D',
      summary: 'PBR 材质、全局光照、高级渲染',
      lock: 'STYLE LOCK: final image must become a high-end 3D production render. Preserve the subject and layout while converting surfaces, light transport, reflections, volume, camera depth, and material response into polished PBR/CG rendering.',
      generic: 'High-end 3D render aesthetic with PBR materials, global illumination, precise reflections, sculpted form, polished surface detail, studio-quality lighting, and a clean production-render finish.'
    },
    {
      id: 'guochao_illustration',
      category: 'illustration',
      label: '国潮',
      summary: '现代国风、装饰纹样、强色彩秩序',
      lock: 'STYLE LOCK: final image must become a modern Chinese-inspired editorial illustration. Preserve subject and composition while reinterpreting the visual language through ornamental rhythm, cultural motifs, graphic color hierarchy, and refined decorative pattern systems.',
      generic: 'Modern Chinese-inspired illustration style with decorative pattern systems, confident color hierarchy, refined cultural motifs, elegant ornamental rhythm, graphic composition, and contemporary editorial polish.'
    },
    {
      id: 'commercial_product',
      category: 'commercial',
      label: '商业产品',
      summary: '棚拍高光、材质反射、广告构图',
      lock: 'STYLE LOCK: final image must read as commercial advertising/product photography. Preserve the main subject while reshaping light, reflection, material texture, cleanliness, composition, and finish toward a premium studio campaign image.',
      generic: 'Commercial product photography look with controlled studio lighting, clean highlight shaping, premium material reflections, precise surface texture, uncluttered composition, and polished advertising-grade finish.'
    }
  ];
  var STYLE_FAMILY_BLOCKS = {
    generic: 'Family tuning: treat the selected STYLE LOCK as the highest-priority visual target. Preserve subject, pose, composition, and required objects, but reinterpret any conflicting style words from the user prompt into the selected style.',
    qwen: 'Qwen tuning: use direct bilingual-friendly positive phrasing. Treat STYLE LOCK as highest priority, emphasize precise subject adherence, coherent text or graphic layout when present, and natural integration of edits into the selected style.',
    flux2: 'FLUX.2 tuning: use complete natural-language English descriptions. Treat STYLE LOCK as highest priority, keep subject-action-style-context explicit, and describe the desired final image without negative-prompt exclusions.',
    z_image: 'Z-Image tuning: treat STYLE LOCK as highest priority. Prioritize precise instruction adherence, bilingual text-rendering clarity, clean layout, coherent lighting, and sharp but not oversharpened material definition in the selected style.',
    ernie: 'ERNIE prompt-enhancer tuning / 画风锁定: 将 STYLE LOCK 视为最高优先级。提示词增强开启时，必须把用户提示词改写到所选画风中，而不是保留原有摄影、写实、插画或渲染倾向；必须保留主体类别和身份，尤其是非人类、动物、机器人、机械、道具、车辆或物体主体，不能替换为真人；保留姿态、构图、物体和文字信息，并输出符合所选画风的最终视觉描述。'
  };
  var STYLE_FAMILY_LABELS = {
    generic: '通用',
    qwen: 'Qwen',
    flux2: 'Flux2',
    z_image: 'Z-Image',
    ernie: 'ERNIE'
  };

function _hasFieldClass(fields, pattern) {
    return (fields || A._wfFieldMeta || []).some(function(f) {
      return f && pattern.test(String(f.class_type || ''));
    });
  }

function _styleFamilyForWorkflow(fields) {
    var workflow = String(A.currentWF || '');
    if (/ernie/i.test(workflow) || _hasFieldClass(fields, /ERNIE/i)) return 'ernie';
    if (/z[-_ ]?image|z[-_ ]?xxx|nunchaku/i.test(workflow) || _hasFieldClass(fields, /ZImage|NunchakuZImage/i)) return 'z_image';
    if (/qwen|千问/i.test(workflow) || _hasFieldClass(fields, /QwenImage/i)) return 'qwen';
    if (/flux[\s_.-]*2/i.test(workflow) || _hasFieldClass(fields, /^Flux2Scheduler$/)) return 'flux2';
    return 'generic';
  }

function _stylePresetById(id) {
    var key = String(id || '');
    for (var i = 0; i < STYLE_PRESETS.length; i++) {
      if (STYLE_PRESETS[i].id === key) return STYLE_PRESETS[i];
    }
    return null;
  }

function _styleCategoryById(id) {
    var key = String(id || '');
    for (var i = 0; i < STYLE_CATEGORIES.length; i++) {
      if (STYLE_CATEGORIES[i].id === key) return STYLE_CATEGORIES[i];
    }
    return null;
  }

function _styleCategoryForPreset(presetOrId) {
    var preset = typeof presetOrId === 'string' ? _stylePresetById(presetOrId) : presetOrId;
    var categoryId = preset && preset.category ? String(preset.category) : '';
    return _styleCategoryById(categoryId);
  }

function _stylePresetsForCategory(categoryId) {
    var key = String(categoryId || '');
    if (!_styleCategoryById(key)) return [];
    return STYLE_PRESETS.filter(function(preset) {
      return preset && preset.category === key;
    });
  }

function _currentStyleSelect() {
    return document.querySelector('#stylePresetSelect');
  }

  function _currentStylePresetId() {
    var select = _currentStyleSelect();
    return select ? String(select.value || '') : '';
  }

  var PROMPT_STRATEGY_OPTIONS = [
    { id: 'none', label: '不优化', summary: '按原提示词直接提交' },
    { id: 'auto', label: '智能推荐', summary: 'LLM先汇总画面brief，再按工作流补全要求' },
    { id: 'xhs_cover', label: '小红书封面', summary: 'LLM拆解点击理由、主体和标题安全区' },
    { id: 'product_poster', label: '产品海报', summary: 'LLM拆解产品主体、商业光影和卖点留白' },
    { id: 'ecommerce', label: '电商主图', summary: 'LLM拆解商品完整度、干净背景和转化展示' },
    { id: 'portrait', label: '人物写真', summary: 'LLM拆解脸部、姿态、皮肤和摄影光线' },
    { id: 'realistic_scene', label: '写实场景', summary: 'LLM拆解空间、透视、环境和真实镜头' },
    { id: 'illustration', label: '插画/二次元', summary: 'LLM拆解线条、色彩、角色轮廓和完成度' },
    { id: 'text_poster', label: '文字海报', summary: 'LLM拆解文字层级、对比和阅读留白' },
    { id: 'reference_edit', label: '参考图改图', summary: 'LLM拆解参考图保留项和局部修改边界' }
  ];

function _promptStrategyById(id) {
    var key = String(id || 'none');
    for (var i = 0; i < PROMPT_STRATEGY_OPTIONS.length; i++) {
      if (PROMPT_STRATEGY_OPTIONS[i].id === key) return PROMPT_STRATEGY_OPTIONS[i];
    }
    return PROMPT_STRATEGY_OPTIONS[0];
  }

function _currentPromptStrategyId() {
    return 'none';
  }

function _promptOptimizeMenuItemsHtml() {
    var out = '<button class="prompt-optimize-choice" type="button" data-optimize-kind="standard" data-prompt-strategy="">'
      + '<span>标准优化</span>'
      + '</button>';
    for (var i = 0; i < PROMPT_STRATEGY_OPTIONS.length; i++) {
      var item = PROMPT_STRATEGY_OPTIONS[i];
      if (!item || item.id === 'none') continue;
      var label = item.id === 'auto' ? '智能优化' : item.label;
      out += '<button class="prompt-optimize-choice" type="button" data-optimize-kind="strategy" data-prompt-strategy="' + escA(item.id) + '">'
        + '<span>' + escH(label) + '</span>'
        + '</button>';
    }
    return out;
  }

function closePromptOptimizeMenu() {
    var layer = document.getElementById('promptOptimizeMenuLayer');
    if (layer && layer.parentNode) layer.parentNode.removeChild(layer);
    document.removeEventListener('keydown', _promptOptimizeMenuKeydown);
    document.removeEventListener('pointerdown', _promptOptimizeMenuOutsidePointer);
  }

function _positionPromptOptimizeMenu(menu, anchor) {
    if (!menu || !anchor || !anchor.getBoundingClientRect) return;
    var rect = anchor.getBoundingClientRect();
    var width = window.innerWidth < 560
      ? Math.min(220, Math.max(168, window.innerWidth - 20))
      : 276;
    var top = rect.bottom + 8;
    var maxHeight = Math.min(320, Math.max(120, window.innerHeight - top - 10));
    var anchorCenter = rect.left + (rect.width / 2);
    var left = Math.max(10, Math.min(window.innerWidth - width - 10, anchorCenter - (width / 2)));
    menu.style.width = width + 'px';
    menu.style.maxHeight = maxHeight + 'px';
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

function openPromptOptimizeMenu(event) {
    var input = $('#promptInput');
    var raw = (input && input.value ? input.value : '').trim();
    var copy = _promptOptimizeCopy();
    if (!raw) {
      if (window.CW && CW.toast) CW.toast(copy.empty, 'warn');
      if (input) input.focus();
      return;
    }
    closePromptOptimizeMenu();
    var html = '<div class="prompt-optimize-menu-layer" id="promptOptimizeMenuLayer" onclick="CW.closePromptOptimizeMenu()">'
      + '<div class="prompt-optimize-menu" id="promptOptimizeMenu" role="menu" aria-label="' + escA(copy.label || '优化提示词') + '" onclick="event.stopPropagation()">'
      + '<div class="prompt-optimize-menu-head"><span>' + escH(copy.label || '优化提示词') + '</span></div>'
      + '<div class="prompt-optimize-menu-list">'
      + _promptOptimizeMenuItemsHtml()
      + '</div>'
      + '</div>'
      + '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
    var menu = document.getElementById('promptOptimizeMenu');
    var anchor = (event && event.currentTarget) || $('#optimizePromptBtn');
    _positionPromptOptimizeMenu(menu, anchor);
    var buttons = menu ? menu.querySelectorAll('.prompt-optimize-choice') : [];
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function() {
        runPromptOptimizeChoice(this.dataset.optimizeKind || 'standard', this.dataset.promptStrategy || '');
      });
    }
    setTimeout(function() {
      document.addEventListener('keydown', _promptOptimizeMenuKeydown);
      document.addEventListener('pointerdown', _promptOptimizeMenuOutsidePointer);
    });
  }

function _promptOptimizeMenuKeydown(event) {
    if (event && event.key === 'Escape') closePromptOptimizeMenu();
  }

function _promptOptimizeMenuOutsidePointer(event) {
    var menu = document.getElementById('promptOptimizeMenu');
    var btn = document.getElementById('optimizePromptBtn');
    var target = event && event.target;
    if (menu && target && menu.contains(target)) return;
    if (btn && target && btn.contains(target)) return;
    closePromptOptimizeMenu();
  }

function _promptStrategyReadCookie(name) {
    try {
      var prefix = encodeURIComponent(name) + '=';
      var parts = String(document.cookie || '').split(';');
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i].trim();
        if (part.indexOf(prefix) === 0) return decodeURIComponent(part.slice(prefix.length));
      }
    } catch (e) {}
    return '';
  }

function _promptStrategyFetchOptions(body) {
    var headers = { 'Content-Type': 'application/json' };
    var csrf = _promptStrategyReadCookie('ez_comfyui_csrf');
    if (csrf) headers['X-CSRF-Token'] = csrf;
    return {
      method: 'POST',
      credentials: 'include',
      headers: headers,
      body: JSON.stringify(body)
    };
  }

async function _promptStrategyOptimizationFields(rawPrompt) {
    var fields = { __user_prompt: rawPrompt };
    _applyCurrentSizeLimit();
    var metas = [];
    try {
      metas = await _getSubmitFieldsMeta();
    } catch (e) {
      metas = A._wfFieldMeta || [];
    }
    for (var i = 0; i < (metas || []).length; i++) {
      var f = metas[i] || {};
      var key = _fieldKeyForMeta(f);
      if (!key) continue;
      if (_isPromptSubmitField(f)) {
        fields[key] = rawPrompt;
      } else if (_isLatentDimensionField(f, 'width') || _isFlux2SchedulerSizeField(f, 'width')) {
        fields[key] = parseInt(($('#widthInput') || {}).value, 10) || f.value || 0;
      } else if (_isLatentDimensionField(f, 'height') || _isFlux2SchedulerSizeField(f, 'height')) {
        fields[key] = parseInt(($('#heightInput') || {}).value, 10) || f.value || 0;
      } else if (_isImageReferenceModeField(f)) {
        fields[key] = _currentImageReferenceMode();
      } else if (_isMultiImageRefsField(f)) {
        fields[key] = JSON.stringify(_multiUploadedRefNames());
      } else if (f.class_type === 'LoadImage' && f.field === 'image') {
        fields[key] = _primaryReferenceImageValue() || f.value || '';
      } else if (_isReferenceVideoField(f)) {
        fields[key] = ($('#refVideoValue') || {}).value || f.value || '';
      } else if (_isReferenceAudioField(f)) {
        fields[key] = ($('#refAudioValue') || {}).value || f.value || '';
      } else if (_isBerniniRefsField(f)) {
        fields[key] = JSON.stringify(_berniniUploadedRefNames());
      } else {
        fields[key] = _currentFieldValueForMeta(f);
      }
    }
    $$('#quickFormFields [data-key], #advFields [data-key]').forEach(function(el) {
      if (!el || !el.dataset || !el.dataset.key) return;
      fields[el.dataset.key] = _readFieldControlValue(el);
    });
    fields.__user_prompt = rawPrompt;
    return fields;
  }

async function _runStandardPromptOptimize(raw) {
    var copy = _promptOptimizeCopy();
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
    return { optimized: optimized, data: data, label: '标准优化', toast: data.structured_prompt_json ? copy.doneJson : copy.done };
  }

async function _runStrategyPromptOptimize(raw, strategyId) {
    var selected = _promptStrategyById(strategyId || 'auto');
    var fields = await _promptStrategyOptimizationFields(raw);
    var fetcher = (window.CW && CW.auth && CW.auth.apiFetch) ? CW.auth.apiFetch : fetch;
    var response = await fetcher(
      API + '/api/prompt/strategy-optimize',
      _promptStrategyFetchOptions({
        prompt: raw,
        strategy: selected.id || 'auto',
        workflow: A.currentWF || '',
        fields: fields
      })
    );
    var data = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(data.detail || data.message || '出图优化失败');
    var optimized = String(data.optimized_prompt || data.prompt || '').trim();
    if (!optimized) throw new Error('优化结果为空');
    window.CW.lastPromptStrategyOptimization = data;
    return {
      optimized: optimized,
      data: data,
      label: selected.id === 'auto' ? '智能优化' : (data.prompt_strategy_label || selected.label || '出图优化'),
      toast: (selected.id === 'auto' ? '智能优化' : (data.prompt_strategy_label || selected.label || '出图优化')) + '已写入提示词'
    };
  }

async function runPromptOptimizeChoice(kind, strategyId) {
    var input = $('#promptInput');
    var raw = (input && input.value ? input.value : '').trim();
    var btn = $('#optimizePromptBtn');
    var copy = _promptOptimizeCopy();
    if (!raw) {
      if (window.CW && CW.toast) CW.toast(copy.empty, 'warn');
      if (input) input.focus();
      return;
    }
    closePromptOptimizeMenu();
    var oldHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.classList.add('is-loading');
      btn.innerHTML = (window.CW && CW.icon ? CW.icon('loader') : '') + ' 优化中';
    }
    try {
      var result = kind === 'strategy'
        ? await _runStrategyPromptOptimize(raw, strategyId)
        : await _runStandardPromptOptimize(raw);
      _setPromptInputValue(result.optimized);
      if (kind === 'strategy') {
        _clearPromptOptimizationVariants();
      } else {
        _showPromptOptimizationVariants(result.data);
      }
      closePromptOptimizeMenu();
      if (window.CW && CW.toast) CW.toast(result.toast || (result.label + '已写入提示词'), 'ok');
    } catch (e) {
      console.warn('[runPromptOptimizeChoice] failed:', e);
      if (window.CW && CW.toast) CW.toast(e.message || copy.error, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.innerHTML = oldHtml || ((window.CW && CW.icon ? CW.icon('zap') : '') + ' ' + copy.label);
      }
    }
  }

function _stylePromptInfo(presetId, fields) {
    var preset = _stylePresetById(presetId);
    if (!preset) return null;
    var family = _styleFamilyForWorkflow(fields);
    var familyBlock = STYLE_FAMILY_BLOCKS[family] || STYLE_FAMILY_BLOCKS.generic;
    var familyLabel = STYLE_FAMILY_LABELS[family] || STYLE_FAMILY_LABELS.generic;
    var promptJson = {
      preset_id: preset.id,
      label: preset.label,
      category: preset.category || '',
      version: STYLE_PROMPT_VERSION,
      summary: preset.summary || '',
      style_lock: preset.lock || preset.generic || '',
      general_style: preset.generic || '',
      model_family: family,
      model_family_label: familyLabel,
      model_family_tuning: familyBlock
    };
    var prompt = JSON.stringify(promptJson);
    return {
      id: preset.id,
      label: preset.label,
      version: STYLE_PROMPT_VERSION,
      family: family,
      familyLabel: familyLabel,
      summary: preset.summary || '',
      promptJson: promptJson,
      prompt: prompt
    };
  }

  function _selectedStylePromptInfo(fields) {
    return _stylePromptInfo(_currentStylePresetId(), fields);
  }

  function _isIdeogram4Workflow(fields) {
    var wf = String(A.currentWF || '').split(/[\\/]/).pop();
    if (/ideogram/i.test(wf)) return true;
    return _hasFieldClass(fields || A._wfFieldMeta || [], /^Ideogram4Scheduler$/);
  }

  function _isOfficialIdeogram4Workflow(fields) {
    return _isIdeogram4Workflow(fields);
  }

function _isErniePromptEnhancerField(field) {
    if (!field) return false;
    var key = String(field.key || ((field.node_id || '') + '::' + (field.field || '')));
    var label = String(field.label || '');
    var title = String(field.node_title || '');
    return field.type === 'toggle'
      && /::value$/.test(key)
      && (/提示词增强|prompt enhancement/i.test(label) || /Enable prompt enhancement|Prompt Enhancement/i.test(title));
  }

function _bypassErniePromptEnhancerForStyle(styleInfo, fields, targetFields, snapshot) {
    if (!styleInfo || styleInfo.family !== 'ernie') return;
    (fields || []).forEach(function(field) {
      if (!_isErniePromptEnhancerField(field)) return;
      var key = field.key || ((field.node_id || '') + '::' + (field.field || ''));
      if (!key || key.indexOf('::') < 0) return;
      targetFields[key] = false;
      if (snapshot && snapshot.adv) snapshot.adv[key] = false;
      targetFields.__style_prompt_enhancer_bypass = 'ernie_direct_style_lock';
      if (snapshot && snapshot.adv) snapshot.adv.__style_prompt_enhancer_bypass = 'ernie_direct_style_lock';
    });
  }

function _stripExistingStylePromptBlocks(prompt) {
    return String(prompt || '')
      .replace(/(^|[\n\r])\s*\[Style Preset:[\s\S]*?\[\s*User Prompt\s*\]\s*/gi, '$1')
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/[\n\r]{3,}/g, '\n\n')
      .trim();
  }

  function _parsePromptJsonObject(prompt) {
    var text = String(prompt || '').trim();
    if (!text) return null;
    if (/^```/i.test(text)) {
      text = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
    }
    try {
      var parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch (e) {
      return null;
    }
  }

  function _promptJsonForStyle(prompt, styleInfo) {
    var base = _stripExistingStylePromptBlocks(prompt);
    var userJson = _parsePromptJsonObject(base);
    var out = userJson ? Object.assign({}, userJson) : { prompt: base };
    if (styleInfo && styleInfo.promptJson) {
      var existingStyle = out.style && typeof out.style === 'object' && !Array.isArray(out.style)
        ? out.style
        : {};
      out.style = Object.assign({}, existingStyle, styleInfo.promptJson);
    }
    return JSON.stringify(out);
  }

function _preparePromptForCurrentStyle(prompt) {
    return _stripExistingStylePromptBlocks(prompt);
  }

function _promptWithStylePreset(prompt, styleInfo) {
    if (!styleInfo || !styleInfo.promptJson) return String(prompt || '');
    return _promptJsonForStyle(prompt, styleInfo);
  }

function _stylePresetOptionsHtml(selectedId) {
    var selected = String(selectedId || '');
    var out = '<option value="">无风格增强</option>';
    for (var i = 0; i < STYLE_CATEGORIES.length; i++) {
      var category = STYLE_CATEGORIES[i];
      var presets = _stylePresetsForCategory(category.id);
      if (!presets.length) continue;
      out += '<optgroup label="' + escA(category.label) + '">';
      for (var j = 0; j < presets.length; j++) {
        var preset = presets[j];
        out += '<option value="' + escA(preset.id) + '"' + (preset.id === selected ? ' selected' : '') + '>' + escH(preset.label) + '</option>';
      }
      out += '</optgroup>';
    }
    return out;
  }

function _stylePresetControlHtml(fields) {
    var family = _styleFamilyForWorkflow(fields);
    var familyLabel = STYLE_FAMILY_LABELS[family] || STYLE_FAMILY_LABELS.generic;
    return '<div class="style-preset-fg style-preset-integrated" data-style-preset-root data-style-family="' + escA(family) + '">'
      + '<div class="style-preset-row">'
      + '<label for="stylePresetSelect" class="style-preset-inline-label">画面风格增强</label>'
      + '<select id="stylePresetSelect" class="style-preset-select" aria-label="画面风格增强">' + _stylePresetOptionsHtml() + '</select>'
      + '<span class="style-preset-family" data-style-family-label>族块 ' + escH(familyLabel) + '</span>'
      + '<span class="style-preset-summary" data-style-summary></span>'
      + '</div>'
      + '</div>';
  }

function _syncStylePresetControl(root, fields) {
    root = root || document.querySelector('[data-style-preset-root]');
    if (!root) return;
    var select = root.querySelector('#stylePresetSelect');
    var summary = root.querySelector('[data-style-summary]');
    var familyLabel = root.querySelector('[data-style-family-label]');
    var info = _stylePromptInfo(select ? select.value : '', fields || A._wfFieldMeta || []);
    var family = info ? info.family : _styleFamilyForWorkflow(fields);
    if (familyLabel) familyLabel.textContent = '族块 ' + (STYLE_FAMILY_LABELS[family] || STYLE_FAMILY_LABELS.generic);
    if (summary) summary.textContent = info ? info.summary : '';
    root.classList.toggle('is-active', !!info);
  }

function _setStylePresetValue(value) {
    var select = _currentStyleSelect();
    if (!select) return false;
    var preset = _stylePresetById(value);
    var root = select.closest('[data-style-preset-root]');
    select.innerHTML = _stylePresetOptionsHtml(preset ? preset.id : '');
    select.value = preset ? preset.id : '';
    _syncStylePresetControl(root);
    return true;
  }

function _initStylePresetControl(fields) {
    var root = document.querySelector('[data-style-preset-root]');
    if (!root || root.dataset.styleInited === '1') return;
    root.dataset.styleInited = '1';
    var select = root.querySelector('#stylePresetSelect');
    if (select) {
      select.addEventListener('change', function() {
        _syncStylePresetControl(root, fields);
      });
    }
    _syncStylePresetControl(root, fields);
  }

function _ideogramCanvasRoot() {
    return document.querySelector('[data-ideogram-canvas-root]');
  }

function _ideogramCanvasStage() {
    return document.querySelector('#ideogramCanvasStage');
  }

function _syncIdeogramCanvasAspect() {
    var stage = _ideogramCanvasStage();
    if (!stage) return;
    var w = parseInt(($('#widthInput') || {}).value || 1024, 10) || 1024;
    var h = parseInt(($('#heightInput') || {}).value || 1024, 10) || 1024;
    stage.style.aspectRatio = Math.max(1, w) + ' / ' + Math.max(1, h);
  }

function _ideogramCanvasShapes() {
    return (_ideogramCanvasState.shapes || []).filter(function(shape) {
      return shape && String(shape.text || '').trim();
    });
  }

function _ideogramCanvasControlHtml() {
    var addIcon = window.CW && CW.icon ? CW.icon('plus') : '+';
    var clearIcon = window.CW && CW.icon ? CW.icon('trash-2') : '';
    return '<div class="ideogram-canvas-root" data-ideogram-canvas-root>'
      + '<div class="ideogram-mode-row">'
      + '<div class="ideogram-mode-tabs" role="tablist" aria-label="Ideogram4 输入方式">'
      + '<button type="button" class="ideogram-mode-btn" data-ideogram-mode="text" aria-pressed="true">文本</button>'
      + '<button type="button" class="ideogram-mode-btn" data-ideogram-mode="canvas" aria-pressed="false">布局画布</button>'
      + '</div>'
      + '<div class="ideogram-tool-row">'
      + '<button type="button" class="ideogram-tool-btn" data-ideogram-tool="rect" title="绘制矩形"><span class="ideogram-tool-shape ideogram-tool-rect"></span>矩形</button>'
      + '<button type="button" class="ideogram-tool-btn" data-ideogram-tool="circle" title="绘制圆形"><span class="ideogram-tool-shape ideogram-tool-circle"></span>圆形</button>'
      + '<button type="button" class="ideogram-tool-btn" data-ideogram-add-shape="rect" title="添加矩形">' + addIcon + '<span>添加</span></button>'
      + '<button type="button" class="ideogram-tool-btn ideogram-clear-btn" data-ideogram-clear title="清空画布">' + clearIcon + '<span>清空</span></button>'
      + '</div>'
      + '</div>'
      + '<div class="ideogram-canvas-panel" data-ideogram-canvas-panel>'
      + '<div class="ideogram-canvas-stage" id="ideogramCanvasStage" aria-label="Ideogram4 布局画布"></div>'
      + '<div class="ideogram-canvas-status" data-ideogram-canvas-status></div>'
      + '</div>'
      + '</div>';
  }

function _setIdeogramCanvasMode(mode) {
    _ideogramCanvasState.mode = mode === 'canvas' ? 'canvas' : 'text';
    var root = _ideogramCanvasRoot();
    if (!root) return;
    root.classList.toggle('is-canvas-mode', _ideogramCanvasState.mode === 'canvas');
    root.querySelectorAll('[data-ideogram-mode]').forEach(function(btn) {
      var active = btn.getAttribute('data-ideogram-mode') === _ideogramCanvasState.mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

function _setIdeogramCanvasTool(tool) {
    _ideogramCanvasState.activeTool = tool === 'circle' ? 'circle' : 'rect';
    var root = _ideogramCanvasRoot();
    if (!root) return;
    root.querySelectorAll('[data-ideogram-tool]').forEach(function(btn) {
      btn.classList.toggle('active', btn.getAttribute('data-ideogram-tool') === _ideogramCanvasState.activeTool);
    });
  }

function _ideogramCanvasClampShape(shape) {
    shape.w = Math.max(8, Math.min(100, Number(shape.w) || 24));
    shape.h = Math.max(8, Math.min(100, Number(shape.h) || 18));
    shape.x = Math.max(0, Math.min(100 - shape.w, Number(shape.x) || 0));
    shape.y = Math.max(0, Math.min(100 - shape.h, Number(shape.y) || 0));
    return shape;
  }

function _addIdeogramCanvasShape(kind, options) {
    options = options || {};
    var shape = _ideogramCanvasClampShape({
      id: 'ig_' + (_ideogramCanvasState.nextId++),
      kind: kind === 'circle' ? 'circle' : 'rect',
      elementType: options.elementType === 'text' ? 'text' : 'obj',
      x: options.x == null ? 18 : options.x,
      y: options.y == null ? 18 : options.y,
      w: options.w == null ? 42 : options.w,
      h: options.h == null ? 24 : options.h,
      text: options.text || ''
    });
    _ideogramCanvasState.shapes.push(shape);
    _ideogramCanvasState.selectedId = shape.id;
    _setIdeogramCanvasMode('canvas');
    _renderIdeogramCanvasShapes();
    return shape;
  }

function _deleteIdeogramCanvasShape(id) {
    _ideogramCanvasState.shapes = (_ideogramCanvasState.shapes || []).filter(function(shape) {
      return shape.id !== id;
    });
    if (_ideogramCanvasState.selectedId === id) _ideogramCanvasState.selectedId = '';
    _renderIdeogramCanvasShapes();
  }

function _ideogramCanvasShapeLabel(shape) {
    return shape.kind === 'circle' ? '圆形' : '矩形';
  }

function _renderIdeogramCanvasShapes() {
    var stage = _ideogramCanvasStage();
    if (!stage) return;
    stage.innerHTML = '';
    var shapes = _ideogramCanvasState.shapes || [];
    if (!shapes.length) {
      var empty = document.createElement('div');
      empty.className = 'ideogram-canvas-empty';
      empty.textContent = '选择矩形或圆形工具，在画布中拖拽绘制区域';
      stage.appendChild(empty);
    }
    shapes.forEach(function(shape) {
      _ideogramCanvasClampShape(shape);
      var el = document.createElement('div');
      el.className = 'ideogram-shape ideogram-shape-' + shape.kind + (shape.id === _ideogramCanvasState.selectedId ? ' is-selected' : '');
      el.dataset.shapeId = shape.id;
      el.style.left = shape.x + '%';
      el.style.top = shape.y + '%';
      el.style.width = shape.w + '%';
      el.style.height = shape.h + '%';
      el.innerHTML = ''
        + '<div class="ideogram-shape-bar" data-shape-drag>'
        + '<span class="ideogram-shape-kind">' + escH(_ideogramCanvasShapeLabel(shape)) + '</span>'
        + '<select class="ideogram-shape-type" data-shape-element-type aria-label="元素类型">'
        + '<option value="obj"' + (shape.elementType !== 'text' ? ' selected' : '') + '>对象</option>'
        + '<option value="text"' + (shape.elementType === 'text' ? ' selected' : '') + '>文字</option>'
        + '</select>'
        + '<button type="button" class="ideogram-shape-delete" data-shape-delete title="删除">' + (window.CW && CW.icon ? CW.icon('x') : 'x') + '</button>'
        + '</div>'
        + '<textarea class="ideogram-shape-text" data-shape-text placeholder="这里写该区域的提示词"></textarea>'
        + '<span class="ideogram-shape-resize" data-shape-resize aria-hidden="true"></span>';
      var text = el.querySelector('[data-shape-text]');
      if (text) text.value = shape.text || '';
      stage.appendChild(el);
    });
    _syncIdeogramCanvasStatus();
  }

function _syncIdeogramCanvasStatus() {
    var status = document.querySelector('[data-ideogram-canvas-status]');
    if (!status) return;
    var usable = _ideogramCanvasShapes().length;
    status.textContent = usable ? ('将提交 ' + usable + ' 个融合场景元素') : '画布元素需要填写提示词后才会写入 JSON';
  }

function _stagePointToPercent(stage, event) {
    var rect = stage.getBoundingClientRect();
    var x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 100;
    var y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * 100;
    return [Math.max(0, Math.min(100, x)), Math.max(0, Math.min(100, y))];
  }

function _bindIdeogramCanvasPointer(stage) {
    if (!stage || stage.dataset.ideogramStageInited === '1') return;
    stage.dataset.ideogramStageInited = '1';
    stage.addEventListener('pointerdown', function(event) {
      if (event.button !== 0) return;
      var target = event.target;
      if (target && target.closest && target.closest('.ideogram-shape')) return;
      event.preventDefault();
      _setIdeogramCanvasMode('canvas');
      var start = _stagePointToPercent(stage, event);
      var shape = _addIdeogramCanvasShape(_ideogramCanvasState.activeTool || 'rect', {
        x: start[0],
        y: start[1],
        w: 10,
        h: 10
      });
      function onMove(moveEvent) {
        var point = _stagePointToPercent(stage, moveEvent);
        shape.x = Math.min(start[0], point[0]);
        shape.y = Math.min(start[1], point[1]);
        shape.w = Math.max(8, Math.abs(point[0] - start[0]));
        shape.h = Math.max(8, Math.abs(point[1] - start[1]));
        _renderIdeogramCanvasShapes();
      }
      function onUp() {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        _renderIdeogramCanvasShapes();
      }
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp, { once: true });
    });
  }

function _bindIdeogramShapeEvents(root) {
    if (!root || root.dataset.ideogramShapeInited === '1') return;
    root.dataset.ideogramShapeInited = '1';
    root.addEventListener('input', function(event) {
      var field = event.target && event.target.closest ? event.target.closest('[data-shape-text]') : null;
      if (!field) return;
      var el = field.closest('.ideogram-shape');
      var shape = _ideogramCanvasState.shapes.find(function(item) { return item.id === (el && el.dataset.shapeId); });
      if (!shape) return;
      shape.text = field.value;
      _syncIdeogramCanvasStatus();
    });
    root.addEventListener('change', function(event) {
      var select = event.target && event.target.closest ? event.target.closest('[data-shape-element-type]') : null;
      if (!select) return;
      var el = select.closest('.ideogram-shape');
      var shape = _ideogramCanvasState.shapes.find(function(item) { return item.id === (el && el.dataset.shapeId); });
      if (!shape) return;
      shape.elementType = select.value === 'text' ? 'text' : 'obj';
    });
    root.addEventListener('click', function(event) {
      var deleteBtn = event.target && event.target.closest ? event.target.closest('[data-shape-delete]') : null;
      if (!deleteBtn) return;
      var el = deleteBtn.closest('.ideogram-shape');
      _deleteIdeogramCanvasShape(el && el.dataset.shapeId);
    });
    root.addEventListener('pointerdown', function(event) {
      var shapeEl = event.target && event.target.closest ? event.target.closest('.ideogram-shape') : null;
      if (!shapeEl) return;
      var shape = _ideogramCanvasState.shapes.find(function(item) { return item.id === shapeEl.dataset.shapeId; });
      if (!shape) return;
      _ideogramCanvasState.selectedId = shape.id;
      if (event.target.closest('[data-shape-text], [data-shape-element-type], [data-shape-delete]')) {
        return;
      }
      var stage = _ideogramCanvasStage();
      if (!stage) return;
      var start = _stagePointToPercent(stage, event);
      var startShape = Object.assign({}, shape);
      var resizing = !!event.target.closest('[data-shape-resize]');
      event.preventDefault();
      function onMove(moveEvent) {
        var point = _stagePointToPercent(stage, moveEvent);
        var dx = point[0] - start[0];
        var dy = point[1] - start[1];
        if (resizing) {
          shape.w = Math.max(8, startShape.w + dx);
          shape.h = Math.max(8, startShape.h + dy);
        } else {
          shape.x = startShape.x + dx;
          shape.y = startShape.y + dy;
        }
        _ideogramCanvasClampShape(shape);
        _renderIdeogramCanvasShapes();
      }
      function onUp() {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      }
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp, { once: true });
    });
  }

function _initIdeogramCanvasControl(fields) {
    var root = _ideogramCanvasRoot();
    if (!root) return;
    root.querySelectorAll('[data-ideogram-mode]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        _setIdeogramCanvasMode(btn.getAttribute('data-ideogram-mode'));
      });
    });
    root.querySelectorAll('[data-ideogram-tool]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        _setIdeogramCanvasTool(btn.getAttribute('data-ideogram-tool'));
        _setIdeogramCanvasMode('canvas');
      });
    });
    root.querySelectorAll('[data-ideogram-add-shape]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var kind = btn.getAttribute('data-ideogram-add-shape') || _ideogramCanvasState.activeTool || 'rect';
        _addIdeogramCanvasShape(kind);
      });
    });
    var clear = root.querySelector('[data-ideogram-clear]');
    if (clear) {
      clear.addEventListener('click', function() {
        _ideogramCanvasState.shapes = [];
        _ideogramCanvasState.selectedId = '';
        _renderIdeogramCanvasShapes();
      });
    }
    _setIdeogramCanvasMode(_ideogramCanvasState.mode);
    _setIdeogramCanvasTool(_ideogramCanvasState.activeTool);
    _syncIdeogramCanvasAspect();
    _bindIdeogramCanvasPointer(_ideogramCanvasStage());
    _bindIdeogramShapeEvents(root);
    _renderIdeogramCanvasShapes();
  }

function _ideogramCanvasBbox(shape) {
    var y0 = Math.round(shape.y * 10);
    var x0 = Math.round(shape.x * 10);
    var y1 = Math.round((shape.y + shape.h) * 10);
    var x1 = Math.round((shape.x + shape.w) * 10);
    return [
      Math.max(0, Math.min(1000, y0)),
      Math.max(0, Math.min(1000, x0)),
      Math.max(0, Math.min(1000, y1)),
      Math.max(0, Math.min(1000, x1))
    ];
  }

function _ideogramCanvasExportPayload() {
    return {
      mode: _ideogramCanvasState.mode,
      activeTool: _ideogramCanvasState.activeTool,
      selectedId: _ideogramCanvasState.selectedId,
      nextId: _ideogramCanvasState.nextId,
      shapes: (_ideogramCanvasState.shapes || []).map(function(shape) {
        return {
          id: shape.id,
          kind: shape.kind,
          elementType: shape.elementType,
          x: shape.x,
          y: shape.y,
          w: shape.w,
          h: shape.h,
          text: shape.text || ''
        };
      })
    };
  }

function _restoreIdeogramCanvasFromFieldValue(value) {
    try {
      var parsed = typeof value === 'string' ? JSON.parse(value) : value;
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.shapes)) return true;
      _ideogramCanvasState.mode = parsed.mode === 'canvas' ? 'canvas' : 'text';
      _ideogramCanvasState.activeTool = parsed.activeTool === 'circle' ? 'circle' : 'rect';
      _ideogramCanvasState.selectedId = String(parsed.selectedId || '');
      _ideogramCanvasState.nextId = parseInt(parsed.nextId || 1, 10) || 1;
      _ideogramCanvasState.shapes = parsed.shapes.map(function(item) {
        return _ideogramCanvasClampShape({
          id: String(item.id || ('ig_' + (_ideogramCanvasState.nextId++))),
          kind: item.kind === 'circle' ? 'circle' : 'rect',
          elementType: item.elementType === 'text' ? 'text' : 'obj',
          x: item.x,
          y: item.y,
          w: item.w,
          h: item.h,
          text: item.text || ''
        });
      });
      _setIdeogramCanvasMode(_ideogramCanvasState.mode);
      _setIdeogramCanvasTool(_ideogramCanvasState.activeTool);
      _renderIdeogramCanvasShapes();
    } catch (e) {}
    return true;
  }

function _ideogramCanvasSummary() {
    var parts = _ideogramCanvasShapes().map(function(shape) {
      return String(shape.text || '').trim();
    }).filter(Boolean);
    return parts.slice(0, 3).join(' / ');
  }

function _ideogramCanvasWantsPhoto(base) {
    return /照片|摄影|写实|真实|实拍|photo|photograph|camera|realistic|cinematic/i.test(String(base || ''));
  }

function _ideogramCanvasWantsLayout(base) {
    return /海报|版式|排版|信息图|平面设计|设计稿|名片|卡片设计|包装设计|logo|标志|ppt|幻灯片|poster|layout|graphic design|infographic|business card|presentation|slide|flyer|packaging|brand mark/i.test(String(base || ''));
  }

function _ideogramCanvasDefaultStyle(base) {
    if (!_ideogramCanvasWantsLayout(base)) {
      return {
        aesthetics: 'one coherent realistic image, integrated scene composition, no collage, no slide layout, no split-screen, no diptych, no visible guide boxes',
        lighting: 'consistent natural lighting across the whole scene',
        photo: 'single uninterrupted continuous camera shot with consistent perspective, focus, depth, scale, and no dividing seam',
        medium: 'photograph'
      };
    }
    return {
      aesthetics: 'one coherent integrated image, strong text-image alignment, no collage, no slide layout, no split-screen, no diptych, no visible guide boxes',
      lighting: 'consistent lighting and shadows across all positioned elements',
      medium: 'digital image',
      art_style: 'unified single-frame composition with controlled placement and natural visual relationships'
    };
  }

function _ideogramCanvasSceneInstruction(base) {
    var photo = !_ideogramCanvasWantsLayout(base);
    return photo
      ? 'Compose everything as one uninterrupted continuous photograph with shared camera perspective, lighting, scale, and physical context. Fuse all object modules into one shared scene; keep text modules as precisely positioned typography only. Do not use the canvas as a grid, coordinate chart, collage, split-screen, diptych, vertical divider, gutter, seam, card, frame, or PPT-style layout.'
      : 'Compose everything as one uninterrupted unified image with shared perspective, lighting, scale, and visual context. Treat each element bbox as official Ideogram4 coordinate metadata for where the described subject should appear; the bbox is not a visible object, border, frame, panel, white card, split-screen panel, diptych, vertical divider, gutter, seam, or PPT-style separated region.';
  }

function _ideogramCanvasUseHardBbox(base) {
    return _ideogramCanvasWantsLayout(base);
  }

function _ideogramCanvasPositionHint(shape) {
    var cx = Number(shape.x || 0) + Number(shape.w || 0) / 2;
    var cy = Number(shape.y || 0) + Number(shape.h || 0) / 2;
    var vertical = cy < 34 ? 'upper' : (cy > 66 ? 'lower' : 'middle');
    var horizontal = cx < 34 ? 'left' : (cx > 66 ? 'right' : 'center');
    var quadrant = vertical === 'middle' && horizontal === 'center'
      ? 'center'
      : (vertical === 'middle' ? horizontal : (horizontal === 'center' ? vertical : vertical + '-' + horizontal));
    return quadrant + ' of the image, roughly x ' + Math.round(shape.x || 0) + '-' + Math.round((shape.x || 0) + (shape.w || 0)) + '%, y ' + Math.round(shape.y || 0) + '-' + Math.round((shape.y || 0) + (shape.h || 0)) + '%';
  }

function _ideogramCanvasSpatialSentence(shape) {
    return 'It occupies the ' + _ideogramCanvasPositionHint(shape) + ' and is composed as part of the same uninterrupted single camera view, not as a separate insert, side-by-side panel, or divided image.';
  }

function _ideogramCanvasSafetyText(text) {
    var clean = String(text || '').trim();
    if (!clean) return '';
    clean = clean
      .replace(/女高中生|女中学生|未成年女学生/gi, '22岁成年女大学生')
      .replace(/女学生/gi, '22岁成年女大学生')
      .replace(/schoolgirl|school girl|student girl/gi, 'adult 22-year-old university student')
      .replace(/超短裙/g, '短款时装裙');
    if (/学生|university student|student/i.test(clean) && !/成年|adult|22岁|22-year-old/i.test(clean)) {
      clean = '22岁成年人物，' + clean;
    }
    return clean;
  }

function _ideogramCanvasNaturalPlacement(shape) {
    var cx = Number(shape.x || 0) + Number(shape.w || 0) / 2;
    var cy = Number(shape.y || 0) + Number(shape.h || 0) / 2;
    var horizontal = cx < 38 ? 'toward the left side' : (cx > 62 ? 'toward the right side' : 'near the center');
    if (cy < 34) {
      return horizontal + ' of the open sky';
    }
    if (cy > 66) {
      return horizontal + ' of the foreground lawn';
    }
    return horizontal + ' of the middle distance';
  }

function _ideogramCanvasElementDesc(shape, text) {
    var guide = _ideogramCanvasSpatialSentence(shape) + ' ';
    guide += 'The bbox is official Ideogram4 coordinate metadata for placement inside one continuous image. Integrate it naturally into the shared environment, matching the global perspective, lighting, scale, depth, occlusion, and material relationships.';
    if (shape.kind === 'circle') {
      guide += ' The circular canvas guide means this subject should read as a soft clustered area, not as a drawn circle.';
    }
    return guide + ' Subject details: ' + _ideogramCanvasSafetyText(text);
  }

function _ideogramCanvasTextDesc(shape) {
    var guide = _ideogramCanvasSpatialSentence(shape) + ' ';
    guide += 'Render the literal text clearly as integrated typography, signage, label, poster text, or environmental lettering that belongs to the same image.';
    if (shape.kind === 'circle') {
      guide += ' The circular canvas guide means the typography may follow a soft grouped composition, without drawing an oval border.';
    } else {
      guide += ' Keep it unframed and integrated into the surrounding image.';
    }
    return guide;
  }

function _ideogramCanvasSceneNote(shape, text) {
    var note = _ideogramCanvasNaturalPlacement(shape) + ': ' + _ideogramCanvasSafetyText(text);
    if (shape.kind === 'circle') {
      note += '; compose this as a natural soft cluster within the scene, not as a drawn circular outline';
    }
    return note + '.';
  }

function _ideogramCanvasPhotoTextDesc(shape, text) {
    return 'Render the literal text "' + text + '" clearly at this precise typography placement as integrated signage, event lettering, headline lettering, or environmental text belonging to the same photograph. The bbox is an invisible placement constraint for glyphs only: only the letter strokes should be visible, and the surrounding area must remain the original scene. Do not draw any rectangle, outline, border, textbox, caption box, card, panel, white box, translucent fill, frame, or container around the text.';
  }

function _ideogramCanvasPhotoElements(shapes) {
    var textElements = [];
    var objectElements = [];
    shapes.forEach(function(shape) {
      var text = String(shape.text || '').trim();
      if (!text) return;
      if (shape.elementType === 'text') {
        textElements.push({
          type: 'text',
          bbox: _ideogramCanvasBbox(shape),
          text: text,
          desc: _ideogramCanvasPhotoTextDesc(shape, text)
        });
      } else {
        objectElements.push({
          type: 'obj',
          bbox: _ideogramCanvasBbox(shape),
          desc: _ideogramCanvasElementDesc(shape, text)
        });
      }
    });
    return objectElements.concat(textElements);
  }

function _composeIdeogramCanvasPrompt(rawPrompt, styleInfo) {
    if (_ideogramCanvasState.mode !== 'canvas' || !_ideogramCanvasShapes().length) {
      return _promptJsonForStyle(rawPrompt, styleInfo);
    }
    var base = _ideogramCanvasSafetyText(_stripExistingStylePromptBlocks(rawPrompt));
    var userJson = _parsePromptJsonObject(base);
    var promptJson = userJson && userJson.high_level_description && userJson.compositional_deconstruction
      ? userJson
      : null;
    var summary = _ideogramCanvasSummary();
    var sceneInstruction = _ideogramCanvasSceneInstruction(base);
    var useHardBbox = _ideogramCanvasUseHardBbox(base);
    var high = promptJson
      ? String(promptJson.high_level_description || '').trim()
      : (base || (useHardBbox ? 'Coherent Ideogram4 scene with positioned elements: ' : 'Coherent realistic photograph with naturally positioned elements: ') + summary);
    if (high.indexOf('hidden placement guides') === -1 && high.indexOf('隐藏') === -1) {
      high = (high + ' ' + sceneInstruction).trim();
    }
    var comp = promptJson && promptJson.compositional_deconstruction && typeof promptJson.compositional_deconstruction === 'object'
      ? promptJson.compositional_deconstruction
      : {};
    var style = promptJson && promptJson.style_description && typeof promptJson.style_description === 'object'
      ? Object.assign({}, promptJson.style_description)
      : _ideogramCanvasDefaultStyle(base);
    var shapes = _ideogramCanvasShapes();
    var elements = useHardBbox
      ? shapes.map(function(shape) {
        var text = String(shape.text || '').trim();
        if (shape.elementType === 'text') {
          return {
            type: 'text',
            bbox: _ideogramCanvasBbox(shape),
            text: text,
            desc: _ideogramCanvasTextDesc(shape)
          };
        }
        return {
          type: 'obj',
          bbox: _ideogramCanvasBbox(shape),
            desc: _ideogramCanvasElementDesc(shape, text)
        };
      })
      : _ideogramCanvasPhotoElements(shapes);
    var caption = {
      high_level_description: high,
      style_description: style,
      compositional_deconstruction: {
        background: String(comp.background || base || 'One continuous environment connecting all positioned elements naturally, with no separated panels, inset crops, white cards, picture-in-picture windows, vertical dividers, split-screen seams, or visible layout boxes.').trim(),
        elements: elements
      }
    };
    return JSON.stringify(styleInfo && styleInfo.promptJson ? { prompt: caption, style: styleInfo.promptJson } : caption);
  }

function _workflowSizeLimits(fields) {
    var workflow = String(A.currentWF || '');
    if (/bernini/i.test(workflow) || _hasFieldClass(fields, /^BerniniConditioning$/)) {
      return { name: 'bernini', maxSide: 848, maxPixels: null, multiple: 16, minSide: 256, inputMax: 1280, basePresets: DEFAULT_RATIO_BASE_PRESETS };
    }
    if (/scail|wan/i.test(workflow) || _hasFieldClass(fields, /Wan.*(?:ToVideo|Video)|SCAIL/i)) {
      return { name: 'wan-video', maxSide: 896, maxPixels: WAN_VIDEO_MAX_PIXELS, multiple: 32, minSide: 256, inputMax: 1536, presets: WAN_VIDEO_RATIO_PRESETS };
    }
    var hasLtxVideoLatent = _hasFieldClass(fields, /EmptyLTXVLatentVideo|LTXV/i);
    if (/ltx|sulphur/i.test(workflow) || hasLtxVideoLatent) {
      return { name: 'ltx-video', maxSide: 1280, maxPixels: null, multiple: 32, minSide: 192, minWidth: 256, minHeight: 192, inputMax: 1280, basePresets: DEFAULT_RATIO_BASE_PRESETS };
    }
    var hasFlux2Scheduler = _hasFieldClass(fields, /^Flux2Scheduler$/);
    if (/flux[\s_.-]*2/i.test(workflow) || hasFlux2Scheduler) {
      return { name: 'flux2', maxSide: null, maxPixels: FLUX2_MAX_PIXELS, multiple: 16, minSide: 64, inputMax: 4096, basePresets: FLUX2_RATIO_BASE_PRESETS };
    }
    if (/ideogram/i.test(workflow) || _hasFieldClass(fields, /^Ideogram4Scheduler$/)) {
      return { name: 'ideogram4', maxSide: 2048, maxPixels: null, multiple: 16, minSide: 256, inputMax: 2048, basePresets: DEFAULT_RATIO_BASE_PRESETS };
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

function _roundToMultiple(value, multiple, mode) {
    multiple = Math.max(1, parseInt(multiple || 1, 10));
    value = Number(value);
    if (!Number.isFinite(value)) return multiple;
    var scaled = value / multiple;
    if (mode === 'floor') return Math.max(multiple, Math.floor(scaled) * multiple);
    if (mode === 'ceil') return Math.max(multiple, Math.ceil(scaled) * multiple);
    return Math.max(multiple, Math.round(scaled) * multiple);
  }

function _sizeLimitBounds(limits) {
    limits = limits || DEFAULT_SIZE_LIMITS;
    var multiple = Math.max(1, parseInt(limits.multiple || 64, 10));
    var minSide = Math.max(multiple, parseInt(limits.minSide || multiple, 10));
    var minWidth = _roundToMultiple(Math.max(multiple, parseInt(limits.minWidth || minSide, 10)), multiple, 'ceil');
    var minHeight = _roundToMultiple(Math.max(multiple, parseInt(limits.minHeight || minSide, 10)), multiple, 'ceil');
    var inputMax = parseInt(limits.inputMax || limits.maxSide || 2048, 10) || 2048;
    var maxSide = limits.maxSide ? Math.min(inputMax, parseInt(limits.maxSide, 10) || inputMax) : inputMax;
    var maxWidth = _roundToMultiple(Math.max(minWidth, maxSide), multiple, 'floor');
    var maxHeight = _roundToMultiple(Math.max(minHeight, maxSide), multiple, 'floor');
    return {
      multiple: multiple,
      minWidth: minWidth,
      minHeight: minHeight,
      maxWidth: Math.max(minWidth, maxWidth),
      maxHeight: Math.max(minHeight, maxHeight)
    };
  }

function _readSizePresetRatio(btn) {
    if (!btn) return null;
    var w = parseInt(btn.dataset.ratioW || btn.dataset.w || '', 10);
    var h = parseInt(btn.dataset.ratioH || btn.dataset.h || '', 10);
    if (!w || !h) return null;
    return { width: w, height: h };
  }

function _activeSizeRatio() {
    var section = $('#sizeSection');
    var w = parseInt((section && section.dataset.sizeRatioW) || '', 10);
    var h = parseInt((section && section.dataset.sizeRatioH) || '', 10);
    if (w && h) return { width: w, height: h };
    return null;
  }

function _sizePresetButtonForRatio(ratio) {
    if (!ratio) return null;
    var targetW = String(ratio.width || '');
    var targetH = String(ratio.height || '');
    var match = null;
    _sizePresetButtons().forEach(function(btn) {
      if (String(btn.dataset.ratioW || btn.dataset.w || '') === targetW && String(btn.dataset.ratioH || btn.dataset.h || '') === targetH) match = btn;
    });
    return match;
  }

function _ratioHeightFromWidth(width, ratio, multiple) {
    return _roundToMultiple(width * ratio.height / Math.max(1, ratio.width), multiple, 'round');
  }

function _ratioWidthFromHeight(height, ratio, multiple) {
    return _roundToMultiple(height * ratio.width / Math.max(1, ratio.height), multiple, 'round');
  }

function _fitSizeForRatio(width, height, changed, ratio, limits) {
    limits = limits || DEFAULT_SIZE_LIMITS;
    ratio = ratio || { width: 1, height: 1 };
    changed = changed === 'height' ? 'height' : 'width';
    var bounds = _sizeLimitBounds(limits);
    var multiple = bounds.multiple;
    var w = Number(width);
    var h = Number(height);
    if (!Number.isFinite(w) || w <= 0) w = bounds.minWidth;
    if (!Number.isFinite(h) || h <= 0) h = bounds.minHeight;

    if (changed === 'height') {
      h = Math.min(bounds.maxHeight, Math.max(bounds.minHeight, _roundToMultiple(h, multiple, 'round')));
      w = _ratioWidthFromHeight(h, ratio, multiple);
    } else {
      w = Math.min(bounds.maxWidth, Math.max(bounds.minWidth, _roundToMultiple(w, multiple, 'round')));
      h = _ratioHeightFromWidth(w, ratio, multiple);
    }

    for (var i = 0; i < 8; i++) {
      var prev = w + 'x' + h;
      if (w < bounds.minWidth) { w = bounds.minWidth; h = _ratioHeightFromWidth(w, ratio, multiple); }
      if (h < bounds.minHeight) { h = bounds.minHeight; w = _ratioWidthFromHeight(h, ratio, multiple); }
      if (w > bounds.maxWidth) { w = bounds.maxWidth; h = _ratioHeightFromWidth(w, ratio, multiple); }
      if (h > bounds.maxHeight) { h = bounds.maxHeight; w = _ratioWidthFromHeight(h, ratio, multiple); }
      if (limits.maxPixels && w * h > limits.maxPixels) {
        var scale = Math.sqrt(Number(limits.maxPixels) / Math.max(1, w * h));
        if (changed === 'height') {
          h = Math.max(bounds.minHeight, _roundToMultiple(h * scale, multiple, 'floor'));
          w = _ratioWidthFromHeight(h, ratio, multiple);
        } else {
          w = Math.max(bounds.minWidth, _roundToMultiple(w * scale, multiple, 'floor'));
          h = _ratioHeightFromWidth(w, ratio, multiple);
        }
      }
      if (prev === w + 'x' + h) break;
    }

    while (limits.maxPixels && w * h > limits.maxPixels) {
      if (changed === 'height' && h > bounds.minHeight) {
        h = Math.max(bounds.minHeight, h - multiple);
        w = _ratioWidthFromHeight(h, ratio, multiple);
      } else if (w > bounds.minWidth) {
        w = Math.max(bounds.minWidth, w - multiple);
        h = _ratioHeightFromWidth(w, ratio, multiple);
      } else {
        break;
      }
    }
    return [w, h];
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

function _sizePresetLabel(preset) {
    if (!preset) return '';
    return String(preset[2] || (preset[0] + ':' + preset[1]));
  }

function _ratioPartsForPreset(preset) {
    var label = _sizePresetLabel(preset);
    var m = label.match(/^\s*(\d+)\s*:\s*(\d+)\s*$/);
    if (m) {
      var rw = parseInt(m[1], 10);
      var rh = parseInt(m[2], 10);
      if (rw && rh) return { width: rw, height: rh };
    }
    return {
      width: parseInt((preset && preset[0]) || 1, 10) || 1,
      height: parseInt((preset && preset[1]) || 1, 10) || 1
    };
  }

function _closestSizePresetForAspect(width, height, limits) {
    width = parseInt(width, 10) || 0;
    height = parseInt(height, 10) || 0;
    if (!width || !height) return null;
    var target = width / height;
    var best = null;
    var bestDiff = Infinity;
    _ratioPresetsForLimits(limits || _workflowSizeLimits()).forEach(function(p) {
      var pw = parseInt(p[0], 10) || 0;
      var ph = parseInt(p[1], 10) || 0;
      if (!pw || !ph) return;
      var diff = Math.abs(Math.log((pw / ph) / target));
      if (diff < bestDiff) {
        bestDiff = diff;
        best = p;
      }
    });
    return best;
  }

function _largestSizeForSourceAspect(width, height, limits) {
    limits = limits || _workflowSizeLimits();
    width = parseInt(width, 10) || 0;
    height = parseInt(height, 10) || 0;
    if (!width || !height) return null;
    var multiple = Math.max(1, parseInt(limits.multiple || 32, 10));
    var maxSide = parseInt(limits.maxSide || 0, 10) || Math.max(width, height);
    var targetW, targetH;
    if (width >= height) {
      targetW = maxSide;
      targetH = Math.max(multiple, Math.round((maxSide * height / width) / multiple) * multiple);
    } else {
      targetH = maxSide;
      targetW = Math.max(multiple, Math.round((maxSide * width / height) / multiple) * multiple);
    }
    return _limitDimensions(targetW, targetH, limits);
  }

function _applyBestSizeForAspect(width, height) {
    var wi = $('#widthInput'), hi = $('#heightInput');
    if (!wi || !hi) return false;
    var limits = _workflowSizeLimits();
    var size = limits.name === 'wan-video'
      ? _largestSizeForSourceAspect(width, height, limits)
      : _closestSizePresetForAspect(width, height, limits);
    if (!size) return false;
    wi.value = size[0];
    hi.value = size[1];
    _applyCurrentSizeLimit();
    var matched = null;
    _sizePresetButtons().forEach(function(btn) {
      if (String(btn.dataset.w || '') === String(size[0]) && String(btn.dataset.h || '') === String(size[1])) {
        matched = btn;
      }
    });
    if (matched) _setActiveSizePreset(matched);
    return true;
  }

function _numericFieldControlForMeta(f) {
    var key = _fieldKeyForMeta(f);
    if (!key) return null;
    return document.querySelector('#quickFormFields [data-key="' + key + '"], #advFields [data-key="' + key + '"]');
  }

function _isVideoFpsLikeFieldMeta(f) {
    f = f || {};
    var label = String(f.label || '');
    var field = String(f.field || '');
    var cls = String(f.class_type || '');
    var title = String(f.node_title || '');
    var haystack = (label + ' ' + field + ' ' + cls + ' ' + title).toLowerCase();
    return field === 'fps' ||
      field === 'frame_rate' ||
      field === 'force_rate' ||
      /fps|帧率|frame[_ -]?rate|force[_ -]?rate/.test(haystack);
  }

function _videoFrameFieldMeta(kind) {
    var fields = A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      var label = String(f.label || '');
      var field = String(f.field || '');
      var cls = String(f.class_type || '');
      var title = String(f.node_title || '');
      var haystack = (label + ' ' + field + ' ' + cls + ' ' + title).toLowerCase();
      if (kind === 'generate' && !_isVideoFpsLikeFieldMeta(f) && (
        /生成帧数|生成.*帧|输出.*帧/.test(label) ||
        (field === 'length' && /video|tovideo|latentvideo|scail|wan/i.test(cls + ' ' + title))
      )) return f;
      if (kind === 'read' && (field === 'frame_load_cap' || /读取帧数|读入帧数|frame[_ -]?load[_ -]?cap/.test(haystack))) return f;
      if (kind === 'duration' && (
        field === '__output_duration_sec' ||
        /输出时长|视频时长|时长.*秒|duration|seconds/.test(haystack)
      )) return f;
    }
    return null;
  }

function _isWanScailReferenceVideoWorkflow(fieldsMeta) {
    var fields = fieldsMeta || A._wfFieldMeta || [];
    var workflow = String(A.currentWF || '');
    var hasVideo = false;
    var hasWanScail = /scail|wan/i.test(workflow);
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      var cls = String(f.class_type || '');
      var title = String(f.node_title || '');
      var field = String(f.field || '');
      if (_isReferenceVideoField(f)) hasVideo = true;
      if (/Wan.*(?:ToVideo|Video)|SCAIL/i.test(cls + ' ' + title) || field === 'force_rate') hasWanScail = true;
    }
    return hasVideo && hasWanScail;
  }

function _wanScailTimingFieldMeta(kind, fieldsMeta) {
    var fields = fieldsMeta || A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      var label = String(f.label || '');
      var field = String(f.field || '');
      var cls = String(f.class_type || '');
      var title = String(f.node_title || '');
      var haystack = (label + ' ' + field + ' ' + cls + ' ' + title).toLowerCase();
      if (kind === 'output_fps') {
        if (field === 'fps') return f;
        if (/输出帧率|output.*fps|create\s*video/.test(label + ' ' + title)) return f;
      }
      if (kind === 'force_rate') {
        if (field === 'force_rate') return f;
        if (/重采样.*fps|force[_ -]?rate|load.*fps/.test(haystack)) return f;
      }
    }
    return null;
  }

function _numberFieldValue(fields, meta) {
    var key = _fieldKeyForMeta(meta);
    if (!key) return 0;
    var raw = fields && Object.prototype.hasOwnProperty.call(fields, key) ? fields[key] : null;
    if (raw === null || raw === undefined || raw === '') {
      raw = _currentFieldValueForMeta(meta);
    }
    var value = parseFloat(raw);
    return isFinite(value) ? value : 0;
  }

function _writeNumberField(fields, snapshot, meta, value) {
    var key = _fieldKeyForMeta(meta);
    if (!key || !isFinite(value)) return;
    fields[key] = value;
    if (snapshot && snapshot.adv) snapshot.adv[key] = value;
    var control = _numericFieldControlForMeta(meta);
    if (control) _setNumberControlValue(control, value);
  }

function _wanScailDefaultForceRate() {
    return 24;
  }

var _wanScailTimingSyncing = false;

function _roundWanScailFps(value) {
    var fps = parseFloat(value);
    if (!isFinite(fps) || fps <= 0) fps = _wanScailDefaultForceRate();
    fps = Math.max(1, Math.min(60, fps));
    fps = Math.round(fps * 1000) / 1000;
    return Math.abs(fps - Math.round(fps)) < 0.0001 ? Math.round(fps) : fps;
  }

function _wanScailVideoDuration(meta) {
    var source = meta || _getRefVideoMetadata();
    var duration = parseFloat((source && (source.duration || source.duration_seconds)) || 0) || 0;
    return duration > 0 ? duration : 0;
  }

function _wanScailVideoFps(meta) {
    var source = meta || _getRefVideoMetadata();
    var fps = parseFloat((source && (source.fps || source.frame_rate)) || 0) || 0;
    return fps > 0 ? _roundWanScailFps(fps) : 0;
  }

function _fieldNumberLimit(meta, name, fallback) {
    if (!meta) return fallback;
    var key = _fieldKeyForMeta(meta);
    var control = key ? _numericFieldControlForMeta(meta) : null;
    var raw = control ? control.getAttribute(name) : meta[name];
    var value = parseFloat(raw);
    return isFinite(value) ? value : fallback;
  }

function _wanScailFrameLimit(readMeta, genMeta) {
    var value = _fieldNumberLimit(readMeta, 'max', 0);
    if (!(value > 0)) value = _fieldNumberLimit(genMeta, 'max', 0);
    return value > 0 ? value : 501;
  }

function _setNumberControlMax(meta, value) {
    var control = _numericFieldControlForMeta(meta);
    if (!control || !(value > 0)) return;
    control.setAttribute('max', String(Math.round(value * 1000) / 1000));
  }

function _clampWanScailDuration(value, sourceDuration, fps, frameLimit) {
    var duration = parseFloat(value);
    var maxDuration = 0;
    if (sourceDuration > 0) maxDuration = sourceDuration;
    if (frameLimit > 0 && fps > 0) {
      var frameDuration = frameLimit / fps;
      maxDuration = maxDuration > 0 ? Math.min(maxDuration, frameDuration) : frameDuration;
    }
    if (!isFinite(duration) || duration <= 0) duration = maxDuration || 0;
    if (maxDuration > 0) duration = Math.min(duration, maxDuration);
    duration = Math.max(0.1, duration || 0.1);
    return Math.round(duration * 1000) / 1000;
  }

function _wanScailForceRateValue(fields, forceRateMeta) {
    var forceRate = forceRateMeta ? _numberFieldValue(fields || {}, forceRateMeta) : 0;
    if (!isFinite(forceRate) || forceRate <= 0) forceRate = _wanScailDefaultForceRate();
    return _roundWanScailFps(forceRate);
  }

function _autoFitWanScailVideoTimingControls(meta, fieldsMeta) {
    fieldsMeta = fieldsMeta || A._wfFieldMeta || [];
    var forceRateMeta = _wanScailTimingFieldMeta('force_rate', fieldsMeta);
    var outputFpsMeta = _wanScailTimingFieldMeta('output_fps', fieldsMeta);
    var genMeta = _videoFrameFieldMeta('generate');
    var readMeta = _videoFrameFieldMeta('read');
    var durationMeta = _videoFrameFieldMeta('duration');
    var sourceDuration = _wanScailVideoDuration(meta);
    var outputFps = _wanScailForceRateValue({}, outputFpsMeta || forceRateMeta);
    var frameLimit = _wanScailFrameLimit(readMeta, genMeta);
    var duration = _clampWanScailDuration(sourceDuration, sourceDuration, outputFps, frameLimit);
    _setNumberControlMax(durationMeta, _clampWanScailDuration(sourceDuration, sourceDuration, outputFps, frameLimit));

    var targetFrames = duration > 0 ? Math.max(1, Math.floor(duration * outputFps + 0.000001)) : _videoFrameTotalFromMeta(meta);
    targetFrames = Math.max(1, Math.min(frameLimit, targetFrames || 1));

    if (durationMeta) _writeNumberField({}, { adv: {} }, durationMeta, duration);
    if (forceRateMeta) _writeNumberField({}, { adv: {} }, forceRateMeta, outputFps);

    if (genMeta && targetFrames > 0) _writeNumberField({}, { adv: {} }, genMeta, targetFrames);
    if (readMeta && _fieldKeyForMeta(readMeta) !== _fieldKeyForMeta(genMeta) && targetFrames > 0) {
      _writeNumberField({}, { adv: {} }, readMeta, targetFrames);
    }

    if (outputFpsMeta) _writeNumberField({}, { adv: {} }, outputFpsMeta, _roundWanScailFps(outputFps));
    return !!(durationMeta || forceRateMeta || outputFpsMeta || genMeta || readMeta);
  }

function _syncWanScailVideoTiming(fields, snapshot, fieldsMeta, opts) {
    fieldsMeta = fieldsMeta || A._wfFieldMeta || [];
    if (!_isWanScailReferenceVideoWorkflow(fieldsMeta)) return null;
    if (_wanScailTimingSyncing) return null;
    _wanScailTimingSyncing = true;
    try {
    fields = fields || {};
    snapshot = snapshot || {};
    opts = opts || {};
    var outputFpsMeta = _wanScailTimingFieldMeta('output_fps', fieldsMeta);
    var forceRateMeta = _wanScailTimingFieldMeta('force_rate', fieldsMeta);
    var durationMeta = _videoFrameFieldMeta('duration');
    var changed = {};
    var outputFps = _wanScailForceRateValue(fields, outputFpsMeta || forceRateMeta);
    var genMeta = _videoFrameFieldMeta('generate');
    var readMeta = _videoFrameFieldMeta('read');
    var genKey = _fieldKeyForMeta(genMeta);
    var readKey = _fieldKeyForMeta(readMeta);
    var durationKey = _fieldKeyForMeta(durationMeta);
    var sourceDuration = _wanScailVideoDuration();
    var frameLimit = _wanScailFrameLimit(readMeta, genMeta);
    var requestedDuration = 0;
    if (opts.preferFrameCount && readMeta && outputFps > 0 && fields && Object.prototype.hasOwnProperty.call(fields, readKey)) {
      requestedDuration = Math.round((_numberFieldValue(fields, readMeta) / outputFps) * 1000) / 1000;
    } else if (durationMeta && durationKey && fields && Object.prototype.hasOwnProperty.call(fields, durationKey)) {
      requestedDuration = parseFloat(fields[durationKey]) || 0;
    } else if (durationMeta) {
      requestedDuration = _numberFieldValue(fields, durationMeta);
    }
    if (!(requestedDuration > 0) && readMeta && outputFps > 0) {
      requestedDuration = Math.round((_numberFieldValue(fields, readMeta) / outputFps) * 1000) / 1000;
    }
    var duration = _clampWanScailDuration(requestedDuration || sourceDuration, sourceDuration, outputFps, frameLimit);
    _setNumberControlMax(durationMeta, _clampWanScailDuration(sourceDuration || duration, sourceDuration, outputFps, frameLimit));
    var frames = Math.max(1, Math.min(frameLimit, Math.floor(duration * outputFps + 0.000001)));

    if (durationMeta) {
      var currentDuration = _numberFieldValue(fields, durationMeta);
      if (Math.abs(currentDuration - duration) > 0.001) {
        _writeNumberField(fields, snapshot, durationMeta, duration);
        changed.duration = duration;
      } else {
        var durationKey = _fieldKeyForMeta(durationMeta);
        if (durationKey) fields[durationKey] = duration;
      }
    }
    if (forceRateMeta) {
      var currentForceRate = _numberFieldValue(fields, forceRateMeta);
      if (Math.abs(currentForceRate - outputFps) > 0.001) {
        _writeNumberField(fields, snapshot, forceRateMeta, outputFps);
        changed.force_rate = outputFps;
      }
    }
    if (readMeta && frames > 0) {
      var readFrames = _numberFieldValue(fields, readMeta);
      if (Math.round(readFrames) !== frames) {
        _writeNumberField(fields, snapshot, readMeta, frames);
        changed.frame_load_cap = frames;
      }
    }
    if (genMeta && genKey !== readKey && frames > 0) {
      var genFrames = _numberFieldValue(fields, genMeta);
      if (Math.round(genFrames) !== frames) {
        _writeNumberField(fields, snapshot, genMeta, frames);
        changed.generate_frames = frames;
      }
    }
    if (outputFpsMeta) {
      outputFps = _roundWanScailFps(outputFps);
      var currentOutputFps = _numberFieldValue(fields, outputFpsMeta);
      if (Math.abs(currentOutputFps - outputFps) > 0.001) {
        _writeNumberField(fields, snapshot, outputFpsMeta, outputFps);
        changed.output_fps = outputFps;
      }
    }
    return Object.keys(changed).length ? changed : null;
    } finally {
      _wanScailTimingSyncing = false;
    }
  }

function _bindWanScailVideoTimingSync(fieldsMeta) {
    fieldsMeta = fieldsMeta || A._wfFieldMeta || [];
    if (!_isWanScailReferenceVideoWorkflow(fieldsMeta)) return;
    var forceRateMeta = _wanScailTimingFieldMeta('force_rate', fieldsMeta);
    var outputFpsMeta = _wanScailTimingFieldMeta('output_fps', fieldsMeta);
    var durationMeta = _videoFrameFieldMeta('duration');
    var genMeta = _videoFrameFieldMeta('generate');
    var readMeta = _videoFrameFieldMeta('read');
    [forceRateMeta, outputFpsMeta, durationMeta, genMeta, readMeta].forEach(function(meta) {
      var control = _numericFieldControlForMeta(meta);
      if (!control || control.getAttribute('data-wan-scail-timing-bound') === '1') return;
      control.setAttribute('data-wan-scail-timing-bound', '1');
      control.addEventListener('input', function() {
        _syncWanScailVideoTiming({}, { adv: {} }, fieldsMeta, { sourceKey: _fieldKeyForMeta(meta) });
      });
      control.addEventListener('change', function() {
        _syncWanScailVideoTiming({}, { adv: {} }, fieldsMeta, { sourceKey: _fieldKeyForMeta(meta) });
      });
    });
    _syncWanScailVideoTiming({}, { adv: {} }, fieldsMeta);
  }

function _videoFrameTotalFromMeta(meta) {
    meta = meta || {};
    var frames = parseInt(meta.frame_count || meta.frames || meta.nb_frames || 0, 10) || 0;
    var duration = parseFloat(meta.duration || meta.duration_seconds || 0) || 0;
    var fps = parseFloat(meta.fps || meta.frame_rate || 0) || 0;
    if (!frames && duration > 0 && fps > 0) frames = Math.max(1, Math.round(duration * fps));
    return frames;
  }

function _snapVideoFrameCount(value, control) {
    value = Math.max(1, parseInt(value, 10) || 1);
    var min = parseInt((control && control.getAttribute('min')) || 1, 10) || 1;
    var max = parseInt((control && control.getAttribute('max')) || value, 10) || value;
    var step = parseInt((control && control.getAttribute('step')) || 1, 10) || 1;
    value = Math.max(min, Math.min(max, value));
    if (step > 1) {
      var base = step === 4 ? 1 : min;
      value = base + Math.round((value - base) / step) * step;
      if (value < min) value = min;
      if (value > max) value = max;
    }
    return Math.max(min, Math.min(max, value));
  }

function _setNumberControlValue(control, value) {
    if (!control) return;
    control.value = String(value);
    control.dispatchEvent(new Event('input', { bubbles: true }));
    control.dispatchEvent(new Event('change', { bubbles: true }));
  }

function _autoFitVideoFrameControls(meta) {
    if (_isWanScailReferenceVideoWorkflow()) {
      return _autoFitWanScailVideoTimingControls(meta, A._wfFieldMeta || []);
    }
    var totalFrames = _videoFrameTotalFromMeta(meta);
    if (!totalFrames) return false;
    var genMeta = _videoFrameFieldMeta('generate');
    var readMeta = _videoFrameFieldMeta('read');
    var genControl = genMeta ? _numericFieldControlForMeta(genMeta) : null;
    var readControl = readMeta ? _numericFieldControlForMeta(readMeta) : null;
    var target = 0;
    if (genControl) {
      target = _snapVideoFrameCount(totalFrames, genControl);
      _setNumberControlValue(genControl, target);
    }
    if (readControl) {
      var readTarget = target || _snapVideoFrameCount(totalFrames, readControl);
      _setNumberControlValue(readControl, readTarget);
    }
    return !!(genControl || readControl);
  }

function _sizePresetButtons() {
    var btns = $$('[data-size-preset]');
    return btns && btns.length ? btns : $$('.ratio-btn');
  }

function _setActiveSizePreset(activeBtn) {
    var section = $('#sizeSection');
    var ratio = _readSizePresetRatio(activeBtn);
    if (section) {
      if (ratio) {
        section.dataset.sizeRatioW = String(ratio.width);
        section.dataset.sizeRatioH = String(ratio.height);
      } else {
        delete section.dataset.sizeRatioW;
        delete section.dataset.sizeRatioH;
      }
    }
    _sizePresetButtons().forEach(function(btn) {
      var active = btn === activeBtn;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

function _applyCurrentSizeLimit(changed) {
    var wi = $('#widthInput'), hi = $('#heightInput');
    if (!wi || !hi) return;
    var limits = _workflowSizeLimits();
    var ratio = _activeSizeRatio();
    var size = ratio
      ? _fitSizeForRatio(wi.value, hi.value, changed, ratio, limits)
      : _limitDimensions(wi.value, hi.value, limits);
    wi.value = size[0];
    hi.value = size[1];
    if (ratio) {
      var active = _sizePresetButtonForRatio(ratio);
      if (active) _setActiveSizePreset(active);
    } else {
      highlightRatio(size[0], size[1]);
    }
    _syncIdeogramCanvasAspect();
  }

function _syncSizeInputForRatio(changed, commit) {
    var wi = $('#widthInput'), hi = $('#heightInput');
    if (!wi || !hi) return;
    var ratio = _activeSizeRatio();
    var limits = _workflowSizeLimits();
    if (!ratio) {
      var w = parseInt(wi.value, 10) || 0;
      var h = parseInt(hi.value, 10) || 0;
      highlightRatio(w, h);
      _syncIdeogramCanvasAspect();
      return;
    }
    var bounds = _sizeLimitBounds(limits);
    var sourceValue = changed === 'height' ? Number(hi.value) : Number(wi.value);
    var sourceMin = changed === 'height' ? bounds.minHeight : bounds.minWidth;
    if (!commit && (!Number.isFinite(sourceValue) || sourceValue < sourceMin)) {
      _syncIdeogramCanvasAspect();
      return;
    }
    var size = _fitSizeForRatio(wi.value, hi.value, changed, ratio, limits);
    if (commit || sourceValue >= sourceMin) {
      wi.value = size[0];
      hi.value = size[1];
    } else if (changed === 'height') {
      wi.value = size[0];
    } else {
      hi.value = size[1];
    }
    var active = _sizePresetButtonForRatio(ratio);
    if (active) _setActiveSizePreset(active);
    _syncIdeogramCanvasAspect();
  }

function initRatioGrid() {
    // Ratio buttons are created dynamically by renderQuickForm - guard
    var btns = _sizePresetButtons();
    if (!btns || !btns.length) return;
    var initialActive = null;
    btns.forEach(function(b) {
      if (!initialActive && b.classList.contains('active')) initialActive = b;
    });
    if (initialActive) _setActiveSizePreset(initialActive);
    btns.forEach(function(b) {
      b.addEventListener('click', function() {
        _setActiveSizePreset(b);
        var wi = $('#widthInput'), hi = $('#heightInput');
        if (wi) wi.value = b.dataset.w;
        if (hi) hi.value = b.dataset.h;
        _applyCurrentSizeLimit('width');
      });
    });
    ['#widthInput', '#heightInput'].forEach(function(sel) {
      var el = $(sel);
      if (el) {
        var changed = sel === '#heightInput' ? 'height' : 'width';
        el.addEventListener('input', function() {
          _syncSizeInputForRatio(changed, false);
        });
        el.addEventListener('change', function() {
          _syncSizeInputForRatio(changed, true);
        });
        el.addEventListener('blur', function() {
          _syncSizeInputForRatio(changed, true);
        });
      }
    });
  }

function highlightRatio(w, h) {
    var target = w / h;
    var best = null, bestDiff = Infinity;
    _sizePresetButtons().forEach((b) => {
      var bw = parseInt(b.dataset.w), bh = parseInt(b.dataset.h);
      var ratio = bw / bh;
      var diff = Math.abs(ratio - target);
      if (diff < bestDiff) { bestDiff = diff; best = b; }
    });
    _sizePresetButtons().forEach((b) => {
      var active = bestDiff < 0.01 && b === best;
      b.classList.toggle('active', active);
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
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

function _isReferenceVideoField(f) {
    if (!f) return false;
    var cls = String(f.class_type || '');
    var field = String(f.field || '');
    if (f.type === 'video') return true;
    return (cls === 'LoadVideo' && field === 'file') || (cls === 'VHS_LoadVideo' && field === 'video');
  }

function _isReferenceAudioField(f) {
    if (!f) return false;
    var cls = String(f.class_type || '');
    var field = String(f.field || '');
    if (f.type === 'audio') return true;
    return cls === 'LoadAudio' && field === 'audio';
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

function _isBerniniModeField(f) {
    if (!f) return false;
    return f.type === 'bernini_mode' || String(f.field || '') === '__bernini_mode' || _fieldKeyForMeta(f).endsWith('::__bernini_mode');
  }

function _isBerniniRefsField(f) {
    if (!f) return false;
    return f.type === 'bernini_refs' || String(f.field || '') === '__bernini_refs' || _fieldKeyForMeta(f).endsWith('::__bernini_refs');
  }

function _isImageReferenceModeField(f) {
    if (!f) return false;
    return f.type === 'image_reference_mode' || String(f.field || '') === '__image_reference_mode' || _fieldKeyForMeta(f).endsWith('::__image_reference_mode');
  }

function _isMultiImageRefsField(f) {
    if (!f) return false;
    return f.type === 'multi_image_refs' || String(f.field || '') === '__multi_reference_images' || _fieldKeyForMeta(f).endsWith('::__multi_reference_images');
  }

function _isBerniniFramesField(f) {
    if (!f) return false;
    return f.type === 'bernini_frames' || String(f.field || '') === '__bernini_frames' || _fieldKeyForMeta(f).endsWith('::__bernini_frames');
  }

function _isBerniniFpsField(f) {
    if (!f) return false;
    return f.type === 'bernini_fps' || String(f.field || '') === '__bernini_fps' || _fieldKeyForMeta(f).endsWith('::__bernini_fps');
  }

function _currentBerniniMode() {
    var input = document.querySelector('[data-type="bernini_mode"][data-key]');
    return String((input && input.value) || 't2i').trim().toLowerCase() || 't2i';
  }

function _currentImageReferenceMode() {
    var input = document.querySelector('[data-type="image_reference_mode"][data-key]');
    var value = String((input && input.value) || 'single').trim().toLowerCase();
    return value === 'multi' ? 'multi' : 'single';
  }

function _imageReferenceModeNeedsMultiRefs(mode) {
    return String(mode || '').toLowerCase() === 'multi';
  }

function _berniniModeOptions() {
    return [
      { value: 't2i', code: 'T2I', label: '文生图', desc: '用提示词生成图片' },
      { value: 'i2i', code: 'I2I', label: '图生图', desc: '用提示词和 1 张源图生成/重绘图片' },
      { value: 't2v', code: 'T2V', label: '文生视频', desc: '用提示词生成视频' },
      { value: 'v2v', code: 'V2V', label: '视频重绘', desc: '用提示词和源视频生成视频' },
      { value: 'i2v', code: 'I2V', label: '图生视频', desc: '用提示词和 1 张参考图生成视频' },
      { value: 'r2v', code: 'R2V', label: '多参考图生视频', desc: '用提示词和多张参考图生成视频' },
      { value: 'rv2v', code: 'RV2V', label: '参考图视频编辑', desc: '用源视频、多张参考图和提示词生成视频' }
    ];
  }

function _berniniModeInfo(mode) {
    mode = String(mode || 't2i').toLowerCase();
    var modes = _berniniModeOptions();
    for (var i = 0; i < modes.length; i++) {
      if (modes[i].value === mode) return modes[i];
    }
    return modes[0];
  }

function _berniniModeOptionLabel(info) {
    return info.code + '（' + info.label + '）' + info.desc;
  }

function _berniniModeNeedsRefs(mode) {
    return ['i2i', 'i2v', 'r2v', 'rv2v'].indexOf(String(mode || '').toLowerCase()) >= 0;
  }

function _berniniModeNeedsVideo(mode) {
    return ['v2v', 'rv2v'].indexOf(String(mode || '').toLowerCase()) >= 0;
  }

function _isBerniniWorkflowFields(fieldsMeta) {
    var workflow = String(A.currentWF || A._wfFieldWorkflow || '');
    if (/bernini/i.test(workflow)) return true;
    var fields = fieldsMeta || A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if (_isBerniniModeField(f) || _isBerniniRefsField(f)) return true;
      var cls = String(f.class_type || '');
      if (cls === 'BerniniConditioning' || cls.indexOf('RHBerniniFull') === 0) return true;
    }
    return false;
  }

function _isSeedVR2VideoUpscaleWorkflow(fieldsMeta) {
    var workflow = String(A.currentWF || '');
    if (/seedvr2.*video.*upscale|seedvr2.*视频.*放大/i.test(workflow)) return true;
    var fields = fieldsMeta || A._wfFieldMeta || [];
    var hasVideo = false, hasSeedVR2 = false;
    for (var i = 0; i < fields.length; i++) {
      var cls = String((fields[i] || {}).class_type || '');
      if (_isReferenceVideoField(fields[i])) hasVideo = true;
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
    var duration = parseFloat(
      (valueInput && valueInput.getAttribute('data-video-duration')) ||
      (preview && (preview.getAttribute('data-video-duration') || preview.duration)) ||
      0
    ) || 0;
    var fps = parseFloat(
      (valueInput && valueInput.getAttribute('data-video-fps')) ||
      (preview && preview.getAttribute('data-video-fps')) ||
      0
    ) || 0;
    var frameCount = parseInt(
      (valueInput && valueInput.getAttribute('data-video-frame-count')) ||
      (preview && preview.getAttribute('data-video-frame-count')) ||
      0,
      10
    ) || 0;
    return { width: width, height: height, duration: duration, fps: fps, frame_count: frameCount };
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
    var userPrompt = _promptTextValue(values.__user_prompt);
    if (userPrompt) return userPrompt;
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
        if (key.indexOf('__') === 0) continue;
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

function _isCanvasDimensionField(f, dim) {
    var cls = String((f && f.class_type) || '');
    if (f && f.role === dim) return true;
    return !!(f && f.field === dim && (
      cls.indexOf('LatentImage') >= 0 ||
      cls.indexOf('LatentVideo') >= 0 ||
      /Wan.*(?:ToVideo|Video)|SCAIL/i.test(cls)
    ));
  }

function _isLatentDimensionField(f, dim) {
    return _isCanvasDimensionField(f, dim);
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

function _isQwenAngleNeutral(horizontal, vertical, zoom, roll, neutralZoom) {
    var signedYaw = _qwenSignedYaw(horizontal);
    var v = parseFloat(vertical);
    if (!Number.isFinite(v)) v = 0;
    var neutralZ = parseFloat(neutralZoom);
    if (!Number.isFinite(neutralZ)) neutralZ = 5;
    var z = parseFloat(zoom);
    if (!Number.isFinite(z)) z = neutralZ;
    var r = parseFloat(roll);
    if (!Number.isFinite(r)) r = 0;
    return Math.abs(signedYaw) < 0.5
      && Math.abs(v) < 0.5
      && Math.abs(z - neutralZ) < 0.05
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

function _qwenAngleDescriptor(horizontal, vertical, zoom, roll, mode, neutralZoom) {
    var h = ((parseFloat(horizontal) || 0) % 360 + 360) % 360;
    var v = parseFloat(vertical);
    if (!Number.isFinite(v)) v = 0;
    var neutralZ = parseFloat(neutralZoom);
    if (!Number.isFinite(neutralZ)) neutralZ = 5;
    var z = parseFloat(zoom);
    if (!Number.isFinite(z)) z = neutralZ;
    var r = parseFloat(roll);
    if (!Number.isFinite(r)) r = 0;
    if (_isQwenAngleNeutral(h, v, z, r, neutralZ)) return '';
    var rollDirectionZh = r > 0 ? '顺时针' : '逆时针';
    var rollDegrees = Math.abs(Math.round(r));
    var rollText = Math.abs(r) < 1 ? ''
      : '，' + _qwenRollCompositionText(rollDirectionZh, rollDegrees);
    return '<sks> ' + _qwenNativeHorizontalText(h) + ' '
      + _qwenNativeVerticalText(v) + ' '
      + _qwenNativeDistanceText(z)
      + rollText;
  }

function _qwenAnglePromptFromFieldValues(fieldValues, neutralZoom) {
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
      return _qwenAngleDescriptor(h, v, z, _currentQwenRoll(), _currentQwenAngleMode(), neutralZoom);
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

function _qwenAngleDefaultValue(root, axis, fallback) {
    var input = _qwenAngleInput(root, axis);
    var value = input && input.dataset ? input.dataset.angleDefault : undefined;
    if (value === undefined || value === null || value === '') return fallback;
    return value;
  }

function _qwenAngleNeutralZoom(root) {
    return _qwenAngleDefaultValue(root, 'zoom', 5);
  }

function _isQwenAngleControlNeutral(root) {
    if (!root) return true;
    var h = root.querySelector('[data-angle-field="horizontal_angle"]');
    var v = root.querySelector('[data-angle-field="vertical_angle"]');
    var z = root.querySelector('[data-angle-field="zoom"]');
    var r = root.querySelector('[data-angle-roll]');
    var neutralZoom = _qwenAngleNeutralZoom(root);
    return _isQwenAngleNeutral(
      h ? h.value : 0,
      v ? v.value : 0,
      z ? z.value : neutralZoom,
      r ? r.value : 0,
      neutralZoom
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
    if (isEnabled && expand) _setQwenAngleCollapsed(root, false);
    if (!isEnabled) _setQwenAngleCollapsed(root, true);
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
    var neutralZoom = _qwenAngleNeutralZoom(root);
    var fromFields = _qwenAnglePromptFromFieldValues(fieldValues, neutralZoom);
    if (fromFields) return fromFields;
    if (!root) return '';
    var h = root.querySelector('[data-angle-field="horizontal_angle"]');
    var v = root.querySelector('[data-angle-field="vertical_angle"]');
    var z = root.querySelector('[data-angle-field="zoom"]');
    if (!h || !v || !z) return '';
    return _qwenAngleDescriptor(h.value, v.value, z.value, _currentQwenRoll(), _currentQwenAngleMode(), neutralZoom);
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
    var withoutMarkers = _stripExistingQwenAngleMarkers(prompt);
    if (!_currentQwenAnglePrompt()) {
      return withoutMarkers
        .replace(/[ \t]{2,}/g, ' ')
        .replace(/[\n\r]{3,}/g, '\n\n')
        .trim();
    }
    return _sanitizePromptForQwenAngle(withoutMarkers);
  }

function _preparePromptForCurrentControls(prompt) {
    return _preparePromptForCurrentStyle(_preparePromptForCurrentQwenAngle(prompt));
  }

  function _promptWithQwenAngle(prompt, fieldValues) {
    var anglePrompt = _currentQwenAnglePrompt(fieldValues);
    if (!anglePrompt) return prompt;
    var base = _sanitizePromptForQwenAngle(prompt);
    if (!base) return anglePrompt;
    var parsed = _parsePromptJsonObject(base);
    if (parsed) {
      parsed.camera_control = Object.assign(
        {},
        parsed.camera_control && typeof parsed.camera_control === 'object' && !Array.isArray(parsed.camera_control) ? parsed.camera_control : {},
        { qwen_angle_prompt: anglePrompt }
      );
      return JSON.stringify(parsed);
    }
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
    $$('.video-mode-control:not(.bernini-mode-control) .video-mode-btn').forEach(function(btn) {
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
    $$('.video-mode-control:not(.bernini-mode-control) .video-mode-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        setVideoMode(btn.dataset.mode || 't2v');
      });
    });
    _syncVideoModeUi();
  }

function _setFieldControlValue(key, value) {
    if (key === '__ideogram4_canvas') {
      return _restoreIdeogramCanvasFromFieldValue(value);
    }
    if (key === '__style_preset_id') {
      return _setStylePresetValue(value);
    }
    if (/^__style_/.test(String(key || ''))) {
      return true;
    }
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
    if (el.dataset && el.dataset.type === 'bernini_mode') _syncBerniniModeUi();
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

function _promptFullscreenEditorCountText(value) {
    var len = String(value || '').length;
    return len + ' 字';
  }

function closePromptFullscreenEditor() {
    var overlay = document.getElementById('promptFullscreenEditor');
    document.removeEventListener('keydown', _promptFullscreenEditorKeydown);
    document.body.classList.remove('prompt-fullscreen-open');
    if (!overlay) return;
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    var prompt = $('#promptInput');
    if (prompt && prompt.focus) prompt.focus();
  }

function _promptFullscreenEditorKeydown(event) {
    if (!event) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closePromptFullscreenEditor();
    } else if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      closePromptFullscreenEditor();
    }
  }

function openPromptFullscreenEditor() {
    var prompt = $('#promptInput');
    if (!prompt) {
      if (window.CW && CW.toast) CW.toast('没有可编辑的提示词输入框', 'warn');
      return;
    }
    closePromptOptimizeMenu();
    closePromptFullscreenEditor();
    var overlay = document.createElement('div');
    overlay.id = 'promptFullscreenEditor';
    overlay.className = 'prompt-fullscreen-editor';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'promptFullscreenTitle');
    overlay.innerHTML = ''
      + '<div class="prompt-fullscreen-panel">'
      + '<div class="prompt-fullscreen-head">'
      + '<div><strong id="promptFullscreenTitle">全屏编辑提示词</strong></div>'
      + '<button class="prompt-fullscreen-close" type="button" title="关闭" aria-label="关闭">' + (window.CW && CW.icon ? CW.icon('x', 18) : '×') + '</button>'
      + '</div>'
      + '<textarea id="promptFullscreenTextarea" class="prompt-fullscreen-textarea" spellcheck="false"></textarea>'
      + '<div class="prompt-fullscreen-foot"><span id="promptFullscreenCount"></span><button class="prompt-fullscreen-done" type="button">完成</button></div>'
      + '</div>';
    document.body.appendChild(overlay);
    document.body.classList.add('prompt-fullscreen-open');
    var editor = overlay.querySelector('#promptFullscreenTextarea');
    var count = overlay.querySelector('#promptFullscreenCount');
    var closeBtn = overlay.querySelector('.prompt-fullscreen-close');
    var doneBtn = overlay.querySelector('.prompt-fullscreen-done');
    function syncCount() {
      if (count) count.textContent = _promptFullscreenEditorCountText(editor ? editor.value : '');
    }
    if (editor) {
      editor.value = prompt.value || '';
      editor.addEventListener('input', function() {
        _setPromptInputValue(editor.value);
        syncCount();
      });
      setTimeout(function() {
        editor.focus();
        editor.selectionStart = editor.selectionEnd = editor.value.length;
      }, 0);
    }
    if (closeBtn) closeBtn.addEventListener('click', closePromptFullscreenEditor);
    if (doneBtn) doneBtn.addEventListener('click', closePromptFullscreenEditor);
    overlay.addEventListener('pointerdown', function(event) {
      if (event.target === overlay) closePromptFullscreenEditor();
    });
    document.addEventListener('keydown', _promptFullscreenEditorKeydown);
    syncCount();
  }

function _quickGenerationLabel() {
    if (_isIdeogram4Workflow() && _ideogramCanvasState.mode === 'canvas' && _ideogramCanvasShapes().length) {
      var canvasSummary = _ideogramCanvasSummary();
      return ('布局画布｜' + (canvasSummary || 'Ideogram4 JSON layout')).slice(0, 300);
    }
    var prompt = ($('#promptInput') || {}).value || '';
    if (prompt.trim()) {
      var style = _stylePresetById(_currentStylePresetId());
      var label = style ? (style.label + '｜' + prompt.trim()) : prompt.trim();
      return label.slice(0, 300);
    }
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

  function _historyRecordNeedsDetailForReuse(item) {
    return !!(item && item.id && (item.__compact || !item.field_values));
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

function _isReusableLoadVideoField(key, fieldsMeta) {
    key = String(key || '');
    var fields = fieldsMeta || A._wfFieldMeta || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i] || {};
      if ((f.node_id + '::' + f.field) !== key) continue;
      return _isReferenceVideoField(f);
    }
    return /::(?:video|file)$/.test(key);
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

async function _fetchInputVideoMetadata(filename) {
    var safe = String(filename || '').trim();
    if (!safe) return {};
    try {
      var url = API + '/api/input-video-metadata/' + encodeURIComponent(safe);
      var resp = (window.CW && window.CW.auth && typeof window.CW.auth.apiFetch === 'function')
        ? await window.CW.auth.apiFetch(url)
        : await fetch(url);
      if (!resp || !resp.ok) return {};
      var data = await resp.json();
      return data && data.ok ? data : {};
    } catch (e) {
      return {};
    }
  }

async function _restoreRefVideoValue(value) {
    var refValue = String(value || '').trim();
    if (!refValue) return false;
    var vInput = document.querySelector('#refVideoValue');
    var preview = document.querySelector('#refVideoPreview');
    var ph = document.querySelector('#refVideoPlaceholder');
    if (!vInput) return false;
    vInput.value = refValue;
    _setRefVideoMetadata({});
    if (preview) {
      preview.setAttribute('data-video-autofit', '0');
      preview.src = API + '/api/input-video/' + encodeURIComponent(refValue);
      preview.style.display = '';
      preview.classList.remove('hidden');
      _showRefVideoFirstFrame(preview);
      preview.load && preview.load();
    }
    if (ph) ph.style.display = 'none';
    var meta = await _fetchInputVideoMetadata(refValue);
    if (($('#refVideoValue') || {}).value === refValue && meta && Object.keys(meta).length) {
      _setRefVideoMetadata(meta);
    }
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

async function _restoreRefVideoFromFieldValues(fieldValues, fieldsMeta) {
    var values = fieldValues || {};
    for (const [k, v] of Object.entries(values)) {
      if (!_isReusableLoadVideoField(k, fieldsMeta)) continue;
      if (await _restoreRefVideoValue(v)) return true;
    }
    return false;
  }

function _restoreBerniniRefsFromFieldValues(fieldValues) {
    var values = fieldValues || {};
    var raw = values['50::__bernini_refs'] || values.__bernini_refs || '';
    if (!raw) return false;
    var refs = [];
    if (Array.isArray(raw)) refs = raw;
    else {
      try {
        var parsed = JSON.parse(String(raw));
        refs = Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        refs = String(raw).split(',');
      }
    }
    refs = refs.map(function(item) { return String(item || '').trim(); }).filter(Boolean);
    if (!refs.length) return false;
    _berniniRefsState = [];
    refs.forEach(_addBerniniRefFilename);
    _renderBerniniRefsList();
    return true;
  }

function _fieldValueBySuffix(fieldValues, suffix) {
    var values = fieldValues || {};
    if (Object.prototype.hasOwnProperty.call(values, suffix)) return values[suffix];
    var keySuffix = '::' + suffix;
    for (var key in values) {
      if (Object.prototype.hasOwnProperty.call(values, key) && String(key).endsWith(keySuffix)) {
        return values[key];
      }
    }
    return '';
  }

function _restoreMultiRefsFromFieldValues(fieldValues) {
    var raw = _fieldValueBySuffix(fieldValues, '__multi_reference_images');
    if (!raw) return false;
    var refs = [];
    if (Array.isArray(raw)) refs = raw;
    else {
      try {
        var parsed = JSON.parse(String(raw));
        refs = Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        refs = String(raw).split(',');
      }
    }
    refs = refs.map(function(item) { return String(item || '').trim(); }).filter(Boolean);
    if (!refs.length) return false;
    _multiRefsState = [];
    refs.forEach(_addMultiRefFilename);
    var modeInput = document.querySelector('[data-type="image_reference_mode"][data-key]');
    if (modeInput) modeInput.value = refs.length >= 2 ? 'multi' : 'single';
    _renderMultiRefsList();
    _syncImageReferenceModeUi();
    return true;
  }

async function fillFormFromHistory(idx, key) {
    let h = _historyItemByKey(key) || historyItems[idx];
    if (!h) return;
    if (_historyRecordNeedsDetailForReuse(h) && window.CW && typeof window.CW.getHistoryDetail === 'function') {
      try {
        h = await window.CW.getHistoryDetail(h) || h;
      } catch (e) {
        if (window.CW && CW.toast) CW.toast(e && e.message ? e.message : '加载复刻信息失败', 'error');
        if (!h.prompt && !h.field_values) return;
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
      await _restoreRefVideoFromFieldValues(h.field_values, reuseFieldsMeta);
      _restoreBerniniRefsFromFieldValues(h.field_values);
      _restoreMultiRefsFromFieldValues(h.field_values);
    }
    if (reusedPrompt || h.prompt) {
      _setPromptInputValue(_preparePromptForCurrentControls(reusedPrompt || h.prompt));
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
      if (snap.prompt) { _setPromptInputValue(_preparePromptForCurrentControls(snap.prompt)); }
      if (snap.width) { var wi = $('#widthInput'); if (wi) wi.value = snap.width; }
      if (snap.height) { var hi = $('#heightInput'); if (hi) hi.value = snap.height; }
      for (const [k, v] of Object.entries(snap.adv || {})) {
        _setFieldControlValue(k, v);
      }
      _restoreRefImageFromFieldValues(snap.adv || {});
      await _restoreRefVideoFromFieldValues(snap.adv || {});
      _restoreBerniniRefsFromFieldValues(snap.adv || {});
      _restoreMultiRefsFromFieldValues(snap.adv || {});
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
    var jobReuseFieldsMeta = [];
    try {
      jobReuseFieldsMeta = await _getSubmitFieldsMeta();
    } catch (e) {
      jobReuseFieldsMeta = A._wfFieldMeta || [];
    }
    var jobReusedPrompt = _promptFromReusableFields(j.fields || {}, jobReuseFieldsMeta);
    if (jobReusedPrompt || j.prompt || j.prompt_preview) {
      _setPromptInputValue(_preparePromptForCurrentControls(jobReusedPrompt || j.prompt || j.prompt_preview));
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
	      _restoreRefImageFromFieldValues(j.fields, jobReuseFieldsMeta);
      await _restoreRefVideoFromFieldValues(j.fields, jobReuseFieldsMeta);
      _syncWanScailVideoTiming(Object.assign({}, j.fields), { adv: {} }, jobReuseFieldsMeta, { preferFrameCount: true });
      _restoreBerniniRefsFromFieldValues(j.fields);
      _restoreMultiRefsFromFieldValues(j.fields);
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
      await _waitForBerniniRefsUpload();
      await _waitForMultiRefsUpload();
      await _waitForRefVideoUpload();
      await _waitForRefAudioUpload();
      await _waitForDirectorUploads();
      qwenAngleEnabled = _isCurrentQwenAngleActive();
      submitFieldsMeta = await _getSubmitFieldsMeta();
      let promptFieldCount = 0;
      for (const f of submitFieldsMeta || []) {
        // Pre-set default value for this field (including hidden)
        if (_isQwenAngleField(f) && !qwenAngleEnabled) continue;
        const key = _fieldKeyForMeta(f);
        if (!key) continue;
        fields[key] = f.value;
        const zone = f.zone || 'advanced';
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
        if (_isBerniniModeField(f)) {
          fields[key] = _currentBerniniMode();
          snapshot.adv[key] = fields[key];
          continue;
        }
        if (_isBerniniRefsField(f)) {
          const refs = _berniniUploadedRefNames();
          fields[key] = JSON.stringify(refs);
          snapshot.adv[key] = fields[key];
          if (_berniniModeNeedsRefs(_currentBerniniMode()) && refs.length < 1) {
            throw new Error('Bernini 当前模式需要先上传参考图');
          }
          continue;
        }
        if (_isImageReferenceModeField(f)) {
          fields[key] = _currentImageReferenceMode();
          snapshot.adv[key] = fields[key];
          continue;
        }
        if (_isMultiImageRefsField(f)) {
          const refs = _multiUploadedRefNames();
          fields[key] = JSON.stringify(refs);
          snapshot.adv[key] = fields[key];
          if (_imageReferenceModeNeedsMultiRefs(_currentImageReferenceMode()) && refs.length < 2) {
            throw new Error('多图模式需要先上传至少 2 张参考图');
          }
          continue;
        }
        // LoadImage ref
        if (f.class_type === 'LoadImage' && f.field === 'image' && (zone === 'user_input' || !f.zone)) {
          const refVal = _primaryReferenceImageValue();
          delete fields[key];
          if (!refVal) {
            throw new Error(_isVideoI2VMode() ? '图生视频需要先上传参考图' : '需要先上传参考图');
          }
          fields[key] = refVal;
          snapshot.adv[key] = refVal;
          continue;
        }
        if (_isReferenceVideoField(f) && (zone === 'user_input' || !f.zone)) {
          const refVal = $('#refVideoValue')?.value || '';
          if (_isBerniniWorkflowFields(submitFieldsMeta) && !_berniniModeNeedsVideo(_currentBerniniMode())) {
            delete fields[key];
            continue;
          }
          if (!refVal) {
            throw new Error(_isBerniniWorkflowFields(submitFieldsMeta) ? 'Bernini 当前模式需要先上传源视频' : '需要先上传参考视频');
          }
          fields[key] = refVal;
          snapshot.adv[key] = refVal;
          continue;
        }
        if (_isReferenceAudioField(f) && (zone === 'user_input' || !f.zone)) {
          const refVal = $('#refAudioValue')?.value || '';
          if (!refVal) {
            throw new Error('需要先上传参考音频');
          }
          fields[key] = refVal;
          snapshot.adv[key] = refVal;
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

    _syncWanScailVideoTiming(fields, snapshot, submitFieldsMeta);

    if (qwenAngleEnabled) {
      const qwenFrameRoll = _currentQwenRoll();
      snapshot.adv.__qwen_frame_roll = qwenFrameRoll;
      snapshot.adv.__qwen_angle_mode = _currentQwenAngleMode();
    }

    fields.__user_prompt = rawPrompt;
    snapshot.adv.__user_prompt = rawPrompt;

    const styleInfo = _selectedStylePromptInfo(submitFieldsMeta);
    if (styleInfo) {
      fields.__style_preset_id = styleInfo.id;
      fields.__style_model_family = styleInfo.family;
      fields.__style_prompt_version = styleInfo.version;
      fields.__style_prompt_text = styleInfo.prompt;
      snapshot.adv.__style_preset_id = styleInfo.id;
      snapshot.adv.__style_model_family = styleInfo.family;
      snapshot.adv.__style_prompt_version = styleInfo.version;
      snapshot.adv.__style_prompt_text = styleInfo.prompt;
    }

    if (_isIdeogram4Workflow(submitFieldsMeta) && _ideogramCanvasState.mode === 'canvas') {
      fields.__ideogram4_canvas = JSON.stringify(_ideogramCanvasExportPayload());
      snapshot.adv.__ideogram4_canvas = fields.__ideogram4_canvas;
    }

    const styledPrompt = _isOfficialIdeogram4Workflow(submitFieldsMeta)
      ? _composeIdeogramCanvasPrompt(rawPrompt, styleInfo)
      : _promptWithStylePreset(rawPrompt, styleInfo);
    const prompt = _promptWithQwenAngle(styledPrompt, fields);
    promptKeys.forEach((key) => {
      fields[key] = prompt;
    });
    _bypassErniePromptEnhancerForStyle(styleInfo, submitFieldsMeta, fields, snapshot);

    var videoUpscaleSizing = _applyVideoUpscaleLongEdgeResolution(fields, submitFieldsMeta);
    if (videoUpscaleSizing) {
      snapshot.adv[videoUpscaleSizing.key] = videoUpscaleSizing.computedResolution;
      snapshot.adv.__video_upscale_long_edge = videoUpscaleSizing.targetLongEdge;
      snapshot.adv.__video_upscale_source_size = videoUpscaleSizing.width + 'x' + videoUpscaleSizing.height;
    }
    _syncWanScailVideoTiming(fields, snapshot, submitFieldsMeta);

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
        prompt_preview: String(d.prompt_preview || '').trim() || _quickGenerationLabel(),
        width: parseInt(($('#widthInput') || {}).value) || 0,
        height: parseInt(($('#heightInput') || {}).value) || 0,
        preferred_instance: '',
        preferred_node_id: '',
        queued_at: new Date().toLocaleTimeString('en-GB'),
        _local_submitted_at: Date.now(),
      };
      try {
        if (window.CW && CW.toast) {
          CW.toast('排队中', 'queued');
        }
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
    return runPromptOptimizeChoice('standard', '');
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
        btn.innerHTML = (window.CW && CW.icon ? CW.icon('zap') : '') + ' 高级';
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
    _setPromptInterrogateLoading(true, level >= 2 ? '专家反推中' : (level >= 1 ? '高级反推中' : '标准反推中'));
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
    var refVal = _primaryReferenceImageValue();
    openPromptInterrogateModal(refVal);
  }

  function rerunPromptInterrogateFromResult(sourceImage, level) {
    var refVal = String(sourceImage || '').trim();
    if (!refVal) {
      if (window.CW && CW.toast) CW.toast('缺少原图，无法切换反推级别', 'error');
      return;
    }
    var nextLevel = Number(level);
    if (!isFinite(nextLevel)) nextLevel = 0;
    nextLevel = Math.max(0, Math.min(2, Math.round(nextLevel)));
    _startPromptInterrogateTask(refVal, { level: nextLevel });
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
            '<button class="prompt-tool-btn prompt-interrogate-expert-btn" type="button" id="promptInterrogateExpertRunBtn" disabled>' + (window.CW && CW.icon ? CW.icon('zap') : '') + ' 高级</button>' +
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
        expertRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('zap') : '') + ' 高级';
        teamRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('users') : '') + ' 专家';
      } catch (e) {
        if (window.CW && CW.toast) CW.toast(e.message || '图片上传失败', 'error');
        runBtn.disabled = true;
        expertRunBtn.disabled = true;
        teamRunBtn.disabled = true;
        runBtn.innerHTML = (window.CW && CW.icon ? CW.icon('image') : '') + ' 标准';
        expertRunBtn.innerHTML = (window.CW && CW.icon ? CW.icon('zap') : '') + ' 高级';
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
          '<button type="button" data-angle-preset="h:0,v:0">正面</button>' +
          '<button type="button" data-angle-preset="h:180,v:0">背面</button>' +
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
    if (!Number.isFinite(z)) z = parseFloat(_qwenAngleNeutralZoom(root)) || 0;
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
    if (prompt) prompt.textContent = _isQwenAngleControlEnabled(root) ? _qwenAngleDescriptor(h, v, z, r, _qwenAngleMode(root), _qwenAngleNeutralZoom(root)) : '';
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
        var camera = root.querySelector('[data-angle-camera]');
        var dragging = false;
        var activePointerId = null;
        var startDrag = function(ev) {
          if (!ev) return;
          dragging = true;
          activePointerId = ev.pointerId !== undefined ? ev.pointerId : null;
          if (ev.preventDefault) ev.preventDefault();
          if (ev.stopPropagation) ev.stopPropagation();
          _applyQwenAngleSpherePoint(root, ev);
        };
        var moveDrag = function(ev) {
          if (!dragging) return;
          if (activePointerId !== null && ev.pointerId !== undefined && ev.pointerId !== activePointerId) return;
          if (ev.preventDefault) ev.preventDefault();
          _applyQwenAngleSpherePoint(root, ev);
        };
        var stopDrag = function(ev) {
          if (activePointerId !== null && ev && ev.pointerId !== undefined && ev.pointerId !== activePointerId) return;
          dragging = false;
          activePointerId = null;
        };
        if (camera) {
          camera.addEventListener('pointerdown', function(ev) {
            camera.setPointerCapture && camera.setPointerCapture(ev.pointerId);
            startDrag(ev);
          });
          camera.addEventListener('pointermove', moveDrag);
          camera.addEventListener('pointerup', function(ev) {
            camera.releasePointerCapture && camera.releasePointerCapture(ev.pointerId);
            stopDrag(ev);
          });
          camera.addEventListener('pointercancel', stopDrag);
          camera.addEventListener('click', function(ev) {
            ev.preventDefault();
            ev.stopPropagation();
          });
        }
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
var _directorPlacementMode = 'append';

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

function _directorPlacementValue() {
    var active = document.querySelector('#directorPanel [data-director-placement].active');
    var mode = active ? String(active.dataset.directorPlacement || '') : _directorPlacementMode;
    return /^(append|middle|end)$/.test(mode) ? mode : 'append';
  }

function _setDirectorPlacementMode(mode) {
    _directorPlacementMode = /^(append|middle|end)$/.test(String(mode || '')) ? String(mode) : 'append';
    var panel = $('#directorPanel');
    if (!panel) return;
    $$('#directorPanel [data-director-placement]').forEach(function(btn) {
      var active = String(btn.dataset.directorPlacement || '') === _directorPlacementMode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
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
    var summaryText = (_directorState.segments.length || 0) + ' 个镜头 / ' + total + ' 帧';
    document.querySelectorAll('[data-director-summary], [data-director-param-summary]').forEach(function(hint) {
      hint.textContent = summaryText;
    });
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

function _directorMakeSegment(imageFile, prompt, previewSrc, start, length, strength, label) {
    return {
      id: _directorSegmentId(),
      imageFile: String(imageFile || '').trim(),
      previewSrc: String(previewSrc || ''),
      start: Math.max(0, parseInt(start || 0, 10) || 0),
      length: Math.max(1, parseInt(length || 1, 10) || 1),
      strength: Math.max(0, Math.min(1, parseFloat(strength == null ? 0.9 : strength) || 0.9)),
      prompt: String(prompt || ''),
      label: String(label || '')
    };
  }

function _directorAddSegment(imageFile, prompt, previewSrc, placement) {
    imageFile = String(imageFile || '').trim();
    prompt = String(prompt || '');
    if (!imageFile && !prompt.trim()) return;
    var total = _directorTotalFrames();
    var mode = /^(append|middle|end)$/.test(String(placement || '')) ? String(placement) : _directorPlacementValue();
    var count = (_directorState.segments || []).length + 1;
    if (mode === 'middle' || mode === 'end') {
      var anchorLen = Math.max(1, Math.round(total * (mode === 'end' ? 0.18 : 0.25)));
      var start = mode === 'end'
        ? Math.max(0, total - anchorLen)
        : Math.max(0, Math.round(total * 0.5) - Math.round(anchorLen / 2));
      var end = Math.min(total, start + anchorLen);
      var inserted = _directorMakeSegment(imageFile, prompt, previewSrc, start, Math.max(1, end - start), 0.9, mode === 'end' ? '尾帧参考' : '中间参考');
      if (!(_directorState.segments || []).length && start > 0) {
        _directorState.segments.push(_directorMakeSegment('', '', '', 0, start, 0.55, '前段生成'));
      }
      _directorState.segments.push(inserted);
      if (mode === 'middle' && _directorState.segments.length <= 2 && end < total) {
        _directorState.segments.push(_directorMakeSegment('', '', '', end, total - end, 0.55, '后段生成'));
      }
      _renderDirectorTimeline();
      return;
    }
    var len = Math.max(1, Math.round(total / Math.max(1, count)));
    (_directorState.segments || []).forEach(function(seg, idx) {
      seg.start = idx * len;
      seg.length = len;
    });
    var start = Math.min(total - 1, (count - 1) * len);
    _directorState.segments.push(_directorMakeSegment(imageFile, prompt, previewSrc, start, Math.max(1, total - start), 0.9, '镜头 ' + count));
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
      '<div class="director-placement" role="group" aria-label="新增参考图位置"><button type="button" class="active" data-director-placement="append" aria-pressed="true">追加分镜</button><button type="button" data-director-placement="middle" aria-pressed="false">作为中间帧</button><button type="button" data-director-placement="end" aria-pressed="false">作为尾帧</button></div>' +
      '<div class="director-drop" id="directorDropZone"><input type="file" id="directorImageInput" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" multiple class="hidden"><input type="file" id="directorShotImageInput" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden"><button type="button" onclick="document.getElementById(&quot;directorImageInput&quot;).click()">' + (window.CW && CW.icon ? CW.icon('image', 16) : '') + ' 添加参考图</button><span>可拖入历史图片</span></div>' +
      '<div class="director-track" data-director-track></div><div class="director-shot-list" data-director-list></div>' +
      hidden('timeline_data') + hidden('local_prompts') + hidden('segment_lengths') + hidden('guide_strength') + hidden('use_custom_audio') +
    '</div>';
  }

function _directorParamControlHtml() {
    return '<div class="fg director-mode-param" id="directorModeParam">' +
      '<div class="director-mode-param-head"><label>导演模式</label><span data-director-param-summary>0 个镜头</span></div>' +
      '<button id="directorModeBtn" class="director-mode-param-btn" type="button" title="打开导演模式" onclick="CW.toggleDirectorPanel()">' + (window.CW && CW.icon ? CW.icon('clapperboard', 16) : '') + '<span>打开导演面板</span></button>' +
      '<div class="director-mode-param-hint">分镜、参考图和首中尾帧控制</div>' +
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
    var placement = panel.querySelector('.director-placement');
    if (placement && !placement.dataset.bound) {
      placement.dataset.bound = '1';
      placement.addEventListener('click', function(ev) {
        var btn = ev.target.closest && ev.target.closest('[data-director-placement]');
        if (!btn) return;
        _setDirectorPlacementMode(btn.dataset.directorPlacement || 'append');
      });
      _setDirectorPlacementMode(_directorPlacementMode);
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

function _berniniRefsFieldHtml(f) {
    var key = _fieldKeyForMeta(f) || '50::__bernini_refs';
    return '<div class="ref-image-section bernini-ref-section" id="berniniRefSection"><label>' + escH((f && f.label) || '参考图片') + '</label><div class="img-upload-zone bernini-ref-zone" id="berniniRefsZone"><div id="berniniRefsPlaceholder" class="img-upload-placeholder">选择或拖入参考图</div><div id="berniniRefsList" class="bernini-ref-list"></div><input type="hidden" id="berniniRefsValue" data-key="' + escA(key) + '" data-type="bernini_refs" value="[]"><input type="file" id="berniniRefsFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" multiple class="hidden"></div></div>';
  }

function _imageReferenceModeFieldHtml(f) {
    var key = _fieldKeyForMeta(f);
    var value = String((f && f.value) || 'single').toLowerCase() === 'multi' ? 'multi' : 'single';
    return '<div class="fg image-ref-mode-fg"><label>' + escH((f && f.label) || '参考图模式') + '</label><div class="video-mode-control image-ref-mode-control" data-image-ref-mode-key="' + escA(key) + '"><button type="button" class="video-mode-btn image-ref-mode-btn' + (value === 'single' ? ' active' : '') + '" data-image-ref-mode="single" aria-pressed="' + (value === 'single' ? 'true' : 'false') + '">单图</button><button type="button" class="video-mode-btn image-ref-mode-btn' + (value === 'multi' ? ' active' : '') + '" data-image-ref-mode="multi" aria-pressed="' + (value === 'multi' ? 'true' : 'false') + '">多图</button><input type="hidden" data-key="' + escA(key) + '" data-type="image_reference_mode" value="' + escA(value) + '"></div></div>';
  }

function _multiRefsFieldHtml(f) {
    var key = _fieldKeyForMeta(f) || '40::__multi_reference_images';
    var maxRefs = parseInt((f && f.max) || 3, 10) || 3;
    return '<div class="ref-image-section multi-ref-section" id="multiRefSection" data-max-refs="' + escA(String(maxRefs)) + '"><label>' + escH((f && f.label) || '多参考图片') + '</label><div class="img-upload-zone bernini-ref-zone multi-ref-zone" id="multiRefsZone"><div id="multiRefsPlaceholder" class="img-upload-placeholder">选择或拖入 2-' + escH(String(maxRefs)) + ' 张参考图</div><div id="multiRefsList" class="bernini-ref-list"></div><input type="hidden" id="multiRefsValue" data-key="' + escA(key) + '" data-type="multi_image_refs" value="[]"><input type="file" id="multiRefsFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" multiple class="hidden"></div></div>';
  }

function _berniniUploadedRefNames() {
    var names = (_berniniRefsState || [])
      .filter(function(item) { return item && !item.error && item.filename; })
      .map(function(item) { return item.filename; });
    if (names.length) return names;
    var hidden = $('#berniniRefsValue');
    if (!hidden || !hidden.value) return [];
    try {
      var parsed = JSON.parse(hidden.value);
      return Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : [];
    } catch (e) {
      return String(hidden.value || '').split(',').map(function(v) { return v.trim(); }).filter(Boolean);
    }
  }

function _syncBerniniRefsValue() {
    var hidden = $('#berniniRefsValue');
    if (hidden) hidden.value = JSON.stringify(_berniniUploadedRefNames());
  }

function _multiUploadedRefNames() {
    var names = (_multiRefsState || [])
      .filter(function(item) { return item && !item.error && item.filename; })
      .map(function(item) { return item.filename; });
    if (names.length) return names;
    var hidden = $('#multiRefsValue');
    if (!hidden || !hidden.value) return [];
    try {
      var parsed = JSON.parse(hidden.value);
      return Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : [];
    } catch (e) {
      return String(hidden.value || '').split(',').map(function(v) { return v.trim(); }).filter(Boolean);
    }
  }

function _syncMultiRefsValue() {
    var hidden = $('#multiRefsValue');
    if (hidden) hidden.value = JSON.stringify(_multiUploadedRefNames());
  }

function _singleReferenceImageValue() {
    return String(($('#refImageValue') || {}).value || '').trim();
  }

function _clearSingleReferenceImageValue() {
    var preview = $('#refImagePreview');
    var placeholder = $('#refImagePlaceholder');
    var valueInput = $('#refImageValue');
    if (valueInput) valueInput.value = '';
    if (preview) {
      preview.src = '';
      preview.style.display = 'none';
      preview.classList.add('hidden');
    }
    if (placeholder) placeholder.style.display = '';
    _syncQwenAngleReferencePreview();
  }

function _multiRefMaxCount() {
    var zone = $('#multiRefSection');
    return parseInt((zone && zone.getAttribute('data-max-refs')) || '3', 10) || 3;
  }

function _multiRefItemFromFilename(filename) {
    filename = String(filename || '').trim();
    if (!filename) return null;
    return {
      id: ++_multiRefsSeq,
      filename: filename,
      preview: API + '/api/input-image/' + encodeURIComponent(filename),
      uploading: false,
      error: false
    };
  }

function _revokeMultiRefPreview(item) {
    try {
      if (item && item.preview && item.preview.indexOf('blob:') === 0 && window.URL && URL.revokeObjectURL) {
        URL.revokeObjectURL(item.preview);
      }
    } catch (e) {}
  }

function _multiRefItemsFromCurrentValue() {
    var items = (_multiRefsState || []).filter(Boolean);
    if (items.length) return items;
    return _multiUploadedRefNames().map(_multiRefItemFromFilename).filter(Boolean);
  }

function _ensureMultiRefsStartWithSingleReference() {
    var filename = _singleReferenceImageValue();
    if (!filename) {
      _syncMultiRefsValue();
      return false;
    }
    var items = _multiRefItemsFromCurrentValue();
    var selected = null;
    var rest = [];
    items.forEach(function(item) {
      if (item && item.filename === filename && !selected) selected = item;
      else rest.push(item);
    });
    if (!selected) selected = _multiRefItemFromFilename(filename);
    var next = [selected].concat(rest).slice(0, _multiRefMaxCount()).filter(Boolean);
    items.forEach(function(item) {
      if (next.indexOf(item) < 0) _revokeMultiRefPreview(item);
    });
    _multiRefsState = next;
    _renderMultiRefsList();
    return true;
  }

function _syncSingleReferenceFromFirstMultiRef(trimMulti) {
    var items = _multiRefItemsFromCurrentValue().filter(function(item) {
      return item && !item.error;
    });
    var first = items.length ? items[0] : null;
    if (trimMulti) {
      var next = first ? [first] : [];
      (_multiRefsState || []).forEach(function(item) {
        if (next.indexOf(item) < 0) _revokeMultiRefPreview(item);
      });
      _multiRefsState = next;
      _renderMultiRefsList();
    }
    if (first && first.filename) {
      return _restoreRefImageValue(first.filename);
    }
    _clearSingleReferenceImageValue();
    return false;
  }

function _primaryReferenceImageValue() {
    if (_imageReferenceModeNeedsMultiRefs(_currentImageReferenceMode())) {
      var refs = _multiUploadedRefNames();
      return refs.length ? refs[0] : '';
    }
    return _singleReferenceImageValue();
  }

function _syncImageReferenceModeUi() {
    var input = document.querySelector('[data-type="image_reference_mode"][data-key]');
    var mode = _currentImageReferenceMode();
    if (input) input.value = mode;
    document.querySelectorAll('[data-image-ref-mode]').forEach(function(btn) {
      var active = btn.getAttribute('data-image-ref-mode') === mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    var singleSection = $('#refImageZone') && $('#refImageZone').closest ? $('#refImageZone').closest('.ref-image-section') : null;
    var multiSection = $('#multiRefSection');
    var needsMulti = _imageReferenceModeNeedsMultiRefs(mode);
    if (singleSection) singleSection.style.display = needsMulti ? 'none' : '';
    if (multiSection) {
      multiSection.style.display = needsMulti ? '' : 'none';
      multiSection.classList.toggle('is-required', needsMulti);
      var placeholder = $('#multiRefsPlaceholder');
      var maxRefs = parseInt(multiSection.getAttribute('data-max-refs') || '3', 10) || 3;
      if (placeholder) placeholder.textContent = needsMulti ? ('选择或拖入 2-' + maxRefs + ' 张参考图') : '当前模式不需要多参考图';
    }
  }

function _initImageReferenceModeControl() {
    var root = document.querySelector('[data-image-ref-mode-key]');
    if (!root || root.dataset.inited === '1') {
      _syncImageReferenceModeUi();
      return;
    }
    root.dataset.inited = '1';
    root.addEventListener('click', function(e) {
      var btn = e.target && e.target.closest ? e.target.closest('[data-image-ref-mode]') : null;
      if (!btn) return;
      var nextMode = btn.getAttribute('data-image-ref-mode') === 'multi' ? 'multi' : 'single';
      var input = root.querySelector('[data-type="image_reference_mode"]');
      if (input) input.value = nextMode;
      if (nextMode === 'multi') _ensureMultiRefsStartWithSingleReference();
      else _syncSingleReferenceFromFirstMultiRef(true);
      _syncImageReferenceModeUi();
    });
    _syncImageReferenceModeUi();
  }

function _syncBerniniRefsMode() {
    var mode = _currentBerniniMode();
    var section = $('#berniniRefSection');
    var needed = _berniniModeNeedsRefs(mode);
    if (section) {
      section.style.display = needed ? '' : 'none';
      section.classList.toggle('is-required', needed);
      var placeholder = $('#berniniRefsPlaceholder');
      if (placeholder) {
        if (mode === 'i2i') placeholder.textContent = '上传 1 张源图';
        else if (mode === 'i2v') placeholder.textContent = '上传 1 张参考图';
        else if (mode === 'r2v') placeholder.textContent = '上传 1-8 张参考图';
        else if (mode === 'rv2v') placeholder.textContent = '上传 1-8 张风格/角色参考图';
        else placeholder.textContent = '当前模式不需要参考图';
      }
    }
    _syncBerniniVideoMode(mode);
  }

function _syncBerniniVideoMode(modeArg) {
    var section = $('#refVideoZone')?.closest('.ref-video-section');
    if (!section || !_isBerniniWorkflowFields()) return;
    var mode = String(modeArg || _currentBerniniMode()).toLowerCase();
    var needed = _berniniModeNeedsVideo(mode);
    section.style.display = needed ? '' : 'none';
    section.classList.toggle('is-required', needed);
    var label = section.querySelector('label');
    if (label) label.textContent = mode === 'rv2v' ? '源视频' : '源视频';
    var placeholder = $('#refVideoPlaceholder');
    if (placeholder) {
      if (mode === 'rv2v') placeholder.textContent = '上传要编辑的源视频';
      else if (mode === 'v2v') placeholder.textContent = '上传要重绘/编辑的源视频';
      else placeholder.textContent = '当前模式不需要源视频';
    }
  }

function _syncBerniniModeUi() {
    var root = document.querySelector('[data-bernini-mode-key]');
    if (!root) {
      _syncBerniniRefsMode();
      _syncBerniniVideoMode();
      return;
    }
    var select = root.querySelector('[data-type="bernini_mode"]');
    var mode = String((select && select.value) || 't2i').toLowerCase() || 't2i';
    var summary = root.querySelector('[data-bernini-mode-summary]');
    if (summary) summary.textContent = _berniniModeInfo(mode).desc;
    _syncBerniniRefsMode();
  }

function _initBerniniModeControl() {
    var root = document.querySelector('[data-bernini-mode-key]');
    if (!root || root.dataset.inited === '1') {
      _syncBerniniModeUi();
      return;
    }
    root.dataset.inited = '1';
    root.addEventListener('change', function(e) {
      if (!e.target || e.target.getAttribute('data-type') !== 'bernini_mode') return;
      _syncBerniniModeUi();
    });
    _syncBerniniModeUi();
  }

function renderQuickForm(fields) {
    var container = $('#quickFormFields');
    if (!container) return;
    _removeBodyDirectorPanel();
    if (!fields || !fields.length) { container.innerHTML = ''; return; }
    fields = _normalizeFieldMeta(fields, A.currentWF || A._wfFieldWorkflow || '');
    // Preserve prompt text across workflow switches
    var _savedPrompt = ($('#promptInput') || {}).value || '';
    var _savedStylePreset = _currentStylePresetId();
    var hasZones = fields.some(function(f) { return f.zone; });
    var hasDirector = _hasDirectorWorkflow(fields);
    var html = '', hasTextEncode = false, hasLoadImage = false, hasLoadVideo = false, hasLoadAudio = false, hasBerniniRefs = false, hasMultiRefs = false, hasImageReferenceMode = false, quickImageRendered = false, quickVideoRendered = false, quickAudioRendered = false, quickBerniniRefsRendered = false, quickMultiRefsRendered = false, sizeRendered = false, styleRendered = false, ideogramCanvasRendered = false;
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
      var bounds = _sizeLimitBounds(limits);
      var limitLabel = limits.maxPixels
        ? '按' + bounds.multiple + '像素倍数与当前模型像素上限同步'
        : '按' + bounds.multiple + '像素倍数与当前工作流上限同步';
      var out = '<div class="fg size-control" id="sizeSection" data-size-control data-size-limit="' + escA(limits.name || 'default') + '"><div class="size-control-head"><label>出图尺寸</label><span class="size-control-hint">' + escH(limitLabel) + '</span></div><div class="ratio-grid size-preset-grid" id="ratioGrid" role="group" aria-label="出图比例">';
      var presets = _ratioPresetsForLimits(limits);
      for (var spi = 0; spi < presets.length; spi++) {
        var p = presets[spi];
        var active = p[0] === sw && p[1] === sh;
        var ratio = _ratioPartsForPreset(p);
        out += '<button type="button" class="ratio-btn size-preset-btn' + (active ? ' active' : '') + '" data-size-preset="1" data-w="' + p[0] + '" data-h="' + p[1] + '" data-ratio-w="' + ratio.width + '" data-ratio-h="' + ratio.height + '" title="' + p[0] + '×' + p[1] + '" aria-pressed="' + (active ? 'true' : 'false') + '"><span class="ratio-shape size-preset-shape" style="width:' + p[3] + ';height:' + p[4] + '"></span><span class="ratio-label size-preset-ratio">' + escH(_sizePresetLabel(p)) + '</span><span class="size-preset-pixels">' + p[0] + '×' + p[1] + '</span></button>';
      }
      out += '</div><div class="ratio-custom size-custom-row"><input type="number" id="widthInput" value="' + sw + '" step="' + bounds.multiple + '" min="' + bounds.minWidth + '" max="' + bounds.maxWidth + '" aria-label="宽度"><span class="sep-dim" aria-label="乘以">×</span><input type="number" id="heightInput" value="' + sh + '" step="' + bounds.multiple + '" min="' + bounds.minHeight + '" max="' + bounds.maxHeight + '" aria-label="高度"></div></div>';
      return out;
    }
    for (var fi = 0; fi < fields.length; fi++) {
      var f = fields[fi], zone = f.zone || (hasZones ? 'hidden' : 'advanced');
      if (zone !== 'user_input') {
        if (hasZones) continue;
        if (f.class_type === 'LoadImage' && f.field === 'image') hasLoadImage = true;
        else if (_isBerniniRefsField(f)) hasBerniniRefs = true;
        else if (_isMultiImageRefsField(f)) hasMultiRefs = true;
        else if (_isImageReferenceModeField(f)) hasImageReferenceMode = true;
        else if (_isReferenceVideoField(f)) hasLoadVideo = true;
        else if (_isReferenceAudioField(f)) hasLoadAudio = true;
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
        var labelText = f.label || 'Prompt', nodeInfo = f.node_title ? ' [' + f.node_title.split('(')[0].trim() + ']' : '';
        var optimizeCopy = _promptOptimizeCopy(fields);
        var styleControlHtml = '';
        if (!styleRendered) {
          styleControlHtml = _stylePresetControlHtml(fields);
          styleRendered = true;
        }
        var ideogramCanvasHtml = '';
        if (!ideogramCanvasRendered && _isIdeogram4Workflow(fields)) {
          ideogramCanvasHtml = _ideogramCanvasControlHtml();
          ideogramCanvasRendered = true;
        }
        var promptFullscreenBtnHtml = '<button id="promptFullscreenBtn" class="prompt-fullscreen-btn" type="button" title="全屏编辑提示词" aria-label="全屏编辑提示词" onclick="CW.openPromptFullscreenEditor()">' + (window.CW && CW.icon ? CW.icon('scaleup', 15) : '↗') + '</button>';
        html += '<div class="fg prompt-fg"><div class="prompt-label-row"><label>' + escH(labelText + nodeInfo) + '</label>' + promptFullscreenBtnHtml + '</div><div class="prompt-input-wrap prompt-input-wrap-with-style"><textarea id="promptInput" placeholder="' + escA(labelText) + '..."></textarea>' + styleControlHtml + ideogramCanvasHtml + '</div><div class="prompt-actions"><button id="interrogatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-image" type="button" title="图片反推" onclick="CW.interrogatePromptFromImage()">' + (window.CW && CW.icon ? CW.icon('image') : '') + ' <span class="prompt-tool-label">图片反推</span></button><button id="optimizePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant is-compact-disabled" type="button" title="' + escA(optimizeCopy.label) + '" data-optimize-mode="' + escA(optimizeCopy.mode) + '" aria-haspopup="menu" onclick="CW.openPromptOptimizeMenu(event)" disabled>' + (window.CW && CW.icon ? CW.icon('zap') : '') + ' <span class="prompt-tool-label">' + escH(optimizeCopy.label) + '</span></button><button id="translatePromptBtn" class="prompt-tool-btn prompt-tool-btn-vibrant prompt-tool-btn-translate is-compact-disabled" type="button" title="中文/英文提示词切换" onclick="CW.translatePromptLanguage()" disabled>' + (window.CW && CW.icon ? CW.icon('globe') : '') + ' <span class="prompt-tool-label">中英切换</span></button><button id="clearPromptBtn" class="prompt-tool-btn prompt-tool-btn-clear clear-btn is-compact-disabled" type="button" title="清除文字" onclick="CW.clearPrompt()" disabled>' + (window.CW && CW.icon ? CW.icon('trash-2') : '') + ' <span class="prompt-tool-label">清除文字</span></button></div></div>';
      } else if (_isVideoModeField(f)) {
        var modeKey = `${f.node_id}::${f.field}`;
        var isBypass = f.value !== false && f.value !== 'false' && f.value !== 'False';
        html += '<div class="fg video-mode-fg"><label>' + escH(f.label || '生成模式') + '</label><div class="video-mode-control" data-video-mode-key="' + escA(modeKey) + '"><button type="button" class="video-mode-btn' + (isBypass ? ' active' : '') + '" data-mode="t2v" aria-pressed="' + (isBypass ? 'true' : 'false') + '">文生视频</button><button type="button" class="video-mode-btn' + (!isBypass ? ' active' : '') + '" data-mode="i2v" aria-pressed="' + (!isBypass ? 'true' : 'false') + '">图生视频</button><input type="hidden" data-key="' + escA(modeKey) + '" data-type="video_mode" value="' + (isBypass ? 'true' : 'false') + '"></div></div>';
      } else if (_isBerniniModeField(f)) {
        var berniniModeKey = _fieldKeyForMeta(f);
        var berniniModeVal = String(f.value || 't2i').toLowerCase();
        var berniniModes = _berniniModeOptions();
        var berniniModeInfo = _berniniModeInfo(berniniModeVal);
        html += '<div class="fg bernini-mode-fg"><label>' + escH(f.label || '生成模式') + '</label><div class="bernini-mode-control" data-bernini-mode-key="' + escA(berniniModeKey) + '"><select class="bernini-mode-select" data-key="' + escA(berniniModeKey) + '" data-type="bernini_mode">';
        for (var bmi = 0; bmi < berniniModes.length; bmi++) {
          var bm = berniniModes[bmi];
          html += '<option value="' + escA(bm.value) + '"' + (bm.value === berniniModeVal ? ' selected' : '') + '>' + escH(_berniniModeOptionLabel(bm)) + '</option>';
        }
        html += '</select><div class="bernini-mode-summary" data-bernini-mode-summary>' + escH(berniniModeInfo.desc) + '</div></div></div>';
      } else if (_isBerniniRefsField(f)) {
        hasBerniniRefs = true;
        quickBerniniRefsRendered = true;
        html += _berniniRefsFieldHtml(f);
      } else if (_isImageReferenceModeField(f)) {
        hasImageReferenceMode = true;
        html += _imageReferenceModeFieldHtml(f);
      } else if (_isMultiImageRefsField(f)) {
        hasMultiRefs = true;
        quickMultiRefsRendered = true;
        html += _multiRefsFieldHtml(f);
      } else if (f.class_type === 'LoadImage' && f.field === 'image') {
        hasLoadImage = true;
        quickImageRendered = true;
        html += '<div class="ref-image-section"><label>' + escH(f.label || 'Reference Image') + '</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden"></div></div>';
      } else if (_isReferenceVideoField(f)) {
        hasLoadVideo = true;
        quickVideoRendered = true;
        html += '<div class="ref-image-section ref-video-section"><label>' + escH(f.label || 'Reference Video') + '</label><div class="img-upload-zone video-upload-zone" id="refVideoZone"><div id="refVideoPlaceholder" class="img-upload-placeholder">Click or drag video</div><video id="refVideoPreview" class="img-upload-preview video-upload-preview hidden" muted playsinline controls></video><input type="hidden" id="refVideoValue" value=""><input type="file" id="refVideoFile" accept="video/*,.mp4,.webm,.mov,.m4v" class="hidden"></div></div>';
      } else if (_isReferenceAudioField(f)) {
        hasLoadAudio = true;
        quickAudioRendered = true;
        html += '<div class="ref-image-section ref-audio-section"><label>' + escH(f.label || 'Reference Audio') + '</label><div class="img-upload-zone audio-upload-zone" id="refAudioZone"><div id="refAudioPlaceholder" class="img-upload-placeholder">Click or drag audio</div><audio id="refAudioPreview" class="audio-upload-preview hidden" controls></audio><div id="refAudioActions" class="audio-upload-actions hidden"><span id="refAudioName" class="audio-upload-name"></span><button id="refAudioReplace" class="audio-upload-replace" type="button">重新选择</button></div><input type="hidden" id="refAudioValue" value=""><input type="file" id="refAudioFile" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus" class="hidden"></div></div>';
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
      } else if (f.type === 'toggle' || f.type === 'bool') {
        var toggleKey = `${f.node_id}::${f.field}`;
        var toggleVal = f.value === true || f.value === 'True' || f.value === 'true';
        html += '<div class="fg quick-toggle-fg"><label>' + escH(f.label || f.field) + '</label><label class="toggle-label bool-toggle"><input type="checkbox" data-key="' + escA(toggleKey) + '" data-type="bool" value="' + (toggleVal ? 'true' : 'false') + '" ' + (toggleVal ? 'checked' : '') + ' onchange="this.value=this.checked"><span class="toggle-slider"></span><span class="toggle-state" data-on="开启" data-off="关闭"></span></label></div>';
      } else if (f.type === 'text') {
        var textKey = `${f.node_id}::${f.field}`;
        var textVal = f.value ?? '';
        html += '<div class="fg quick-text-fg"><label>' + escH(f.label || f.field) + '</label><input type="text" data-key="' + escA(textKey) + '" value="' + escA(String(textVal)) + '"></div>';
      }
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadImage && !quickImageRendered) {
      html += '<div class="ref-image-section"><label>Reference Image</label><div class="img-upload-zone" id="refImageZone"><div id="refImagePlaceholder" class="img-upload-placeholder">Click or drag image</div><img id="refImagePreview" src="" class="img-upload-preview" class="hidden"><input type="hidden" id="refImageValue" value=""><input type="file" id="refImageFile" accept="image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif" class="hidden"></div></div>';
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasBerniniRefs && !quickBerniniRefsRendered) {
      html += _berniniRefsFieldHtml({ key: '50::__bernini_refs', field: '__bernini_refs', label: '参考图片' });
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasMultiRefs && !quickMultiRefsRendered) {
      html += _multiRefsFieldHtml({ key: '40::__multi_reference_images', field: '__multi_reference_images', label: '多参考图片', max: 3 });
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadVideo && !quickVideoRendered) {
      html += '<div class="ref-image-section ref-video-section"><label>Reference Video</label><div class="img-upload-zone video-upload-zone" id="refVideoZone"><div id="refVideoPlaceholder" class="img-upload-placeholder">Click or drag video</div><video id="refVideoPreview" class="img-upload-preview video-upload-preview hidden" muted playsinline controls></video><input type="hidden" id="refVideoValue" value=""><input type="file" id="refVideoFile" accept="video/*,.mp4,.webm,.mov,.m4v" class="hidden"></div></div>';
    }
    if (!hasTextEncode && !hasLatentW && !hasLatentH && hasLoadAudio && !quickAudioRendered) {
      html += '<div class="ref-image-section ref-audio-section"><label>Reference Audio</label><div class="img-upload-zone audio-upload-zone" id="refAudioZone"><div id="refAudioPlaceholder" class="img-upload-placeholder">Click or drag audio</div><audio id="refAudioPreview" class="audio-upload-preview hidden" controls></audio><div id="refAudioActions" class="audio-upload-actions hidden"><span id="refAudioName" class="audio-upload-name"></span><button id="refAudioReplace" class="audio-upload-replace" type="button">重新选择</button></div><input type="hidden" id="refAudioValue" value=""><input type="file" id="refAudioFile" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus" class="hidden"></div></div>';
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
    // Restore only text the user had already typed before this DOM rebuild.
    if (_savedPrompt) {
      var pi2 = $('#promptInput');
      if (pi2) pi2.value = _savedPrompt;
    }
    var promptInput = $('#promptInput');
    if (promptInput && window.CW.syncClearPromptButton) {
      promptInput.addEventListener('input', window.CW.syncClearPromptButton);
      window.CW.syncClearPromptButton();
    }
    _initStylePresetControl(fields);
    _setStylePresetValue(_savedStylePreset || '');
    if (ideogramCanvasRendered) _initIdeogramCanvasControl(fields);
    _initVideoModeControl();
    _initBerniniModeControl();
    if (hasBerniniRefs) { _berniniRefsInited = false; setTimeout(function() { _initBerniniRefsZone(); }, 50); }
    else _resetBerniniRefs();
    if (hasImageReferenceMode) _initImageReferenceModeControl();
    if (hasMultiRefs) { _multiRefsInited = false; setTimeout(function() { _initMultiRefsZone(); _syncImageReferenceModeUi(); }, 50); }
    else _resetMultiRefs();
    _initQwenAngleControls();
    if (hasDirector) _initDirectorPanel();
    if (hasLoadImage) { _refImageInited = false; setTimeout(function() { _initRefImageZone(); _syncImageReferenceModeUi(); }, 50); }
    if (hasLoadVideo) { _refVideoInited = false; setTimeout(function() { _initRefVideoZone(); }, 50); }
    if (hasLoadAudio) { _refAudioInited = false; setTimeout(function() { _initRefAudioZone(); }, 50); }
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
      if (!_isReferenceVideoField(f)) return false;
      const zone = f.zone || 'advanced';
      return zone === 'user_input';
    });
    var _loadAudioFields = fields.filter((f) => {
      if (!_isReferenceAudioField(f)) return false;
      const zone = f.zone || 'advanced';
      return zone === 'user_input';
    });
    // Fallback: if no zone info, use old logic
    if (!_loadImageFields.length && !fields.some((f) => f.zone)) {
      _loadImageFields = fields.filter((f) => f.class_type === 'LoadImage' && f.field === 'image');
    }
    const hasLoadImage = _loadImageFields.length > 0;
    const hasLoadVideo = _loadVideoFields.length > 0;
    const hasLoadAudio = _loadAudioFields.length > 0;
    const section = $('#refImageSection');
    if (section) section.style.display = hasLoadImage ? '' : 'none';
    if (hasLoadImage) _initRefImageZone();
    else _resetRefImage();
    if (!hasLoadVideo) _resetRefVideo();
    if (!hasLoadAudio) _resetRefAudio();

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
        if (_isReferenceVideoField(f)) return false;
        if (_isReferenceAudioField(f)) return false;
        if (_isVideoModeField(f)) return false;
        if (_isBerniniModeField(f) || _isBerniniRefsField(f)) return false;
        if (_isImageReferenceModeField(f) || _isMultiImageRefsField(f)) return false;
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
        if (_isReferenceVideoField(f)) return false;
        if (_isReferenceAudioField(f)) return false;
        if (_isBerniniModeField(f) || _isBerniniRefsField(f)) return false;
        if (_isImageReferenceModeField(f) || _isMultiImageRefsField(f)) return false;
      }
      // Skip output zone (read-only, handled by SaveImage)
      if (zone === 'output') return false;
      return true;
    });

    const hasDirector = _hasDirectorWorkflow(fields);
    let html = hasDirector ? _directorParamControlHtml() : '';
    if (!advFields.length) {
      box.innerHTML = html || '<div class="gen-empty">无可编辑参数</div>';
      if (hasDirector) _renderDirectorTrackOnly();
      return;
    }
    for (const f of advFields) {
      const key = _fieldKeyForMeta(f);
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
    if (hasDirector) _renderDirectorTrackOnly();
    setTimeout(function() { _bindWanScailVideoTimingSync(fields); }, 0);
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
var _berniniRefsInited = false;
var _berniniRefsState = [];
var _berniniRefsUploadPromises = [];
var _berniniRefsSeq = 0;
var _multiRefsInited = false;
var _multiRefsState = [];
var _multiRefsUploadPromises = [];
var _multiRefsSeq = 0;
var _refVideoInited = false;
var _refVideoUploadPromise = null;
var _refVideoUploadToken = 0;
var _refAudioInited = false;
var _refAudioUploadPromise = null;
var _refAudioUploadToken = 0;
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

function _resetBerniniRefs() {
    _berniniRefsInited = false;
    _berniniRefsUploadPromises = [];
    _berniniRefsState.forEach(function(item) {
      try {
        if (item && item.preview && item.preview.indexOf('blob:') === 0 && window.URL && URL.revokeObjectURL) {
          URL.revokeObjectURL(item.preview);
        }
      } catch (e) {}
    });
    _berniniRefsState = [];
    _renderBerniniRefsList();
    _setBerniniRefsUploading(false);
  }

function _resetMultiRefs() {
    _multiRefsInited = false;
    _multiRefsUploadPromises = [];
    _multiRefsState.forEach(function(item) {
      try {
        if (item && item.preview && item.preview.indexOf('blob:') === 0 && window.URL && URL.revokeObjectURL) {
          URL.revokeObjectURL(item.preview);
        }
      } catch (e) {}
    });
    _multiRefsState = [];
    _renderMultiRefsList();
    _setMultiRefsUploading(false);
  }

function _resetRefVideo() {
    _refVideoInited = false;
    _refVideoUploadPromise = null;
    _refVideoUploadToken += 1;
    var preview = $('#refVideoPreview');
    var placeholder = $('#refVideoPlaceholder');
    var valueInput = $('#refVideoValue');
    if (preview) { preview.removeAttribute('data-video-autofit'); preview.removeAttribute('src'); preview.load && preview.load(); preview.style.display = 'none'; preview.classList.add('hidden'); }
    if (placeholder) placeholder.style.display = '';
    if (valueInput) valueInput.value = '';
    _setRefVideoMetadata({});
    _setRefVideoUploading(false);
  }

function _resetRefAudio() {
    _refAudioInited = false;
    _refAudioUploadPromise = null;
    _refAudioUploadToken += 1;
    var preview = $('#refAudioPreview');
    var placeholder = $('#refAudioPlaceholder');
    var valueInput = $('#refAudioValue');
    var actions = $('#refAudioActions');
    var nameEl = $('#refAudioName');
    if (preview) { preview.removeAttribute('src'); preview.load && preview.load(); preview.style.display = 'none'; }
    if (placeholder) placeholder.style.display = '';
    if (valueInput) valueInput.value = '';
    if (actions) actions.classList.add('hidden');
    if (nameEl) nameEl.textContent = '';
    _setRefAudioUploading(false);
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

  function _uploadRefAudio(file) {
    var fd = new FormData();
    fd.append('file', file);
    var upload = (window.CW && window.CW.auth && typeof window.CW.auth.apiFetch === 'function')
      ? window.CW.auth.apiFetch(API + '/api/upload-audio', { method: 'POST', body: fd })
      : fetch(API + '/api/upload-audio', { method: 'POST', body: fd });
    return upload.then(_parseUploadResponse);
  }

  function _setRefVideoMetadata(meta) {
    var width = parseInt((meta && meta.width) || 0, 10) || 0;
    var height = parseInt((meta && meta.height) || 0, 10) || 0;
    var duration = parseFloat((meta && (meta.duration || meta.duration_seconds)) || 0) || 0;
    var fps = parseFloat((meta && (meta.fps || meta.frame_rate)) || 0) || 0;
    var frameCount = _videoFrameTotalFromMeta(meta);
    [$('#refVideoValue'), $('#refVideoPreview')].forEach(function(el) {
      if (!el) return;
      if (width && height) {
        el.setAttribute('data-video-width', String(width));
        el.setAttribute('data-video-height', String(height));
      } else {
        el.removeAttribute('data-video-width');
        el.removeAttribute('data-video-height');
      }
      if (duration) el.setAttribute('data-video-duration', String(duration));
      else el.removeAttribute('data-video-duration');
      if (fps) el.setAttribute('data-video-fps', String(fps));
      else el.removeAttribute('data-video-fps');
      if (frameCount) el.setAttribute('data-video-frame-count', String(frameCount));
      else el.removeAttribute('data-video-frame-count');
    });
  }

  function _showRefVideoFirstFrame(preview) {
    if (!preview) return;
    preview.classList.remove('hidden');
    preview.style.display = '';
    preview.muted = true;
    preview.preload = 'auto';
    preview.setAttribute('playsinline', 'playsinline');
    function seekFirstFrame() {
      try {
        preview.pause();
        var duration = Number(preview.duration || 0);
        var t = duration > 0 ? Math.min(0.05, Math.max(0.001, duration / 1000)) : 0.001;
        if (Number.isFinite(t)) preview.currentTime = t;
      } catch (e) {}
    }
    if (preview.readyState >= 1) {
      setTimeout(seekFirstFrame, 0);
    } else {
      preview.addEventListener('loadedmetadata', seekFirstFrame, { once: true });
    }
    preview.addEventListener('seeked', function() {
      try { preview.pause(); } catch (e) {}
    }, { once: true });
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

  function _setBerniniRefsUploading(uploading) {
    var zone = $('#berniniRefsZone');
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

  function _setMultiRefsUploading(uploading) {
    var zone = $('#multiRefsZone');
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

  function _setRefAudioUploading(uploading) {
    var zone = $('#refAudioZone');
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

  async function _waitForBerniniRefsUpload() {
    var pending = (_berniniRefsUploadPromises || []).filter(Boolean);
    if (!pending.length) return;
    if (window.CW && CW.toast) CW.toast('Bernini 参考图仍在上传，完成后继续提交', 'info');
    try {
      await Promise.all(pending);
    } catch (e) {
      throw new Error('Bernini 参考图上传失败，请重新上传后再出图');
    }
  }

  async function _waitForMultiRefsUpload() {
    var pending = (_multiRefsUploadPromises || []).filter(Boolean);
    if (!pending.length) return;
    if (window.CW && CW.toast) CW.toast('多参考图仍在上传，完成后继续提交', 'info');
    try {
      await Promise.all(pending);
    } catch (e) {
      throw new Error('多参考图上传失败，请重新上传后再出图');
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

  async function _waitForRefAudioUpload() {
    if (!_refAudioUploadPromise) return;
    if (window.CW && CW.toast) CW.toast('参考音频仍在上传，完成后继续提交', 'info');
    try {
      await _refAudioUploadPromise;
    } catch (e) {
      throw new Error('参考音频上传失败，请重新上传后再出图');
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
      if (_imageReferenceModeNeedsMultiRefs(_currentImageReferenceMode())) {
        _ensureMultiRefsStartWithSingleReference();
      }
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

  function _renderBerniniRefsList() {
    var list = $('#berniniRefsList');
    var placeholder = $('#berniniRefsPlaceholder');
    if (!list) {
      _syncBerniniRefsValue();
      return;
    }
    var items = _berniniRefsState || [];
    list.innerHTML = items.map(function(item, index) {
      var preview = item.preview || (item.filename ? API + '/api/input-image/' + encodeURIComponent(item.filename) : '');
      var status = item.uploading ? '<span class="bernini-ref-status">上传中</span>' : (item.error ? '<span class="bernini-ref-status error">失败</span>' : '');
      return '<div class="bernini-ref-item" data-index="' + index + '">'
        + (preview ? '<img src="' + escA(preview) + '" alt="Bernini reference">' : '<div class="bernini-ref-thumb"></div>')
        + status
        + '<button type="button" class="bernini-ref-remove" data-bernini-ref-remove="' + index + '" title="移除" aria-label="移除">×</button>'
        + '</div>';
    }).join('');
    if (placeholder) placeholder.style.display = items.length ? 'none' : '';
    _syncBerniniRefsValue();
    _syncBerniniRefsMode();
  }

  function _addBerniniRefFilename(filename) {
    filename = String(filename || '').trim();
    if (!filename) return;
    var exists = (_berniniRefsState || []).some(function(item) { return item && item.filename === filename; });
    if (exists) return;
    _berniniRefsState.push({
      id: ++_berniniRefsSeq,
      filename: filename,
      preview: API + '/api/input-image/' + encodeURIComponent(filename),
      uploading: false,
      error: false
    });
    _renderBerniniRefsList();
  }

  function _renderMultiRefsList() {
    var list = $('#multiRefsList');
    var placeholder = $('#multiRefsPlaceholder');
    if (!list) {
      _syncMultiRefsValue();
      return;
    }
    var items = _multiRefsState || [];
    list.innerHTML = items.map(function(item, index) {
      var preview = item.preview || (item.filename ? API + '/api/input-image/' + encodeURIComponent(item.filename) : '');
      var status = item.uploading ? '<span class="bernini-ref-status">上传中</span>' : (item.error ? '<span class="bernini-ref-status error">失败</span>' : '');
      return '<div class="bernini-ref-item multi-ref-item" data-index="' + index + '">'
        + (preview ? '<img src="' + escA(preview) + '" alt="multi reference">' : '<div class="bernini-ref-thumb"></div>')
        + status
        + '<button type="button" class="bernini-ref-remove" data-multi-ref-remove="' + index + '" title="移除" aria-label="移除">×</button>'
        + '</div>';
    }).join('');
    if (placeholder) placeholder.style.display = items.length ? 'none' : '';
    _syncMultiRefsValue();
    _syncImageReferenceModeUi();
  }

  function _addMultiRefFilename(filename) {
    filename = String(filename || '').trim();
    if (!filename) return;
    var exists = (_multiRefsState || []).some(function(item) { return item && item.filename === filename; });
    if (exists) return;
    _multiRefsState.push({
      id: ++_multiRefsSeq,
      filename: filename,
      preview: API + '/api/input-image/' + encodeURIComponent(filename),
      uploading: false,
      error: false
    });
    _renderMultiRefsList();
  }

  function _applyUploadedBerniniRefs(files, fileInput) {
    files = Array.prototype.slice.call(files || []).filter(Boolean);
    if (!files.length) return Promise.resolve([]);
    var slots = files.map(function(file) {
      var preview = '';
      try {
        if (window.URL && URL.createObjectURL) preview = URL.createObjectURL(file);
      } catch (e) {}
      var item = {
        id: ++_berniniRefsSeq,
        filename: '',
        preview: preview,
        uploading: true,
        error: false
      };
      _berniniRefsState.push(item);
      return { file: file, item: item };
    });
    _renderBerniniRefsList();
    _setBerniniRefsUploading(true);
    var uploads = slots.map(function(slot) {
      var promise = _uploadRefImage(slot.file).then(function(d) {
        slot.item.filename = d.filename;
        slot.item.uploading = false;
        if (!slot.item.preview) slot.item.preview = API + '/api/input-image/' + encodeURIComponent(d.filename);
        _renderBerniniRefsList();
        return d;
      }).catch(function(err) {
        slot.item.uploading = false;
        slot.item.error = true;
        _renderBerniniRefsList();
        throw err;
      });
      _berniniRefsUploadPromises.push(promise);
      promise.then(function() {
        _berniniRefsUploadPromises = _berniniRefsUploadPromises.filter(function(item) { return item !== promise; });
        _setBerniniRefsUploading(_berniniRefsUploadPromises.length > 0);
        if (fileInput) fileInput.value = '';
      }, function() {
        _berniniRefsUploadPromises = _berniniRefsUploadPromises.filter(function(item) { return item !== promise; });
        _setBerniniRefsUploading(_berniniRefsUploadPromises.length > 0);
        if (fileInput) fileInput.value = '';
      });
      return promise;
    });
    return Promise.all(uploads);
  }

  function _applyUploadedMultiRefs(files, fileInput) {
    files = Array.prototype.slice.call(files || []).filter(Boolean);
    if (!files.length) return Promise.resolve([]);
    var zone = $('#multiRefSection');
    var maxRefs = parseInt((zone && zone.getAttribute('data-max-refs')) || '3', 10) || 3;
    var remaining = Math.max(0, maxRefs - (_multiRefsState || []).length);
    if (files.length > remaining) {
      files = files.slice(0, remaining);
      if (window.CW && CW.toast) CW.toast('最多上传 ' + maxRefs + ' 张参考图', 'info');
    }
    if (!files.length) {
      if (fileInput) fileInput.value = '';
      return Promise.resolve([]);
    }
    var slots = files.map(function(file) {
      var preview = '';
      try {
        if (window.URL && URL.createObjectURL) preview = URL.createObjectURL(file);
      } catch (e) {}
      var item = {
        id: ++_multiRefsSeq,
        filename: '',
        preview: preview,
        uploading: true,
        error: false
      };
      _multiRefsState.push(item);
      return { file: file, item: item };
    });
    _renderMultiRefsList();
    _setMultiRefsUploading(true);
    var uploads = slots.map(function(slot) {
      var promise = _uploadRefImage(slot.file).then(function(d) {
        slot.item.filename = d.filename;
        slot.item.uploading = false;
        if (!slot.item.preview) slot.item.preview = API + '/api/input-image/' + encodeURIComponent(d.filename);
        if (!_imageReferenceModeNeedsMultiRefs(_currentImageReferenceMode())) {
          _syncSingleReferenceFromFirstMultiRef(true);
        }
        _renderMultiRefsList();
        return d;
      }).catch(function(err) {
        slot.item.uploading = false;
        slot.item.error = true;
        _renderMultiRefsList();
        throw err;
      });
      _multiRefsUploadPromises.push(promise);
      promise.then(function() {
        _multiRefsUploadPromises = _multiRefsUploadPromises.filter(function(item) { return item !== promise; });
        _setMultiRefsUploading(_multiRefsUploadPromises.length > 0);
        if (fileInput) fileInput.value = '';
      }, function() {
        _multiRefsUploadPromises = _multiRefsUploadPromises.filter(function(item) { return item !== promise; });
        _setMultiRefsUploading(_multiRefsUploadPromises.length > 0);
        if (fileInput) fileInput.value = '';
      });
      return promise;
    });
    return Promise.all(uploads);
  }

  function _applyUploadedRefVideo(file, fileInput, zone, preview, valueInput, placeholder) {
    if (!file) return Promise.resolve(null);
    var token = ++_refVideoUploadToken;
    if (valueInput) valueInput.value = '';
    if (preview) {
      preview.removeAttribute('data-video-autofit');
      preview.removeAttribute('src');
      preview.load && preview.load();
      preview.style.display = 'none';
      preview.classList.add('hidden');
    }
    if (placeholder) placeholder.style.display = '';
    _setRefVideoUploading(true);
    var upload = Promise.all([_uploadRefVideo(file), _readVideoFileMetadata(file)]).then(function(results) {
      var d = results[0];
      var meta = Object.assign({}, results[1] || {}, d || {});
      if (token !== _refVideoUploadToken) return d;
      if (valueInput) valueInput.value = d.filename;
      _setRefVideoMetadata(meta);
      if (meta.width && meta.height) _applyBestSizeForAspect(meta.width, meta.height);
      _autoFitVideoFrameControls(meta);
      if (preview) {
        preview.removeAttribute('data-video-autofit');
        preview.src = API + '/api/input-video/' + encodeURIComponent(d.filename);
        _showRefVideoFirstFrame(preview);
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

  function _applyUploadedRefAudio(file, fileInput, zone, preview, valueInput, placeholder, actions, nameEl) {
    if (!file) return Promise.resolve(null);
    var token = ++_refAudioUploadToken;
    if (valueInput) valueInput.value = '';
    if (actions) actions.classList.add('hidden');
    if (nameEl) nameEl.textContent = '';
    if (preview) {
      preview.removeAttribute('src');
      preview.load && preview.load();
      preview.style.display = 'none';
    }
    if (placeholder) placeholder.style.display = '';
    _setRefAudioUploading(true);
    var upload = _uploadRefAudio(file).then(function(d) {
      if (token !== _refAudioUploadToken) return d;
      if (valueInput) valueInput.value = d.filename;
      if (preview) {
        preview.src = API + '/api/input-audio/' + encodeURIComponent(d.filename);
        preview.style.display = '';
        preview.classList.remove('hidden');
        preview.load && preview.load();
      }
      if (nameEl) nameEl.textContent = (file && file.name) || d.filename || 'audio.wav';
      if (actions) actions.classList.remove('hidden');
      if (placeholder) placeholder.style.display = 'none';
      return d;
    }).finally(function() {
      if (token === _refAudioUploadToken) {
        _refAudioUploadPromise = null;
        _setRefAudioUploading(false);
      }
      if (fileInput) fileInput.value = '';
    });
    _refAudioUploadPromise = upload;
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

  function _initBerniniRefsZone() {
    if (_berniniRefsInited) {
      _syncBerniniRefsMode();
      _renderBerniniRefsList();
      return;
    }
    _berniniRefsInited = true;
    var zone = $('#berniniRefsZone');
    var fileInput = $('#berniniRefsFile');
    if (!zone || !fileInput) return;
    zone.addEventListener('click', function(e) {
      var removeBtn = e.target && e.target.closest ? e.target.closest('[data-bernini-ref-remove]') : null;
      if (removeBtn) {
        e.preventDefault();
        e.stopPropagation();
        var index = parseInt(removeBtn.getAttribute('data-bernini-ref-remove') || '-1', 10);
        if (index >= 0 && index < _berniniRefsState.length) {
          var removed = _berniniRefsState.splice(index, 1)[0];
          try {
            if (removed && removed.preview && removed.preview.indexOf('blob:') === 0 && window.URL && URL.revokeObjectURL) URL.revokeObjectURL(removed.preview);
          } catch (err) {}
          _renderBerniniRefsList();
        }
        return;
      }
      if (e.target && e.target.tagName === 'IMG') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', async function() {
      if (!fileInput.files.length) return;
      try {
        await _applyUploadedBerniniRefs(fileInput.files, fileInput);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
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
      var files = e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files : [];
      if (!files.length) return;
      try {
        await _applyUploadedBerniniRefs(files, fileInput);
      } catch (err) {
        alert('upload fail: ' + err.message);
      }
    });
    _syncBerniniRefsMode();
    _renderBerniniRefsList();
  }

  function _initMultiRefsZone() {
    if (_multiRefsInited) {
      _renderMultiRefsList();
      _syncImageReferenceModeUi();
      return;
    }
    _multiRefsInited = true;
    var zone = $('#multiRefsZone');
    var fileInput = $('#multiRefsFile');
    if (!zone || !fileInput) return;
    zone.addEventListener('click', function(e) {
      var removeBtn = e.target && e.target.closest ? e.target.closest('[data-multi-ref-remove]') : null;
      if (removeBtn) {
        e.preventDefault();
        e.stopPropagation();
        var index = parseInt(removeBtn.getAttribute('data-multi-ref-remove') || '-1', 10);
        if (index >= 0 && index < _multiRefsState.length) {
          var removed = _multiRefsState.splice(index, 1)[0];
          try {
            if (removed && removed.preview && removed.preview.indexOf('blob:') === 0 && window.URL && URL.revokeObjectURL) URL.revokeObjectURL(removed.preview);
          } catch (err) {}
          _renderMultiRefsList();
        }
        return;
      }
      if (e.target && e.target.tagName === 'IMG') return;
      fileInput.click();
    });
    fileInput.addEventListener('change', async function() {
      if (!fileInput.files.length) return;
      try {
        await _applyUploadedMultiRefs(fileInput.files, fileInput);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
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
      var files = e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files : [];
      if (!files.length) return;
      try {
        await _applyUploadedMultiRefs(files, fileInput);
      } catch (err) {
        alert('upload fail: ' + err.message);
      }
    });
    _renderMultiRefsList();
    _syncImageReferenceModeUi();
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
        var meta = Object.assign({}, _getRefVideoMetadata(), {
          width: preview.videoWidth || 0,
          height: preview.videoHeight || 0,
          duration: preview.duration || 0
        });
        _setRefVideoMetadata(meta);
        if (preview.getAttribute('data-video-autofit') === '0') {
          preview.removeAttribute('data-video-autofit');
        } else {
          if (meta.width && meta.height) _applyBestSizeForAspect(meta.width, meta.height);
          _autoFitVideoFrameControls(meta);
        }
        _showRefVideoFirstFrame(preview);
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

  function _initRefAudioZone() {
    if (_refAudioInited) return;
    _refAudioInited = true;
    var zone = $('#refAudioZone');
    var fileInput = $('#refAudioFile');
    var preview = $('#refAudioPreview');
    var valueInput = $('#refAudioValue');
    var placeholder = $('#refAudioPlaceholder');
    var actions = $('#refAudioActions');
    var nameEl = $('#refAudioName');
    var replaceBtn = $('#refAudioReplace');
    if (!zone || !fileInput) return;
    zone.addEventListener('click', function(e) {
      if (e.target.tagName === 'AUDIO') return;
      if (e.target.closest && e.target.closest('#refAudioActions')) return;
      fileInput.click();
    });
    fileInput.addEventListener('change', async function() {
      if (!fileInput.files.length) return;
      var file = fileInput.files[0];
      try {
        await _applyUploadedRefAudio(file, fileInput, zone, preview, valueInput, placeholder, actions, nameEl);
      } catch (e) {
        alert('upload fail: ' + e.message);
      }
    });
    if (replaceBtn) {
      replaceBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        fileInput.click();
      });
    }
    if (preview) {
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
        await _applyUploadedRefAudio(file, fileInput, zone, preview, valueInput, placeholder, actions, nameEl);
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
  window.CW.openPromptOptimizeMenu = openPromptOptimizeMenu;
  window.CW.closePromptOptimizeMenu = closePromptOptimizeMenu;
  window.CW.openPromptFullscreenEditor = openPromptFullscreenEditor;
  window.CW.closePromptFullscreenEditor = closePromptFullscreenEditor;
  window.CW.optimizePrompt = optimizePrompt;
  window.CW.translatePromptLanguage = translatePromptLanguage;
  window.CW.registerPromptTranslationPair = registerPromptTranslationPair;
  window.CW.preparePromptForQwenAngle = _preparePromptForCurrentQwenAngle;
  window.CW.clearPromptOptimizationVariants = _clearPromptOptimizationVariants;
  window.CW.interrogatePromptFromImage = interrogatePromptFromImage;
  window.CW.rerunPromptInterrogateFromResult = rerunPromptInterrogateFromResult;
  window.CW.openPromptInterrogateModal = openPromptInterrogateModal;
  window.CW.closePromptInterrogateModal = closePromptInterrogateModal;
  window.CW.renderAdvFields = renderAdvFields;
  window.CW.renderQuickGen = renderQuickGen;
  window.CW.renderQuickForm = renderQuickForm;
  window.CW.toggleDirectorPanel = toggleDirectorPanel;
  window.CW.setDirectorPlacementMode = _setDirectorPlacementMode;
  window.CW.removeDirectorShot = removeDirectorShot;
  window.CW.importDirectorPromptSegments = importDirectorPromptSegments;
  window.CW.selectDirectorShotImage = selectDirectorShotImage;
  window.CW.setVideoMode = setVideoMode;
  window.CW.toggleSeedRandom = toggleSeedRandom;
  window.CW.setSeedRandomEnabled = _setSeedRandomEnabled;
  window.CW.initRatioGrid = initRatioGrid;
  window.CW.highlightRatio = highlightRatio;
})();
