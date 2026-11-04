/* Local 20px stroke icons. Geometry and attributes never come from trace data. */
const ChatTraceIcons = (() => {
  'use strict';
  const path = d => ['path', {d}];
  const circle = (cx, cy, r) => ['circle', {cx, cy, r}];
  const icons = {
    tool: [path('M12 3a4.5 4.5 0 0 0-5.6 5.6L2.8 12.2a2 2 0 0 0 2.8 2.8l3.6-3.6A4.5 4.5 0 0 0 15 5.8l-2.8 2.8-2.8-2.8L12 3Z')],
    model: [path('m10 2.5 2 5.5 5.5 2-5.5 2-2 5.5L8 12l-5.5-2L8 8Z')],
    thinking: [
      ['ellipse', {cx:10, cy:10, rx:4, ry:8, transform:'rotate(45 10 10)'}],
      ['ellipse', {cx:10, cy:10, rx:4, ry:8, transform:'rotate(-45 10 10)'}],
      circle(10, 10, 1),
    ],
    search: [circle(8.5, 8.5, 5.5), path('m12.5 12.5 4.5 4.5')],
    read: [path('M12 2.5H5a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 5 17.5h10a1.5 1.5 0 0 0 1.5-1.5V7Zm0 0V7h4.5M7 10h6M7 13.5h4')],
    database: [
      ['ellipse', {cx:10, cy:4.5, rx:6.5, ry:2.5}],
      path('M3.5 4.5v11c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-11M3.5 10c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5'),
    ],
    code: [path('m3 5 4.5 5L3 15M10 15h7')],
    plot: [path('M3 3v14h14M6.5 13v-3M10.5 13V6M14.5 13V8')],
    image: [
      ['rect', {x:2.5, y:2.5, width:15, height:15, rx:2.5}],
      circle(7, 7, 1.5), path('m3 14 4-4 3 3 3.5-4 4 5'),
    ],
    memory: [path('M5 3h10v14l-5-3-5 3ZM8 6h4')],
    task: [circle(10, 10, 7.5), path('M10 5.5v5l3.5 2')],
    automation: [
      ['rect', {x:2.5, y:2.5, width:5, height:5, rx:1.3}],
      ['rect', {x:12.5, y:12.5, width:5, height:5, rx:1.3}],
      path('M7.5 5H13a2 2 0 0 1 2 2v3M12.5 8 15 10.5 17.5 8M5 10v3a2 2 0 0 0 2 2h3'),
    ],
    message: [path('m2.5 9 15-6.5L11 17.5 8.5 11.5Zm6 2.5 9-9')],
    profile: [circle(10, 6, 3), path('M3.5 17a6.5 6.5 0 0 1 13 0')],
    role: [path('M3 3.5h14v5a8 8 0 0 1-7 9 8 8 0 0 1-7-9ZM6 7h1M13 7h1M7 11a3.5 3.5 0 0 0 6 0')],
    control: [path('M3 5h4M11 5h6M3 15h7M14 15h3'), circle(9, 5, 2), circle(12, 15, 2)],
    discover: [
      ['rect', {x:3, y:3, width:5, height:5, rx:1}],
      ['rect', {x:3, y:12, width:5, height:5, rx:1}],
      ['rect', {x:12, y:12, width:5, height:5, rx:1}],
      path('M12 5.5h5M14.5 3v5'),
    ],
    usage: [path('M3.5 15.5V11M8 15.5V6.5M12.5 15.5V3M17 15.5V9')],
    copy: [
      ['rect', {x:6.5, y:6.5, width:11, height:11, rx:2}],
      path('M13.5 3.5v-1h-9a2 2 0 0 0-2 2v9h1'),
    ],
    chevron: [path('m7 4 6 6-6 6')],
  };

  // Explicit UI mappings for the registered application/QQ tools. New or historical
  // names fall back to a generic tool, never to a guessed action or execution state.
  const groups = [
    ['search', '搜索', ['web_search', 'search_chat_history', 'search_hok_functions']],
    ['read', '读取', ['read_recent_chat_history', 'read_bot_manual', 'list_reference_catalogs', 'describe_hok_function']],
    ['database', '查询', ['analyze_chat_database', 'analyze_game_database', 'lookup_reference_data', 'query_kpl']],
    ['code', '运行代码', ['execute_python']],
    ['plot', '绘图', ['list_plot_templates', 'render_plot']],
    ['image', '图像', ['generate_image', 'set_bot_avatar']],
    ['memory', '记忆', ['recall_memory', 'remember_memory', 'forget_memory']],
    ['task', '任务', ['create_task', 'list_tasks', 'cancel_task']],
    ['automation', '自动化', ['list_automation_actions', 'save_automation_rule', 'list_automation_rules', 'delete_automation_rule']],
    ['message', '消息', ['emit_message', 'set_reply_mention', 'send_group_member_private_message']],
    ['profile', '资料', ['read_group_member_profile']],
    ['role', '角色', ['list_roles', 'select_role', 'add_role_from_web', 'set_reply_preferences']],
    ['control', '会话设置', ['manage_chat_ignored_users']],
    ['discover', '工具发现', ['discover_tools']],
  ];
  const tools = new Map(groups.flatMap(([icon, label, names]) => names.map(name => [name, {icon, label}])));
  const forTool = name => tools.get(name) || {icon:'tool', label:'工具调用'};

  function create(name, className = '') {
    const key = Object.hasOwn(icons, name) ? name : 'tool';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [attribute, value] of Object.entries({
      viewBox:'0 0 20 20', width:20, height:20, fill:'none', stroke:'currentColor',
      'stroke-width':1.5, 'stroke-linecap':'round', 'stroke-linejoin':'round',
      'aria-hidden':'true', focusable:'false', 'data-icon':key, class:`chat-icon ${className}`.trim(),
    })) svg.setAttribute(attribute, String(value));
    for (const [tag, attributes] of icons[key]) {
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [attribute, value] of Object.entries(attributes)) node.setAttribute(attribute, String(value));
      svg.append(node);
    }
    return svg;
  }
  return {create, forTool};
})();
