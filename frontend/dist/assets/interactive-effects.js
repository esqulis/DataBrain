/* =====================================================================
 * DataBrain Interactive Effects v1.0.0
 * 外挂式增量互动增强：
 *   - 不修改原打包代码；事件全部委托，不拦截/不阻止任何原生交互；
 *   - 单一命名空间 window.DataBrainFX，支持 destroy() 完全卸载；
 *   - 重复加载自动去重；系统"减弱动效"开启时自动降级。
 * 手工 API：
 *   DataBrainFX.thinking.show()  在对话区显示"AI 正在思考"三点动画
 *   DataBrainFX.thinking.hide()  移除
 *   DataBrainFX.destroy()        卸载全部效果
 * ===================================================================== */
(function () {
  'use strict';

  var VERSION = '1.0.0';

  /* 重复加载：同版本直接跳过；旧版本先卸载 */
  if (window.DataBrainFX) {
    if (window.DataBrainFX.version === VERSION) return;
    if (typeof window.DataBrainFX.destroy === 'function') {
      try { window.DataBrainFX.destroy(); } catch (e) { /* noop */ }
    }
  }

  var doc = document;
  var rootEl = doc.documentElement;
  var win = window;

  var reduced = false;
  try {
    reduced = !!(win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch (e) { /* noop */ }

  /* ---------------- 资源登记（供 destroy 使用） ---------------- */
  var listeners = [];   // [target, type, fn, options]
  var observers = [];   // MutationObserver / IntersectionObserver
  var timers = [];      // setTimeout / setInterval ids
  var ownedNodes = [];  // 脚本创建的 DOM 节点
  var restored = [];    // [fn] 卸载时执行的恢复函数

  function on(target, type, fn, options) {
    if (!target) return;
    target.addEventListener(type, fn, options);
    listeners.push([target, type, fn, options]);
  }
  function later(fn, ms) {
    var id = setTimeout(fn, ms);
    timers.push(id);
    return id;
  }
  function every(fn, ms) {
    var id = setInterval(fn, ms);
    timers.push(id);
    return id;
  }
  function own(node) { ownedNodes.push(node); return node; }
  function qs(sel, ctx) { try { return (ctx || doc).querySelector(sel); } catch (e) { return null; } }
  function qsa(sel, ctx) {
    try { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }
    catch (e) { return []; }
  }
  function closest(el, sel) {
    if (!el || el.nodeType !== 1) return null;
    return el.closest ? el.closest(sel) : null;
  }
  function safe(fn) { try { fn(); } catch (e) { /* 单项失败不影响整体 */ } }

  /* 开启 CSS 作用域 */
  rootEl.classList.add('fx-on');
  if (reduced) rootEl.classList.add('fx-reduced');

  /* 跟随系统"减弱动效"变化 */
  var mq = null;
  try {
    mq = win.matchMedia('(prefers-reduced-motion: reduce)');
    var mqHandler = function (ev) {
      reduced = !!ev.matches;
      rootEl.classList.toggle('fx-reduced', reduced);
    };
    if (mq.addEventListener) {
      mq.addEventListener('change', mqHandler);
      restored.push(function () { mq.removeEventListener('change', mqHandler); });
    }
  } catch (e) { /* noop */ }

  /* ================= 1. 鼠标跟随光晕 ================= */
  function initGlow() {
    if (reduced) return;
    var glow = own(doc.createElement('div'));
    glow.id = 'fx-glow';
    doc.body.appendChild(glow);

    var raf = 0, px = -999, py = -999;
    function render() {
      raf = 0;
      glow.style.transform = 'translate(' + (px - 260) + 'px,' + (py - 260) + 'px)';
    }
    on(doc, 'pointermove', function (e) {
      if (e.pointerType === 'touch') return;
      px = e.clientX; py = e.clientY;
      glow.classList.add('fx-visible');
      if (!raf) raf = requestAnimationFrame(render);
    }, { passive: true });
    on(doc, 'pointerleave', function () { glow.classList.remove('fx-visible'); }, { passive: true });
    on(doc, 'pointerdown', function () { glow.classList.add('fx-visible'); }, { passive: true });
  }

  /* ================= 2. 按钮涟漪（委托，不改写任何默认行为） ================= */
  var RIPPLE_SEL = [
    'button', 'a[href]', '[role="button"]',
    '.btn', '.el-button', '.btn-primary', '.btn-secondary', '.btn-ghost',
    '.header-btn', '.chat-suggestion-chip', '.auth-switch',
    '.el-menu-item', '.el-sub-menu__title', '.el-tab__item'
  ].join(',');

  function initRipple() {
    on(doc, 'pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0) return;
      var t = closest(e.target, RIPPLE_SEL);
      if (!t || t.disabled || closest(t, '.is-disabled,[disabled]')) return;
      safe(function () {
        var rect = t.getBoundingClientRect();
        if (rect.width < 12 || rect.height < 12) return;
        var cs = win.getComputedStyle(t);
        var fixPos = false, fixOf = false;
        if (cs.position === 'static') { t.style.position = 'relative'; fixPos = true; }
        if (cs.overflow === 'visible') { t.style.overflow = 'hidden'; fixOf = true; }
        t.__fxRipples = (t.__fxRipples || 0) + 1;

        var d = Math.max(rect.width, rect.height) * 2.1;
        var s = doc.createElement('span');
        s.className = 'fx-ripple';
        s.style.width = s.style.height = d + 'px';
        s.style.left = (e.clientX - rect.left - d / 2) + 'px';
        s.style.top = (e.clientY - rect.top - d / 2) + 'px';
        t.appendChild(s);

        setTimeout(function () {
          if (s.parentNode) s.parentNode.removeChild(s);
          t.__fxRipples -= 1;
          if (t.__fxRipples <= 0) {
            t.__fxRipples = 0;
            if (fixPos) t.style.position = '';
            if (fixOf) t.style.overflow = '';
          }
        }, 700);
      });
    }, true);
  }

  /* ================= 3. 卡片悬停 3D 微倾斜 ================= */
  var TILT_SEL = '.brain-card,.chart-card,.el-card,.auth-card,.feature-item,.chat-chart-box,.brain-stat';

  function initTilt() {
    if (reduced) return;
    var raf = 0, cur = null;

    function apply(e, el) {
      var rect = el.getBoundingClientRect();
      var dx = (e.clientX - rect.left) / rect.width - 0.5;
      var dy = (e.clientY - rect.top) / rect.height - 0.5;
      el.style.transform =
        'perspective(720px) rotateX(' + (-dy * 5).toFixed(2) + 'deg) rotateY(' + (dx * 5).toFixed(2) + 'deg)';
    }
    on(doc, 'mouseover', function (e) {
      var el = closest(e.target, TILT_SEL);
      if (!el || el.__fxTiltSkip) return;
      safe(function () {
        /* 若元素自身已用 transform 定位/动画，则不叠加，避免冲突 */
        var cs = win.getComputedStyle(el);
        if (cs.transform !== 'none') { el.__fxTiltSkip = true; return; }
        el.classList.add('fx-tiltable');
        el.classList.add('fx-tilting');
      });
    }, { passive: true });
    on(doc, 'mousemove', function (e) {
      var el = closest(e.target, TILT_SEL);
      if (!el || el.__fxTiltSkip || !el.classList.contains('fx-tilting')) return;
      cur = [e, el];
      if (!raf) {
        raf = requestAnimationFrame(function () {
          raf = 0;
          if (cur) safe(function () { apply(cur[0], cur[1]); });
        });
      }
    }, { passive: true });
    on(doc, 'mouseout', function (e) {
      var el = closest(e.target, TILT_SEL);
      if (!el || !el.classList.contains('fx-tilting')) return;
      if (e.relatedTarget && el.contains(e.relatedTarget)) return;
      el.classList.remove('fx-tilting');
      el.style.transform = '';
    }, { passive: true });
  }

  /* ================= 4. 侧边栏：滑动指示条 + 悬停底纹 ================= */
  var sidebar = null;
  var navItems = [];
  var indicator = null;

  function findSidebar() {
    var logo = qs('.sidebar-logo');
    if (logo) {
      var el = logo.parentElement;
      while (el && el !== doc.body) {
        if (el.querySelectorAll('li, a, [class*="item"]').length >= 3) return el;
        el = el.parentElement;
      }
    }
    var cand = qs('.sidebar, aside, [class*="sidebar"]:not(.sidebar-logo), .el-menu');
    if (cand && cand.querySelectorAll('li, a, [class*="item"]').length >= 3) return cand;
    return null;
  }

  function collectNavItems() {
    if (!sidebar) return [];
    var out = [];
    var cands = qsa('li, a, [class*="item"], [class*="menu"] > *', sidebar);
    for (var i = 0; i < cands.length; i++) {
      var el = cands[i];
      if (closest(el, '.sidebar-logo')) continue;
      if (el.querySelector('li, a, [class*="item"]')) continue; // 只取叶子项
      var txt = (el.textContent || '').trim();
      if (!txt || txt.length > 24) continue;
      var r = el.getBoundingClientRect();
      if (r.height < 26 || r.height > 76 || r.width < 48) continue;
      var cs = win.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      out.push(el);
    }
    return out;
  }

  function placeIndicator(target) {
    if (!indicator || !sidebar) return;
    var sRect = sidebar.getBoundingClientRect();
    var tRect = target.getBoundingClientRect();
    indicator.style.height = Math.min(tRect.height, 46) + 'px';
    indicator.style.transform =
      'translateY(' + (tRect.top - sRect.top + sidebar.scrollTop + (tRect.height - Math.min(tRect.height, 46)) / 2) + 'px)';
    indicator.style.opacity = '1';
  }

  function initSidebarFX() {
    sidebar = findSidebar();
    if (!sidebar) return false;
    safe(function () {
      if (win.getComputedStyle(sidebar).position === 'static') sidebar.style.position = 'relative';
    });
    navItems = collectNavItems();
    if (navItems.length < 2) return false;

    indicator = own(doc.createElement('div'));
    indicator.id = 'fx-nav-indicator';
    sidebar.appendChild(indicator);

    for (var i = 0; i < navItems.length; i++) navItems[i].classList.add('fx-nav-item');

    on(sidebar, 'mouseover', function (e) {
      var it = closest(e.target, '.fx-nav-item');
      if (it) placeIndicator(it);
    }, { passive: true });
    on(sidebar, 'mouseleave', function () {
      var act = qs('.fx-nav-item.active, .fx-nav-item.is-active, .fx-nav-item.current', sidebar);
      if (act) placeIndicator(act);
      else if (indicator) indicator.style.opacity = '0';
    }, { passive: true });

    /* 初始定位到当前激活项 */
    var act = qs('.fx-nav-item.active, .fx-nav-item.is-active, .fx-nav-item.current', sidebar);
    if (act) placeIndicator(act);
    return true;
  }

  /* ================= 5. 侧栏折叠手柄 ================= */
  var sbToggle = null;
  var sbSaved = null;

  function sidebarWidth() {
    return sidebar ? sidebar.getBoundingClientRect().width : 0;
  }
  function placeSbToggle() {
    if (!sbToggle || !sidebar) return;
    sbToggle.style.left = Math.max(0, sidebarWidth() - 1) + 'px';
  }

  function initSidebarCollapse() {
    if (!sidebar) return;
    sbToggle = own(doc.createElement('button'));
    sbToggle.id = 'fx-sb-toggle';
    sbToggle.type = 'button';
    sbToggle.title = '收起 / 展开侧栏';
    sbToggle.textContent = '◀';
    doc.body.appendChild(sbToggle);
    placeSbToggle();
    on(win, 'resize', placeSbToggle, { passive: true });

    on(sbToggle, 'click', function () {
      safe(function () {
        var w = sidebarWidth();
        if (!sbSaved) {
          /* 保存原始状态 */
          sbSaved = {
            width: sidebar.style.width,
            flex: sidebar.style.flex,
            transition: sidebar.style.transition,
            compensated: []
          };
          var wPx = Math.round(w) + 'px';
          /* 为补偿内容区：找到 marginLeft 恰等于侧栏宽度的容器 */
          qsa('.content, main, [class*="main-content"], [class*="app-main"]')
            .forEach(function (el) {
              var ml = win.getComputedStyle(el).marginLeft;
              if (parseFloat(ml) === w) {
                sbSaved.compensated.push([el, el.style.marginLeft, ml]);
                el.style.transition = 'margin-left 0.3s ease';
                el.style.marginLeft = '72px';
              }
            });
          sidebar.style.transition = 'width 0.3s ease';
          sidebar.style.flex = sidebar.style.flex || '0 0 auto';
          sidebar.style.width = '72px';
          sidebar.classList.add('fx-sb-collapsed');
          sbToggle.textContent = '▶';
        } else {
          sidebar.style.width = sbSaved.width || '';
          if (sbSaved.flex) sidebar.style.flex = sbSaved.flex;
          sidebar.classList.remove('fx-sb-collapsed');
          sbSaved.compensated.forEach(function (rec) {
            rec[0].style.marginLeft = rec[1] || '';
          });
          sbSaved = null;
          sbToggle.textContent = '◀';
        }
        later(placeSbToggle, 320);
      });
    });
  }

  /* ================= 6. 对话消息入场动画（MutationObserver） ================= */
  var MSG_SEL = '.chat-msg, .chat-msg-content';

  function initMsgAnim() {
    var mo = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var n = added[j];
          if (n.nodeType !== 1) continue;
          safe(function () {
            var targets = [];
            if (n.matches && n.matches(MSG_SEL)) targets.push(n);
            targets = targets.concat(qsa(MSG_SEL, n));
            targets.forEach(function (el) {
              if (el.__fxMsgDone) return;
              el.__fxMsgDone = true;
              if (!reduced) el.classList.add('fx-msg-in');
            });
          });
        }
      }
    });
    mo.observe(doc.body, { childList: true, subtree: true });
    observers.push(mo);
  }

  /* ================= 7. “AI 正在思考”三点动画（API + 自动侦测） ================= */
  var thinkingEl = null;

  function showThinking(containerSel) {
    if (thinkingEl) return thinkingEl;
    var host = qs(containerSel || '.chat-messages') || qs('.chat-container') || doc.body;
    var el = doc.createElement('div');
    el.className = 'fx-thinking';
    el.setAttribute('aria-live', 'polite');
    el.innerHTML = '<i></i><i></i><i></i>';
    host.appendChild(el);
    thinkingEl = el;
    return el;
  }
  function hideThinking() {
    if (thinkingEl && thinkingEl.parentNode) thinkingEl.parentNode.removeChild(thinkingEl);
    thinkingEl = null;
  }
  function initThinkingAuto() {
    /* 对话区出现 Element Plus 加载遮罩时自动显示三点动画 */
    var autoShown = false;
    var mo = new MutationObserver(function () {
      safe(function () {
        var loading = qs('.chat-container .el-loading-mask, .chat-messages .el-loading-mask');
        if (loading && !autoShown && !thinkingEl) {
          showThinking('.chat-messages');
          if (thinkingEl) thinkingEl.setAttribute('data-fx-auto', '1');
          autoShown = true;
        } else if (!loading && autoShown) {
          if (thinkingEl && thinkingEl.getAttribute('data-fx-auto')) hideThinking();
          autoShown = false;
        }
      });
    });
    mo.observe(doc.body, { childList: true, subtree: true });
    observers.push(mo);
  }

  /* ================= 8. 数字滚动动画 ================= */
  var NUM_SEL = '.brain-stat-value, .el-statistic__number, [class*="stat-value"], [class*="metric-value"]';
  var io = null;

  function animateNumber(el) {
    var raw = el.__fxNumRaw;
    var m = raw.match(/^([^\d\-]*)(-?[\d,]+(?:\.\d+)?)([\s\S]*)$/);
    if (!m) return;
    var prefix = m[1], numStr = m[2], suffix = m[3];
    var target = parseFloat(numStr.replace(/,/g, ''));
    if (!isFinite(target)) return;
    var dec = (numStr.split('.')[1] || '').length;
    var useGroup = numStr.indexOf(',') !== -1;
    function fmt(v) {
      var s = useGroup
        ? v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
        : v.toFixed(dec);
      return prefix + s + suffix;
    }
    var dur = 900, t0 = null;
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * eased);
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = raw;
    }
    requestAnimationFrame(step);
  }

  function scanNumbers() {
    if (reduced) return;
    qsa(NUM_SEL).forEach(function (el) {
      if (el.__fxNumDone) return;
      var txt = (el.textContent || '').trim();
      if (!/^[^\d\-]*-?[\d,]+(\.\d+)?[%％]?$/.test(txt) || txt.length > 16) return;
      el.__fxNumDone = true;
      el.__fxNumRaw = txt;
      if (io) io.observe(el);
      else animateNumber(el);
    });
  }

  function initCountUp() {
    if (reduced) return;
    if ('IntersectionObserver' in win) {
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            io.unobserve(en.target);
            safe(function () { animateNumber(en.target); });
          }
        });
      }, { threshold: 0.4 });
      observers.push(io);
    }
    scanNumbers();
  }

  /* ================= 9. 表格行点击选中 ================= */
  function initRowSelect() {
    on(doc, 'click', function (e) {
      var tr = closest(e.target, '.el-table__body tr, .data-table tbody tr');
      if (!tr) return;
      /* 不干扰输入控件/按钮/链接自身的点击 */
      if (closest(e.target, 'input, button, a, .el-checkbox, .el-radio, select, textarea')) return;
      tr.classList.toggle('fx-row-sel');
    }, { passive: true });
  }

  /* ================= 10. 页面切换淡入 ================= */
  function initRouteFade() {
    var app = qs('#app');
    if (!app) return;
    var tid = 0;
    function fade() {
      if (reduced) return;
      app.classList.remove('fx-page-enter');
      /* 强制重排以便重复触发 */
      void app.offsetWidth;
      app.classList.add('fx-page-enter');
      if (tid) clearTimeout(tid);
      tid = later(function () { app.classList.remove('fx-page-enter'); }, 420);
    }
    ['pushState', 'replaceState'].forEach(function (k) {
      var orig = history[k];
      if (typeof orig !== 'function') return;
      history[k] = function () {
        var r = orig.apply(this, arguments);
        safe(fade);
        return r;
      };
      restored.push(function () { history[k] = orig; });
    });
    on(win, 'popstate', fade, { passive: true });
    on(win, 'hashchange', fade, { passive: true });
  }

  /* ================= 11. 回到顶部 ================= */
  var backtop = null;

  function findScrollable() {
    var list = qsa('.chat-messages, .content, [class*="main"], [class*="container"], [class*="scroll"]');
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el.scrollHeight > el.clientHeight + 60) {
        var oy = win.getComputedStyle(el).overflowY;
        if (oy === 'auto' || oy === 'scroll') out.push(el);
      }
    }
    return out;
  }
  function maxScrollNow() {
    var m = win.pageYOffset || doc.documentElement.scrollTop || 0;
    findScrollable().forEach(function (el) { if (el.scrollTop > m) m = el.scrollTop; });
    return m;
  }
  function onScrollCheck() {
    if (!backtop) return;
    backtop.classList.toggle('fx-show', maxScrollNow() > 400);
  }
  function initBacktop() {
    if (qs('.el-backtop')) return; /* 应用已自带则不重复 */
    backtop = own(doc.createElement('button'));
    backtop.id = 'fx-backtop';
    backtop.type = 'button';
    backtop.title = '回到顶部';
    backtop.setAttribute('aria-label', '回到顶部');
    backtop.textContent = '↑';
    doc.body.appendChild(backtop);
    on(win, 'scroll', onScrollCheck, { passive: true, capture: true });
    on(backtop, 'click', function () {
      safe(function () {
        var best = null, bestTop = 0;
        findScrollable().forEach(function (el) {
          if (el.scrollTop > bestTop) { bestTop = el.scrollTop; best = el; }
        });
        var docTop = win.pageYOffset || doc.documentElement.scrollTop || 0;
        if (docTop >= bestTop) win.scrollTo({ top: 0, behavior: 'smooth' });
        if (best) best.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  }

  /* ================= 装配 ================= */
  function initGlobal() {
    safe(initGlow);
    safe(initRipple);
    safe(initTilt);
    safe(initMsgAnim);
    safe(initThinkingAuto);
    safe(initCountUp);
    safe(initRowSelect);
    safe(initRouteFade);
  }

  function initSidebarFeatures() {
    var ok = false;
    safe(function () { ok = initSidebarFX(); });
    if (ok) safe(initSidebarCollapse);
    return ok;
  }

  /* 等 Vue 挂载完成后再探测侧栏；轮询最多 ~10s */
  var bootedSidebar = false;
  function boot() {
    initGlobal();
    safe(initBacktop);
    bootedSidebar = initSidebarFeatures();
    if (!bootedSidebar) {
      var tries = 0;
      every(function () {
        tries += 1;
        if (bootedSidebar || tries > 20) return;
        bootedSidebar = initSidebarFeatures();
        if (bootedSidebar) safe(placeSbToggle);
      }, 500);
    }
    /* 动态内容重扫：数字 / 侧栏 / 返回顶部 */
    var scanT = 0;
    var mo = new MutationObserver(function () {
      if (scanT) return;
      scanT = later(function () {
        scanT = 0;
        safe(scanNumbers);
        if (!bootedSidebar) bootedSidebar = initSidebarFeatures();
        safe(placeSbToggle);
      }, 350);
    });
    mo.observe(doc.body, { childList: true, subtree: true });
    observers.push(mo);
  }

  /* ---------------- 卸载 ---------------- */
  function destroy() {
    listeners.forEach(function (rec) { rec[0].removeEventListener(rec[1], rec[2], rec[3]); });
    listeners.length = 0;
    observers.forEach(function (o) { try { o.disconnect(); } catch (e) {} });
    observers.length = 0;
    timers.forEach(function (id) { clearTimeout(id); clearInterval(id); });
    timers.length = 0;
    restored.forEach(function (fn) { safe(fn); });
    restored.length = 0;
    ownedNodes.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    ownedNodes.length = 0;
    hideThinking();
    qsa('.fx-tiltable, .fx-tilting').forEach(function (el) {
      if (el.style) el.style.transform = '';
      el.classList.remove('fx-tiltable', 'fx-tilting');
    });
    qsa('.fx-msg-in, .fx-nav-item, .fx-row-sel').forEach(function (el) {
      el.classList.remove('fx-msg-in', 'fx-nav-item', 'fx-row-sel');
    });
    var app = qs('#app');
    if (app) app.classList.remove('fx-page-enter');
    rootEl.classList.remove('fx-on', 'fx-reduced');
    window.DataBrainFX = undefined;
  }

  /* ---------------- 暴露 API 并启动 ---------------- */
  window.DataBrainFX = {
    version: VERSION,
    destroy: destroy,
    rescan: function () { safe(scanNumbers); safe(placeSbToggle); },
    thinking: { show: showThinking, hide: hideThinking }
  };

  function start() {
    if (doc.body) boot();
    else {
      doc.addEventListener('DOMContentLoaded', function once() {
        doc.removeEventListener('DOMContentLoaded', once);
        boot();
      });
    }
  }
  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', function once() {
      doc.removeEventListener('DOMContentLoaded', once);
      start();
    });
  } else {
    start();
  }
})();
