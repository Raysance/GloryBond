const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

// In-memory DOM only: no browser, network, or live agent requests.
class Node {
  constructor(tag = '') {this.tagName = tag.toUpperCase(); this.className = ''; this.children = []; this.attributes = {}; this.listeners = {}; this.value = '';}
  set textContent(value) {this.value = String(value); this.children = [];}
  get textContent() {return this.value + this.children.map(child => child.textContent).join('');}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.value = ''; this.children = nodes;}
  setAttribute(key, value) {this.attributes[key] = value;}
  addEventListener(kind, listener) {this.listeners[kind] = listener;}
}
const context = {document:{createElement:tag => new Node(tag), createTextNode:value => {const node = new Node(); node.textContent = value; return node;}}, navigator:{clipboard:{writeText:async value => {context.copied = value;}}}};
vm.createContext(context);
vm.runInContext(readFileSync(join(__dirname, '../templates/CommonPages/ChatTrace/conversation.js'), 'utf8') + '\nglobalThis.viewer = ChatTraceConversation;', context);
const viewer = context.viewer;
const nodes = root => [root, ...root.children.flatMap(nodes)];
const byClass = (root, name) => nodes(root).filter(node => node.className.split(' ').includes(name));
const event = (id, kind, text, extra = {}) => ({id, kind:'output.message', data:{kind, text, ...extra}});

test('persisted replies preserve order and both versions without duplicating the final answer', () => {
  const trace = {answer:'short', events:[event('a','progress','working'), event('b','final','short',
    {variants:{detailed:'long', chat:'short'}, presentation:{role_name:'安琪拉'}}), event('b','final','short')]};
  const result = viewer.messages(trace);
  assert.deepEqual(Array.from(result, reply => reply.text), ['working','short']);
  assert.equal(result[1].variants.detailed, 'long');
  assert.equal(result[1].roleName, '安琪拉');
});

test('old and failed traces retain their saved answer alongside partial messages', () => {
  assert.equal(viewer.messages({answer:'legacy'})[0].text, 'legacy');
  const legacy = {answer:'legacy', events:{}};
  const root = new Node('div');
  viewer.render(legacy, root);
  assert.equal(byClass(root,'answer')[0].textContent, 'legacy');
  const replies = viewer.messages({answer:'failure fallback', events:[event('a','partial','data retrieved')]});
  assert.deepEqual(Array.from(replies, reply => reply.text), ['data retrieved','failure fallback']);
  assert.match(viewer.messages({})[0].text, /未保存最终回复/);
});

test('transient messages and duplicate event IDs never add extra replies', () => {
  const transient = {...event('a','progress','stream'), transient:true};
  assert.deepEqual(Array.from(viewer.messages({answer:'saved', events:[transient]}), reply => reply.text), ['saved']);
});

test('cancelled runs and fixed notifications do not invent or repeat a final reply', () => {
  const partial = event('a', 'partial', 'already delivered');
  assert.deepEqual(Array.from(viewer.messages({status:'cancelled', answer:'already delivered', events:[partial]}),
    reply => reply.text), ['already delivered']);
  assert.equal(viewer.messages({status:'cancelled', events:[]}).length, 0);
  assert.deepEqual(Array.from(viewer.messages({status:'ok', answer:'reminder', events:[event('b', 'notification', 'reminder')]}),
    reply => reply.text), ['reminder']);
});

test('usage counts actual API responses once, excludes cache subsets and flags missing requests', () => {
  const report = viewer.usage({summary:{token_usage:{total_tokens:999}}, rounds:[
    {index:1, response_meta:{usage:{prompt_tokens:100, completion_tokens:20, total_tokens:120, prompt_cache_hit_tokens:70}}},
    {index:2, response_payload:{usage:{prompt_tokens:10, completion_tokens:5, total_tokens:15}}},
    {index:3, status:'error'},
  ]});
  assert.equal(report.totals.total_tokens, 135);
  assert.equal(report.totals.prompt_tokens, 110);
  assert.equal(report.totals.prompt_cache_hit_tokens, 70);
  assert.equal(report.incomplete, true);
});

test('unknown usage is distinct from explicit zero and failed-request default summaries', () => {
  assert.equal(viewer.usage({}).totals.total_tokens, null);
  assert.equal(viewer.usage({rounds:[{index:1}], summary:{token_usage:{total_tokens:0}}}).totals.total_tokens, null);
  assert.equal(viewer.usage({rounds:[{index:1, response_meta:{usage:{total_tokens:0}}}]}).totals.total_tokens, 0);
  assert.equal(viewer.usage({summary:{token_usage:{total_tokens:42}}}).totals.total_tokens, 42);
});

test('Markdown improves readability while HTML and non-HTTP links remain inert text', () => {
  const root = viewer.markdown('# Heading\n**Bold** and `code`\n- List\n| Item | Value |\n| --- | --- |\n| a | b |\n```python\nprint(1)\n```\n<img src=x onerror=alert(1)>\n[unsafe](javascript:alert(1))\n[safe](https://example.com)');
  const tags = nodes(root).map(node => node.tagName);
  for (const tag of ['H2','STRONG','CODE','UL','TABLE','PRE']) assert.ok(tags.includes(tag));
  assert.ok(!tags.includes('IMG'));
  assert.ok(root.textContent.includes('<img src=x onerror=alert(1)>'));
  const links = nodes(root).filter(node => node.tagName === 'A');
  assert.equal(links.length, 1);
  assert.equal(links[0].href, 'https://example.com');
  assert.equal(links[0].rel, 'noopener noreferrer');
});

test('conversation renders the saved role, dual replies, progress, and a copy action', async () => {
  const root = new Node('div');
  const trace = {question:'user question', answer:'short', status:'ok', events:[event('a','progress','working'),
    event('b','final','short',{variants:{detailed:'**long**', chat:'short'}, presentation:{role_name:'安琪拉'}})]};
  viewer.render(trace, root);
  assert.equal(byClass(root,'user-bubble')[0].textContent, 'user question');
  assert.match(byClass(root,'agent-name')[0].textContent, /安琪拉/);
  assert.equal(byClass(root,'progress-message')[0].textContent, 'working');
  assert.equal(byClass(root,'reply-detail').length, 1);
  assert.equal(byClass(root,'chat-reply-text')[0].textContent, 'short');
  await byClass(root,'reply-copy')[0].listeners.click();
  assert.equal(context.copied, 'short');
});

test('execution steps open original inspector records and only expose real reasoning', () => {
  const root = new Node('div'); let selected;
  const records = [{kind:'model', round:1, output:{choices:[{message:{reasoning_content:'saved reasoning'}}]}},
    {kind:'tool', name:'query_database', status:'error'}, {kind:'model', round:2, output:{}}];
  viewer.render({answer:'done'}, root, records, item => {selected = item;});
  assert.equal(byClass(root,'execution-details')[0].open, undefined);
  assert.equal(byClass(root,'thought-text').length, 1);
  assert.equal(byClass(root,'thought-text')[0].textContent, 'saved reasoning');
  byClass(root,'execution-step')[1].listeners.click();
  assert.equal(selected, records[1]);
});
