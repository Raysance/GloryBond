;(function (global) {
  'use strict';

  // Minimal, dependency-free inline LaTeX-like renderer
  // Supported subset: \frac{a}{b}, \cdot, \text{...}, ^exponent, braces {..}, and ignores \left/\right.

  function htmlEscape(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function readGroup(src, i) {
    // Read a {...} group; returns { content, end }
    if (src[i] !== '{') return { content: '', end: i };
    let depth = 0, start = i + 1, p = i;
    for (; p < src.length; p++) {
      const ch = src[p];
      if (ch === '{') depth++;
      else if (ch === '}') {
        depth--;
        if (depth === 0) {
          return { content: src.slice(start, p), end: p + 1 };
        }
      }
    }
    return { content: src.slice(start), end: src.length };
  }

  function startsWithAt(src, i, token) {
    return src.slice(i, i + token.length) === token;
  }

  function parseExpr(src, i) {
    let out = '';
    while (i < src.length) {
      const ch = src[i];
      if (ch === '}') break;

      if (ch === '\\') {
        // commands
        if (startsWithAt(src, i, '\\frac')) {
          i += 5;
          while (src[i] === ' ') i++;
          const g1 = readGroup(src, i);
          i = g1.end;
          while (src[i] === ' ') i++;
          const g2 = readGroup(src, i);
          i = g2.end;
          const num = parseExpr(g1.content, 0);
          const den = parseExpr(g2.content, 0);
          out += '(' + num + ')/(' + den + ')';
          continue;
        }
        if (startsWithAt(src, i, '\\cdot')) { i += 5; out += ' · '; continue; }
        if (startsWithAt(src, i, '\\text')) {
          i += 5; while (src[i] === ' ') i++;
          if (src[i] === '{') { const g = readGroup(src, i); i = g.end; out += htmlEscape(g.content); }
          else { out += 'text'; }
          continue;
        }
        if (startsWithAt(src, i, '\\left')) { i += 5; continue; }
        if (startsWithAt(src, i, '\\right')) { i += 6; continue; }
        i++; // unknown command: skip '\'
        continue;
      }

      if (ch === '^') {
        i++;
        while (src[i] === ' ') i++;
        let expo = '';
        if (src[i] === '{') { const g = readGroup(src, i); i = g.end; expo = parseExpr(g.content, 0); }
        else { expo = htmlEscape(src[i] || ''); i++; }
        out += '<sup>' + expo + '</sup>';
        continue;
      }

      if (ch === '{') { const g = readGroup(src, i); i = g.end; out += parseExpr(g.content, 0); continue; }

      if (ch === '\n' || ch === '\r' || ch === '\t') { i++; continue; }
      if (ch === '-') { out += '−'; i++; continue; }

      out += htmlEscape(ch);
      i++;
    }
    return out;
  }

  function renderInline(el, tex) {
    if (!el) return;
    const normalized = String(tex).replace(/\s+/g, ' ').trim();
    el.innerHTML = parseExpr(normalized, 0);
  }

  const api = { renderInline };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  else { global.LiteLaTeX = api; }

})(typeof window !== 'undefined' ? window : globalThis);
/* Legacy leftover (disabled)
  // Multiple CDN fallbacks
  const CSS_URLS = [
    // 本地优先（如已将 KaTeX 放入 assets/katex/）
    'assets/katex/katex.min.css',
    'https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css',
    'https://unpkg.com/katex@0.16.10/dist/katex.min.css',
    'https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.10/katex.min.css'
  ];
  const JS_URLS = [
    // 本地优先（如已将 KaTeX 放入 assets/katex/）
    'assets/katex/katex.min.js',
    'https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js',
    'https://unpkg.com/katex@0.16.10/dist/katex.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.10/katex.min.js'
  ];

  function injectCSS(url){
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    document.head.appendChild(link);
  }

  function loadScriptSequential(urls, onload, onfail){
    let i = 0;
    function tryNext(){
      if (i >= urls.length) { onfail && onfail(); return; }
      const s = document.createElement('script');
      s.src = urls[i++];
      s.async = true;
      s.onload = () => onload && onload();
      s.onerror = () => tryNext();
      document.head.appendChild(s);
    }
    tryNext();
  }

  function renderKatex(){
    if (!window.katex) return;
    const defsEl = document.getElementById('tex-defs');
    ;(function (global) {
      'use strict';

      function htmlEscape(s) {
        return String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      function readGroup(src, i) {
        // 读取以 { 开始的组，返回 {content, end}
        if (src[i] !== '{') return { content: '', end: i };
        let depth = 0, start = i + 1, p = i;
        for (; p < src.length; p++) {
          const ch = src[p];
          if (ch === '{') depth++;
          else if (ch === '}') {
            depth--;
            if (depth === 0) {
              return { content: src.slice(start, p), end: p + 1 };
            }
          }
        }
        // 不匹配时，容错为到结尾
        return { content: src.slice(start), end: src.length };
      }

      function startsWithAt(src, i, token) {
        return src.slice(i, i + token.length) === token;
      }

      function parseExpr(src, i) {
        let out = '';
        while (i < src.length) {
          const ch = src[i];

          // 结束条件：用于上层组解析
          if (ch === '}') break;

          // 控制序列
          if (ch === '\\') {
            // 常见命令分支
            if (startsWithAt(src, i, '\\frac')) {
              i += 5; // skip \\frac
              // 读取分子
              while (src[i] === ' ') i++;
              if (src[i] !== '{') { out += 'frac'; continue; }
              const g1 = readGroup(src, i);
              i = g1.end;
              // 读取分母
              while (src[i] === ' ') i++;
              if (src[i] !== '{') { out += ' / '; continue; }
              const g2 = readGroup(src, i);
              i = g2.end;
              const num = parseExpr(g1.content, 0);
              const den = parseExpr(g2.content, 0);
              out += '(' + num + ')/(' + den + ')';
              continue;
            }
            if (startsWithAt(src, i, '\\cdot')) {
              i += 5; out += ' · '; continue;
            }
            if (startsWithAt(src, i, '\\text')) {
              i += 5; while (src[i] === ' ') i++;
              if (src[i] === '{') {
                const g = readGroup(src, i); i = g.end;
                out += htmlEscape(g.content);
              } else {
                out += 'text';
              }
              continue;
            }
            if (startsWithAt(src, i, '\\left')) { i += 5; continue; }
            if (startsWithAt(src, i, '\\right')) { i += 6; continue; }
            // 未覆盖的命令：跳过反斜杠，仅输出后续字符
            i++;
            continue;
          }

          // 上标 ^
          if (ch === '^') {
            i++;
            // 跳过空格
            while (src[i] === ' ') i++;
            let expo = '';
            if (src[i] === '{') {
              const g = readGroup(src, i); i = g.end;
              expo = parseExpr(g.content, 0);
            } else {
              // 单字符指数
              expo = htmlEscape(src[i] || '');
              i++;
            }
            out += '<sup>' + expo + '</sup>';
            continue;
          }

          // 组 { ... }
          if (ch === '{') {
            const g = readGroup(src, i); i = g.end;
            out += parseExpr(g.content, 0);
            continue;
          }

          // 普通字符
          if (ch === '\n' || ch === '\r' || ch === '\t') { i++; continue; }
          // 使用 Unicode 负号美化
          if (ch === '-') { out += '−'; i++; continue; }

          out += htmlEscape(ch);
          i++;
        }
        return out;
      }

      function renderInline(el, tex) {
        if (!el) return;
        const normalized = String(tex).replace(/\s+/g, ' ').trim();
        const html = parseExpr(normalized, 0);
        el.innerHTML = html;
      }

      const api = { renderInline };
      if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
      } else {
        global.LiteLaTeX = api;
      }
  })(typeof window !== 'undefined' ? window : globalThis);
*/
