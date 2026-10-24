const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const observers = [];
class Element {
    constructor() { this.children = []; this.events = {}; this.style = {}; this.parent = null; }
    appendChild(child) { child.remove(); this.children.push(child); child.parent = this; }
    addEventListener(type, handler) { this.events[type] = handler; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; }
}
const scope = {
    WeakMap,
    document: {createElement: () => new Element()},
    window: {IntersectionObserver: true, addEventListener() {}, removeEventListener() {}},
    IntersectionObserver: class {
        constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
        observe() {}
        disconnect() { this.disconnected = true; }
    }
};
vm.createContext(scope);
vm.runInContext(fs.readFileSync('templates/CommonPages/battle_list_pager.js', 'utf8'), scope);
const container = new Element();
function renderer(total) {
    let rendered = 0;
    return size => {
        const end = Math.min(rendered + size, total);
        for (; rendered < end; rendered++) container.appendChild(new Element());
        return rendered < total;
    };
}
function cards() { return container.children.filter(c => c.className !== 'battle-load-more').length; }
scope.mountBattleListPager(container, renderer(55));
assert.equal(cards(), 20);
observers[0].callback([{isIntersecting: true}]);
assert.equal(cards(), 30);
observers[0].callback([{isIntersecting: true}]);
assert.equal(cards(), 40);
container.children = [];
scope.mountBattleListPager(container, renderer(25));
assert.equal(cards(), 20);
assert.equal(observers[0].disconnected, true);
observers[0].callback([{isIntersecting: true}]); // A queued callback from the old filter must do nothing.
assert.equal(cards(), 20);
observers[1].callback([{isIntersecting: true}]);
assert.equal(cards(), 25);
assert.equal(container.children.some(c => c.className === 'battle-load-more'), false);
assert.equal(observers[1].disconnected, true);
container.children = [];
scope.mountBattleListPager(container, renderer(0));
assert.equal(container.children.length, 0);
console.log('Battle list paging: 20 initially, +10 on demand, reset and completion passed');
