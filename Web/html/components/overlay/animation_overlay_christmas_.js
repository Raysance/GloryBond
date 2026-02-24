/* Christmas Overlay - 纯雪花（最小化、非阻塞、可完全清理）
   使用：在页面底部引入脚本，或添加 data-init 属性自动启动：
   <script src="/path/christmas-overlay.js" data-init='{"snowCount":36}'></script>
*/
(function(window, document){
  const defaultOpts = { snowCount: 40, snowSize: [6,14], zIndex: 99999, clickThrough: true };
  let opts = Object.assign({}, defaultOpts);
  let root = null;

  function injectCSS(){
    if (document.getElementById('christmas-overlay-style')) return;
    const css = `
    .christmas-overlay{position:fixed;inset:0;pointer-events:var(--co-pointer, none);z-index:var(--co-z, 99999);overflow:hidden}
    .christmas-overlay .snowflake{position:absolute;border-radius:50%;background:white;will-change:transform,opacity}
    .christmas-overlay .co-decoration{position:absolute;will-change:transform,opacity;user-select:none;cursor:default;filter:drop-shadow(0 2px 4px rgba(0,0,0,0.2))}
    @keyframes co-fall{0%{transform:translateY(-12vh) rotate(0deg);opacity:0}10%{opacity:1}100%{transform:translateY(110vh) rotate(360deg);opacity:0.95}}
    @keyframes co-pulse{0%,100%{opacity:0.3} 50%{opacity:1}}
    `;
    const s = document.createElement('style');
    s.id = 'christmas-overlay-style';
    s.textContent = css;
    document.head.appendChild(s);
  }

  function createOverlay(){
    injectCSS();
    if (root) hide();
    root = document.createElement('div');
    root.className = 'christmas-overlay';
    root.setAttribute('aria-hidden','true');
    root.style.setProperty('--co-z', String(opts.zIndex));
    root.style.setProperty('--co-pointer', opts.clickThrough ? 'none' : 'auto');

    const count = Math.max(0, parseInt(opts.snowCount,10) || 0);
    const minS = (opts.snowSize && opts.snowSize[0]) || 6;
    const maxS = (opts.snowSize && opts.snowSize[1]) || 14;

    for (let i=0;i<count;i++){
      const f = document.createElement('div');
      f.className = 'snowflake';
      const size = Math.round(minS + Math.random()*(maxS-minS));
      f.style.width = size + 'px';
      f.style.height = size + 'px';
      f.style.left = (Math.random()*100) + '%';
      f.style.top = (Math.random()*-120) + 'vh';
      f.style.opacity = (0.6 + Math.random()*0.4).toFixed(2);
      const dur = (6 + Math.random()*10).toFixed(2) + 's';
      const delay = (Math.random()*-10).toFixed(2) + 's';
      f.style.animation = `co-fall ${dur} linear ${delay} infinite`;
      root.appendChild(f);
    }

    // Add Decorations (Randomized & Static)
    const decoChars = ['🎄', '🎁', '🔔', '🧦', '⛄', '🦌', '🍪'];
    const decoCount = Math.floor(Math.random() * 4) + 8; // 8-11 items scattered
    
    // 2D Collision avoidance
    const placedPositions = []; // {x, y}
    
    for(let i=0; i<decoCount; i++){
      let x = 0, y = 0;
      let valid = false;
      let attempts = 0;
      
      // Try to find a non-overlapping position
      while(!valid && attempts < 50){
        x = Math.random() * 90 + 5; // 5% - 95%
        y = Math.random() * 90 + 5; // 5% - 95%
        valid = true;
        for(const p of placedPositions){
          // Calculate distance percentage
          const dist = Math.sqrt(Math.pow(p.x - x, 2) + Math.pow(p.y - y, 2));
          if(dist < 15){ // Minimum 15% distance radius
            valid = false;
            break;
          }
        }
        attempts++;
      }

      if(!valid) continue;
      placedPositions.push({x, y});

      const d = document.createElement('div');
      d.className = 'co-decoration';
      d.textContent = decoChars[Math.floor(Math.random() * decoChars.length)];
      d.style.fontSize = (12 + Math.random() * 12) + 'px'; // Smaller: 12-24px
      d.style.left = x + '%';
      d.style.top = y + '%';
      
      const dur = (2 + Math.random() * 4).toFixed(2) + 's';
      const delay = (Math.random() * -5).toFixed(2) + 's';
      d.style.animation = `co-pulse ${dur} ease-in-out ${delay} infinite`;
      
      // Randomly flip some items horizontally for variety
      if (Math.random() > 0.5) d.style.transform = 'scaleX(-1)';
      
      root.appendChild(d);
    }

    document.body.appendChild(root);
    return root;
  }

  function show(userOpts){
    opts = Object.assign({}, defaultOpts, opts, userOpts || {});
    if (root) hide();
    createOverlay();
  }

  function hide(){
    if (root){
      try{ root.remove(); }catch(e){}
      root = null;
    }
    const s = document.getElementById('christmas-overlay-style'); if (s) s.remove();
  }

  window.ChristmasOverlay = { init: show, show, hide };

  // auto-init from script tag data-init (修复：即使没有 data-init 也自动初始化)
  try{
    var scripts = document.getElementsByTagName('script');
    var cur = document.currentScript || (scripts[scripts.length-1] || null);
    if(!cur){
      for(var i=scripts.length-1;i>=0;i--){ var sc = scripts[i]; if(sc && sc.src && sc.src.indexOf('christmas-overlay.js') !== -1){ cur = sc; break; } }
    }
    var cfg = {};
    if(cur){
      var data = cur.getAttribute('data-init') || cur.getAttribute('data-init-json') || (cur.dataset && cur.dataset.init);
      if(data){
        try{ cfg = JSON.parse(data); }catch(e){ cfg = {}; }
      }
    }
    // 无论是否提供 data-init，都在短延迟后尝试 init，恢复脚本自动显示行为
    setTimeout(function(){ if(window.ChristmasOverlay && typeof window.ChristmasOverlay.init === 'function'){ window.ChristmasOverlay.init(cfg || {}); } }, 30);
  }catch(e){}

})(window, document);
