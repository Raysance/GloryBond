// Only create cards as the reader reaches the end of the current batch.
const battleListPagers = new WeakMap();
function mountBattleListPager(container, renderBatch) {
    battleListPagers.get(container)?.();
    let active = true;
    let observer = null;
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'battle-load-more';
    more.textContent = '加载更多';
    more.style.cssText = 'display:block;margin:16px auto;padding:10px 24px;border:1px solid #b7cce2;border-radius:18px;background:#fff;color:#456889;cursor:pointer';
    function dispose() {
        active = false;
        observer?.disconnect();
        window.removeEventListener('scroll', checkBottom);
        more.remove();
    }
    function loadMore() {
        if (!active) return;
        more.remove();
        if (renderBatch(10)) container.appendChild(more);
        else dispose();
    }
    function checkBottom() {
        if (active && more.getBoundingClientRect().top <= window.innerHeight) loadMore();
    }
    battleListPagers.set(container, dispose);
    if (!renderBatch(20)) { dispose(); return; }
    container.appendChild(more);
    more.addEventListener('click', loadMore);
    if ('IntersectionObserver' in window) {
        observer = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) loadMore();
        });
        observer.observe(more);
    } else {
        window.addEventListener('scroll', checkBottom, {passive: true});
    }
}
