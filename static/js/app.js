/* ==========================================================================
   Pike — frontend application
   Vanilla JavaScript. No frameworks. Server-Sent-Events streaming.
   ========================================================================== */
'use strict';

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                   */
/* -------------------------------------------------------------------------- */
const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));

const escapeHtml = (value = '') =>
  String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

const relativeTime = (stamp) => {
  if (!stamp) return '';
  const seconds = Math.floor(Date.now() / 1000 - stamp);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(stamp * 1000).toLocaleDateString();
};

const debounce = (fn, wait = 250) => {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
};

const icon = (name, extra = '') => `<svg class="icon ${extra}"><use href="#i-${name}"></use></svg>`;

const readLocal = (key, fallback) => {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
};

const writeLocal = (key, value) => {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
};

/* -------------------------------------------------------------------------- */
/*  API layer                                                                 */
/* -------------------------------------------------------------------------- */
const API = {
  async request(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let payload = {};
    try { payload = await response.json(); } catch { /* ignore */ }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
  },
  status: () => API.request('/api/status'),
  getSettings: () => API.request('/api/settings'),
  saveSettings: (body) => API.request('/api/settings', { method: 'POST', body }),
  testConnection: (body) => API.request('/api/settings/test', { method: 'POST', body }),
  getProviders: () => API.request('/api/providers'),
  refreshModels: (body) => API.request('/api/providers/models', { method: 'POST', body }),
  listConversations: (query = '') =>
    API.request(`/api/conversations${query ? `?q=${encodeURIComponent(query)}` : ''}`),
  getConversation: (id) => API.request(`/api/conversations/${id}`),
  saveConversation: (body) => API.request('/api/conversations/save', { method: 'POST', body }),
  renameConversation: (id, title) =>
    API.request(`/api/conversations/${id}`, { method: 'PATCH', body: { title } }),
  deleteConversation: (id) => API.request(`/api/conversations/${id}`, { method: 'DELETE' }),
  clearConversations: () => API.request('/api/conversations', { method: 'DELETE' }),
  checkForUpdate: () => API.request('/api/update'),
  // Workspace
  getWorkspace: () => API.request('/api/workspace'),
  setWorkspace: (path) => API.request('/api/workspace', { method: 'POST', body: { path } }),
  browseFolder: (path = '') =>
    API.request(`/api/workspace/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  workspaceTree: () => API.request('/api/workspace/tree'),
  readWorkspaceFile: (path) => API.request('/api/workspace/read', { method: 'POST', body: { path } }),
  writeWorkspaceFile: (path, content) =>
    API.request('/api/workspace/write', { method: 'POST', body: { path, content } }),
  deleteWorkspacePath: (path) =>
    API.request('/api/workspace/delete', { method: 'POST', body: { path } }),
  renameWorkspacePath: (from, to) =>
    API.request('/api/workspace/rename', { method: 'POST', body: { from, to } }),
  makeWorkspaceDir: (path) =>
    API.request('/api/workspace/mkdir', { method: 'POST', body: { path } }),
  searchWorkspace: (query) =>
    API.request(`/api/workspace/search?q=${encodeURIComponent(query)}`),
  // Terminal
  createTerminal: (cwd) => API.request('/api/terminal', { method: 'POST', body: { cwd } }),
  readTerminal: (id) => API.request(`/api/terminal/${id}`),
  writeTerminal: (id, input) =>
    API.request(`/api/terminal/${id}`, { method: 'POST', body: { input } }),
  interruptTerminal: (id) =>
    API.request(`/api/terminal/${id}/interrupt`, { method: 'POST', body: {} }),
  closeTerminal: (id) => API.request(`/api/terminal/${id}`, { method: 'DELETE' }),
};

/* -------------------------------------------------------------------------- */
/*  Application state                                                         */
/* -------------------------------------------------------------------------- */
const state = {
  conversationId: null,
  title: 'New conversation',
  messages: [],           // { role, content, time?, error? }
  models: [],
  providers: [],
  activeProvider: 'openai',
  catalogUpdated: '',
  defaultModel: 'gpt-4o-mini',
  reasoningLevels: [],
  reasoningEffort: 'medium',
  configured: false,
  appName: 'Pike',
  appVersion: '',
  streaming: false,
  controller: null,
  history: [],
  searchQuery: '',
  projects: [],
  activeProjectId: null,
  connectedEditors: readLocal('pike.editors', []),
  theme: readLocal('pike.theme', 'dark'),
  attachments: [],      // staged files/images waiting to be sent
  view: readLocal('pike.view', 'chat'),
  rightPanelOpen: false,
  rightPanelPref: readLocal('pike.panel', false),
  workspace: null,      // { path, name }
  tree: [],             // flat workspace listing
  openFile: null,       // { path, content, dirty }
  folderBrowse: null,   // current path in the folder picker
};

const PROJECTS_KEY = 'pike.projects';
const EDITORS_KEY = 'pike.editors';
const THEME_KEY = 'pike.theme';
const COMPACT_KEY = 'pike.compact';
const VIEW_KEY = 'pike.view';
const PANEL_KEY = 'pike.panel';

/* -------------------------------------------------------------------------- */
/*  DOM references                                                            */
/* -------------------------------------------------------------------------- */
const dom = {
  shell: $('#appShell'),
  messages: $('#messages'),
  welcome: $('#welcome'),
  conversation: $('#conversation'),
  composeConversation: $('#composeConversation'),
  composeMessages: $('#composeMessages'),
  prompt: $('#promptInput'),
  composerBox: $('#composerBox'),
  composerHint: $('#composerHint'),
  send: $('#sendBtn'),
  stop: $('#stopBtn'),
  newChat: $('#newChat'),
  attachWrap: $('#attachWrap'),
  attachBtn: $('#attachBtn'),
  attachMenu: $('#attachMenu'),
  attachPreview: $('#attachPreview'),
  fileInput: $('#fileInput'),
  imageInput: $('#imageInput'),
  modelSelect: $('#modelSelect'),
  modelSelectWrap: $('#modelSelectWrap'),
  modelTrigger: $('#modelTrigger'),
  modelTriggerLabel: $('#modelTriggerLabel'),
  modelMenu: $('#modelMenu'),
  modelMenuList: $('#modelMenuList'),
  modelSearchInput: $('#modelSearchInput'),
  modelDot: $('#modelDot'),
  composeModelSelect: $('#composeModelSelect'),
  composeModelSelectWrap: $('#composeModelSelectWrap'),
  composeModelTrigger: $('#composeModelTrigger'),
  composeModelTriggerLabel: $('#composeModelTriggerLabel'),
  composeModelMenu: $('#composeModelMenu'),
  composeModelMenuList: $('#composeModelMenuList'),
  composeModelSearchInput: $('#composeModelSearchInput'),
  composeModelDot: $('#composeModelDot'),
  reasoningWrap: $('#reasoningWrap'),
  reasoningTrigger: $('#reasoningTrigger'),
  reasoningTriggerLabel: $('#reasoningTriggerLabel'),
  reasoningMenu: $('#reasoningMenu'),
  reasoningMenuList: $('#reasoningMenuList'),
  composeAttachWrap: $('#composeAttachWrap'),
  composeAttachBtn: $('#composeAttachBtn'),
  composeAttachMenu: $('#composeAttachMenu'),
  composeAttachPreview: $('#composeAttachPreview'),
  composeFileInput: $('#composeFileInput'),
  composeImageInput: $('#composeImageInput'),
  composeReasoningWrap: $('#composeReasoningWrap'),
  composeReasoningTrigger: $('#composeReasoningTrigger'),
  composeReasoningTriggerLabel: $('#composeReasoningTriggerLabel'),
  composeReasoningMenu: $('#composeReasoningMenu'),
  composeReasoningMenuList: $('#composeReasoningMenuList'),
  statusDot: $('#statusDot'),
  connectionStatus: $('#connectionStatus'),
  connectCard: $('#connectCard'),
  chatHistory: $('#chatHistory'),
  projectList: $('#projectList'),
  newProject: $('#newProject'),
  projectsHead: $('#projectsHead'),
  topTitle: $('#topTitle'),
  topTitleText: $('#topTitleText'),
  topTitleIcon: $('#topTitleIcon'),
  scrollBottom: $('#scrollBottom'),
  toastContainer: $('#toastContainer'),
  settingsModal: $('#settingsModal'),
  providerSelect: $('#providerSelect'),
  providerDocs: $('#providerDocs'),
  refreshModels: $('#refreshModels'),
  refreshModelsList: $('#refreshModelsList'),
  modelsUpdatedNote: $('#modelsUpdatedNote'),
  apiKeyInput: $('#apiKeyInput'),
  baseUrlInput: $('#baseUrlInput'),
  saveKey: $('#saveKey'),
  removeKey: $('#removeKey'),
  toggleKey: $('#toggleKey'),
  testConnection: $('#testConnection'),
  searchInput: $('#searchInput'),
  searchClear: $('#searchClear'),
  menuBtn: $('#menuBtn'),
  sidebarClose: $('#sidebarClose'),
  backdrop: $('#sidebarBackdrop'),
  clearHistory: $('#clearHistory'),
  modalClose: $('#modalClose'),
  settingsBtn: $('#settingsBtn'),
  settingsTabs: $('#settingsTabs'),
  settingsModelList: $('#settingsModelList'),
  themeOptions: $('#themeOptions'),
  compactToggle: $('#compactToggle'),
  exportHistory: $('#exportHistory'),
  clearAllData: $('#clearAllData'),
  clearProjects: $('#clearProjects'),
  aboutApp: $('#aboutApp'),
  aboutVersion: $('#aboutVersion'),
  aboutModel: $('#aboutModel'),
  aboutStatus: $('#aboutStatus'),
  projectModal: $('#projectModal'),
  projectModalList: $('#projectModalList'),
  projectNameInput: $('#projectNameInput'),
  createProjectBtn: $('#createProjectBtn'),
  projectModalClose: $('#projectModalClose'),
  connectModal: $('#connectModal'),
  connectModalClose: $('#connectModalClose'),
  editorList: $('#editorList'),
  windowUpdate: $('#windowUpdate'),
  windowTitle: $('#windowTitle'),
  // Views
  viewTabs: $('#viewTabs'),
  chatView: $('#conversation'),
  composeView: $('#composeView'),
  composer: $('.main > .composer'),
  composeComposer: $('#composeView .compose-composer'),
  composePrompt: $('#composePromptInput'),
  composeSend: $('#composeSendBtn'),
  composeComposerBox: $('#composeComposerBox'),
  composeFolderStripName: $('#composeFolderStripName'),
  composeChooseFolder: $('#composeChooseFolder'),
  workspacePanel: $('#workspacePanel'),
  panelToggle: $('#panelToggle'),
  rightPanel: $('#rightPanel'),
  rightPanelBody: $('#rightPanelBody'),
  // Workspace / compose
  composeFolder: $('#composeFolder'),
  composeFolderName: $('#composeFolderName'),
  composeEmpty: $('#composeEmpty'),
  openFolderBtn: $('#openFolderBtn'),
  openFolderEmpty: $('#openFolderEmpty'),
  newFileBtn: $('#newFileBtn'),
  refreshTreeBtn: $('#refreshTreeBtn'),
  workspaceSearchInput: $('#workspaceSearchInput'),
  fileTree: $('#fileTree'),
  editorPane: $('#editorPane'),
  editorPathText: $('#editorPathText'),
  editorStatus: $('#editorStatus'),
  editorArea: $('#editorArea'),
  saveFileBtn: $('#saveFileBtn'),
  // Folder picker
  folderModal: $('#folderModal'),
  folderModalClose: $('#folderModalClose'),
  folderPath: $('#folderPath'),
  folderList: $('#folderList'),
  folderDrives: $('#folderDrives'),
  folderUp: $('#folderUp'),
  folderChoose: $('#folderChoose'),
  // Terminal
  terminalTop: $('#terminalTop'),
  terminalPanel: $('#terminalPanel'),
  terminalOutput: $('#terminalOutput'),
  terminalForm: $('#terminalForm'),
  terminalInput: $('#terminalInput'),
  terminalPrompt: $('#terminalPrompt'),
  terminalCwd: $('#terminalCwd'),
  terminalNewBtn: $('#terminalNewBtn'),
  terminalClearBtn: $('#terminalClearBtn'),
  terminalCloseBtn: $('#terminalCloseBtn'),
  terminalResize: $('#terminalResize'),
  dialogModal: $('#dialogModal'),
  dialogTitle: $('#dialogTitle'),
  dialogMessage: $('#dialogMessage'),
  dialogField: $('#dialogField'),
  dialogInput: $('#dialogInput'),
  dialogCancel: $('#dialogCancel'),
  dialogConfirm: $('#dialogConfirm'),
};

/* -------------------------------------------------------------------------- */
/*  Toasts                                                                    */
/* -------------------------------------------------------------------------- */
function toast(message, type = 'info', delay = 4200) {
  const iconName = { success: 'check-circle', error: 'alert', info: 'info' }[type] || 'info';
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.setAttribute('role', 'status');
  element.innerHTML = `
    ${icon(iconName)}
    <div class="toast-body">${escapeHtml(message)}</div>
    <button class="icon-btn toast-close" type="button" aria-label="Dismiss">${icon('x')}</button>`;

  const dismiss = () => {
    element.classList.add('leaving');
    element.addEventListener('animationend', () => element.remove(), { once: true });
    setTimeout(() => element.remove(), 400);
  };
  element.querySelector('.toast-close').addEventListener('click', dismiss);
  dom.toastContainer.appendChild(element);
  if (delay > 0) setTimeout(dismiss, delay);
}

/* -------------------------------------------------------------------------- */
/*  Overlay manager (settings / projects / connect)                           */
/* -------------------------------------------------------------------------- */
const openOverlays = new Set();
let lastFocused = null;

function openOverlay(element, focusEl) {
  if (!element || !element.hidden) return;
  if (openOverlays.size === 0) lastFocused = document.activeElement;
  element.hidden = false;
  openOverlays.add(element);
  document.body.style.overflow = 'hidden';
  if (focusEl && typeof focusEl.focus === 'function') {
    setTimeout(() => focusEl.focus(), 30);
  }
}

function closeOverlay(element) {
  if (!element || element.hidden) return;
  element.hidden = true;
  openOverlays.delete(element);
  if (openOverlays.size === 0) {
    document.body.style.overflow = '';
    if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus();
    lastFocused = null;
  }
}

function closeAllOverlays() {
  if (dialogResolve) { settleDialog(dialogReturnsValue ? null : false); return; }
  Array.from(openOverlays).forEach(closeOverlay);
}

/* -------------------------------------------------------------------------- */
/*  In-app dialog (replaces native window.alert/confirm/prompt)               */
/* -------------------------------------------------------------------------- */
let dialogResolve = null;
let dialogReturnsValue = false;

function settleDialog(value) {
  if (!dialogResolve) return;
  const resolve = dialogResolve;
  dialogResolve = null;
  closeOverlay(dom.dialogModal);
  resolve(value);
}

function showDialog({
  title = 'Notice',
  message = '',
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  input = false,
  value = '',
  placeholder = '',
  rows = 1,
} = {}) {
  if (dialogResolve) settleDialog(dialogReturnsValue ? null : false);
  dom.dialogTitle.textContent = title;
  dom.dialogMessage.textContent = message;
  dom.dialogMessage.hidden = !message;
  dom.dialogField.hidden = !input;
  dom.dialogInput.value = value;
  dom.dialogInput.placeholder = placeholder;
  dom.dialogInput.rows = rows;
  dom.dialogConfirm.textContent = confirmLabel;
  dom.dialogCancel.textContent = cancelLabel;
  dialogReturnsValue = !!input;
  openOverlay(dom.dialogModal, input ? dom.dialogInput : dom.dialogConfirm);
  if (input) setTimeout(() => { dom.dialogInput.focus(); dom.dialogInput.select(); }, 40);
  return new Promise((resolve) => { dialogResolve = resolve; });
}

function confirmDialog(title, message, confirmLabel = 'Delete') {
  return showDialog({ title, message, confirmLabel, cancelLabel: 'Cancel' }).then(Boolean);
}

function promptDialog(title, value = '', message = '', placeholder = '', extra = {}) {
  return showDialog({
    title, message, input: true, value, placeholder,
    confirmLabel: 'Save', cancelLabel: 'Cancel', ...extra,
  });
}

/* -------------------------------------------------------------------------- */
/*  Theme & appearance                                                        */
/* -------------------------------------------------------------------------- */
function applyTheme(theme) {
  state.theme = theme;
  const root = document.documentElement;
  const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  const resolved = theme === 'system' ? (prefersLight ? 'light' : 'dark') : theme;
  root.setAttribute('data-theme', resolved);
  root.style.colorScheme = resolved;
  $$('.theme-option', dom.themeOptions).forEach((option) => {
    option.classList.toggle('active', option.dataset.theme === theme);
  });
  writeLocal(THEME_KEY, theme);
}

function setCompact(enabled) {
  document.body.classList.toggle('compact', enabled);
  dom.compactToggle.setAttribute('aria-checked', String(enabled));
  writeLocal(COMPACT_KEY, enabled);
}

/* -------------------------------------------------------------------------- */
/*  Markdown rendering                                                        */
/* -------------------------------------------------------------------------- */
const markedOptions = { breaks: true, gfm: true };

function renderMarkdown(text) {
  const raw = window.marked
    ? window.marked.parse(text || '', markedOptions)
    : `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;
  return window.DOMPurify ? window.DOMPurify.sanitize(raw) : raw;
}

function decorateCodeBlocks(container) {
  $$('pre', container).forEach((pre) => {
    if (pre.closest('.code-block')) return;
    const code = pre.querySelector('code');
    const language = (code?.className.match(/language-([\w+#-]+)/) || [, 'code'])[1];
    const wrapper = document.createElement('div');
    wrapper.className = 'code-block';
    const header = document.createElement('div');
    header.className = 'code-header';
    header.innerHTML = `<span>${escapeHtml(language)}</span>
      <button class="copy-code" type="button">${icon('copy')} Copy</button>`;
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(header);
    wrapper.appendChild(pre);
    header.querySelector('.copy-code').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      try {
        await navigator.clipboard.writeText(code ? code.innerText : pre.innerText);
        button.innerHTML = `${icon('check')} Copied`;
        setTimeout(() => { button.innerHTML = `${icon('copy')} Copy`; }, 1600);
      } catch {
        toast('Could not access the clipboard.', 'error');
      }
    });
  });
}

/* -------------------------------------------------------------------------- */
/*  Message rendering                                                         */
/* -------------------------------------------------------------------------- */
function renderWelcome(show) {
  dom.welcome.hidden = !show || state.view === 'compose';
}

/** The message list that matches the current view (Chat or Compose). */
function activeMessagesEl() {
  return state.view === 'compose' ? dom.composeMessages : dom.messages;
}

function actionButton(iconName, label, handler) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'action-btn';
  button.innerHTML = `${icon(iconName)}<span>${label}</span>`;
  button.addEventListener('click', handler);
  return button;
}

function attachmentChips(items) {
  const row = document.createElement('div');
  row.className = 'message-attachments';
  items.forEach((item) => {
    const chip = document.createElement('span');
    chip.className = `attach-chip ${item.kind} static`;
    chip.title = `${item.name} · ${formatBytes(item.size || 0)}`;
    if (item.kind === 'image' && item.dataUrl) {
      chip.innerHTML = `<span class="attach-thumb" style="background-image:url('${item.dataUrl}')"></span>`
        + `<span class="attach-chip-body"><span class="attach-name">${escapeHtml(item.name)}</span></span>`;
    } else {
      chip.innerHTML = `${icon(attachmentIcon(item.kind))}`
        + `<span class="attach-chip-body"><span class="attach-name">${escapeHtml(item.name)}</span></span>`;
    }
    row.appendChild(chip);
  });
  return row;
}

function createThinkingBlock(text = '', streaming = false, seconds = 0) {
  const block = document.createElement('div');
  block.className = 'thinking';
  const title = seconds ? `Thought for ${seconds}s` : 'Thinking';
  block.innerHTML = `
    <button class="thinking-head" type="button" aria-expanded="false">
      ${icon('lightbulb', 'thinking-icon')}
      <span class="thinking-title">${escapeHtml(title)}</span>
      ${streaming ? '<span class="thinking-status">in progress…</span>' : ''}
      ${icon('chevron-down', 'thinking-chevron')}
    </button>
    <div class="thinking-body" hidden><div class="thinking-text"></div></div>`;

  const body = block.querySelector('.thinking-body');
  const textEl = block.querySelector('.thinking-text');
  const head = block.querySelector('.thinking-head');
  textEl.textContent = text;
  head.addEventListener('click', () => {
    const open = block.classList.toggle('open');
    body.hidden = !open;
    head.setAttribute('aria-expanded', String(open));
  });
  return { block, body, textEl, head };
}

const TOOL_LABELS = {
  list_directory: 'Listing files',
  read_file: 'Reading file',
  write_file: 'Editing file',
  search: 'Searching',
  delete_path: 'Deleting',
  rename_path: 'Renaming',
  make_directory: 'Creating folder',
  run_command: 'Running command',
};

const TOOL_ICONS = {
  list_directory: 'folder',
  read_file: 'file-text',
  write_file: 'pen',
  search: 'search',
  delete_path: 'trash',
  rename_path: 'edit',
  make_directory: 'folder-open',
  run_command: 'terminal',
};

const MAX_PREVIEW_CHARS = 8000;

function toolLanguage(path) {
  const base = String(path || '').split(/[\\/]/).pop() || '';
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1) : 'text';
}

/** Turn a raw ``tool`` SSE event into a persistable activity item. */
function toolItemFromEvent(data) {
  let args = {};
  try {
    args = typeof data.arguments === 'string'
      ? JSON.parse(data.arguments || '{}')
      : (data.arguments || {});
  } catch { /* ignore malformed args */ }
  const name = data.name || 'tool';
  let detail = args.path || args.query || '';
  if (!detail && name === 'rename_path') detail = [args.from, args.to].filter(Boolean).join(' → ');
  if (!detail && name === 'run_command') detail = args.command || '';
  const item = {
    name,
    label: TOOL_LABELS[name] || name || 'Working',
    detail: detail ? String(detail) : '',
  };
  // Editing a file: keep a (capped) preview of the new contents.
  if (name === 'write_file' && typeof args.content === 'string' && args.content) {
    item.preview = args.content.length > MAX_PREVIEW_CHARS
      ? `${args.content.slice(0, MAX_PREVIEW_CHARS)}\n...`
      : args.content;
    item.language = toolLanguage(args.path);
  }
  return item;
}

/** Attach the captured output of a finished tool call to its activity item. */
function applyToolOutput(item, result) {
  if (!item || !result) return;
  if (item.name === 'run_command') {
    item.kind = 'command';
    item.output = [result.stdout, result.stderr].filter(Boolean).join('\n').trim();
    item.exitCode = typeof result.exit_code === 'number' ? result.exit_code : undefined;
  } else if (item.name === 'search' && Array.isArray(result.results)) {
    item.results = result.results;
  } else if (result.error) {
    item.output = String(result.error);
    item.failed = true;
  }
}

/** One row in the expanded activity list (read/search/list actions). */
function toolEntryElement(item) {
  const entry = document.createElement('div');
  entry.className = 'tool-entry';

  const row = document.createElement('div');
  row.className = `tool-row done${item.failed ? ' failed' : ''}`;
  row.innerHTML = `${icon(TOOL_ICONS[item.name] || 'sparkle', 'tool-row-icon')}`
    + `<span class="tool-row-label">${escapeHtml(item.label)}</span>`
    + (item.detail ? `<span class="tool-row-detail">${escapeHtml(item.detail)}</span>` : '');
  entry.appendChild(row);

  if (item.output) {
    const pre = document.createElement('pre');
    pre.className = 'tool-output';
    pre.textContent = item.output;
    entry.appendChild(pre);
  }

  if (Array.isArray(item.results) && item.results.length) {
    const list = document.createElement('div');
    list.className = 'tool-results';
    item.results.slice(0, 50).forEach((hit) => {
      const line = document.createElement('div');
      line.className = 'tool-result';
      line.innerHTML = `<span class="tool-result-path">${escapeHtml(hit.path)}</span>`
        + (hit.line ? `<span class="tool-result-line">:${hit.line}</span>` : '')
        + (hit.text ? `<span class="tool-result-text">${escapeHtml(hit.text)}</span>` : '');
      list.appendChild(line);
    });
    entry.appendChild(list);
  }

  return entry;
}

/** A standalone card previewing a file the agent created or edited. */
function toolPreviewElement(item) {
  const card = document.createElement('div');
  card.className = 'tool-preview';

  const head = document.createElement('div');
  head.className = 'tool-preview-head';
  head.innerHTML = `${icon('pen', 'tool-preview-icon')}
    <span class="tool-preview-path">${escapeHtml(item.detail || 'file')}</span>
    <span class="tool-preview-lang">${escapeHtml(item.language || 'text')}</span>`;
  card.appendChild(head);

  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.textContent = item.preview;
  pre.appendChild(code);
  card.appendChild(pre);

  return card;
}

/** A standalone card showing a shell command and its captured output. */
function toolCommandElement(item) {
  const card = document.createElement('div');
  card.className = 'tool-command';

  const head = document.createElement('div');
  head.className = 'tool-command-head';
  head.innerHTML = `${icon('terminal', 'tool-command-icon')}
    <code class="tool-command-cmd">${escapeHtml(item.detail || 'command')}</code>
    <span class="tool-command-status"></span>`;
  card.appendChild(head);

  const pre = document.createElement('pre');
  pre.className = 'tool-command-output';
  card.appendChild(pre);

  return card;
}

/** Fill a command card with its output once the tool result arrives. */
function paintCommandCard(card, item) {
  if (!card) return;
  const status = card.querySelector('.tool-command-status');
  const pre = card.querySelector('.tool-command-output');
  if (pre) pre.textContent = item.output || '(no output)';
  if (status) {
    if (typeof item.exitCode === 'number') {
      status.textContent = item.exitCode === 0 ? 'exit 0' : `exit ${item.exitCode}`;
      status.classList.toggle('ok', item.exitCode === 0);
      status.classList.toggle('bad', item.exitCode !== 0);
    } else {
      status.textContent = 'done';
    }
  }
}

/** A tiny "typing dots" bubble used while the agent is working. */
function typingDots() {
  const wrap = document.createElement('div');
  wrap.className = 'typing';
  wrap.innerHTML = '<span></span><span></span><span></span>';
  return wrap;
}

/**
 * Collapsible "agent is working" panel plus independent cards. While running
 * it shows a loading (typing dots) bubble and the current action; clicking
 * reveals the read/search/list actions. File edits and shell commands render
 * as their own standalone cards (never mixed into this container).
 */
function createToolActivity() {
  const root = document.createElement('div');
  root.className = 'tool-activity live';
  root.hidden = true;

  const summary = document.createElement('button');
  summary.type = 'button';
  summary.className = 'tool-summary';
  summary.setAttribute('aria-expanded', 'false');
  summary.innerHTML = `<span class="tool-summary-spinner"></span>
    <span class="tool-summary-label">Working</span>
    <span class="tool-summary-detail"></span>
    ${icon('chevron-down', 'tool-summary-chevron')}`;

  const list = document.createElement('div');
  list.className = 'tool-list';
  list.hidden = true;

  // Separate container for standalone cards (file previews + command output)
  // so they never mix with the read/search/list activity panel above.
  const previews = document.createElement('div');
  previews.className = 'tool-previews';
  previews.hidden = true;

  root.appendChild(summary);
  root.appendChild(list);

  const labelEl = summary.querySelector('.tool-summary-label');
  const detailEl = summary.querySelector('.tool-summary-detail');
  const spinnerEl = summary.querySelector('.tool-summary-spinner');
  const items = [];

  summary.addEventListener('click', () => {
    const open = root.classList.toggle('open');
    list.hidden = !open;
    summary.setAttribute('aria-expanded', String(open));
  });

  return {
    root,
    previews,
    list,
    items,
    hasActions() {
      return list.children.length > 0;
    },
    lastCard: null,
    lastEntry: null,
    add(item, autoExpand = true) {
      items.push(item);
      // File edits and shell commands get their own standalone cards.
      if (item.preview) {
        previews.hidden = false;
        const card = toolPreviewElement(item);
        previews.appendChild(card);
        this.lastCard = null;
        this.lastEntry = null;
        return card;
      }
      if (item.name === 'run_command') {
        previews.hidden = false;
        const card = toolCommandElement(item);
        // Persisted items already carry their captured output.
        if (item.output !== undefined || item.exitCode !== undefined || item.failed) {
          paintCommandCard(card, item);
        }
        previews.appendChild(card);
        this.lastCard = card;
        this.lastEntry = null;
        return card;
      }
      root.hidden = false;
      const entry = toolEntryElement(item);
      list.appendChild(entry);
      labelEl.textContent = item.label;
      detailEl.textContent = item.detail;
      this.lastCard = null;
      this.lastEntry = entry;
      return entry;
    },
    /** Attach captured output from a ``tool_output`` event to its item/card. */
    attachOutput(item, result) {
      applyToolOutput(item, result);
      if (item.kind === 'command') {
        paintCommandCard(this.lastCard, item);
      } else if (this.lastEntry && (item.output || item.failed || (item.results && item.results.length))) {
        // Re-render the row now that it carries output/search hits.
        const next = toolEntryElement(item);
        this.lastEntry.replaceWith(next);
        this.lastEntry = next;
      }
    },
    finish() {
      // If only cards happened there is no activity panel to settle.
      if (!list.children.length) {
        root.remove();
        return;
      }
      root.classList.remove('live');
      root.classList.add('done');
      if (spinnerEl) spinnerEl.outerHTML = icon('check-circle', 'tool-summary-icon');
      const count = list.children.length;
      labelEl.textContent = count === 1 ? 'Used 1 action' : `Used ${count} actions`;
      detailEl.textContent = '';
    },
  };
}

function messageElement(message, index) {
  const wrapper = document.createElement('article');
  wrapper.className = `message ${message.role}${message.error ? ' error' : ''}`;
  wrapper.dataset.index = index;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  wrapper.appendChild(bubble);

  const isUser = message.role === 'user';
  if (isUser) {
    if (message.attachments && message.attachments.length) {
      bubble.appendChild(attachmentChips(message.attachments));
    }
    if (message.content) {
      const text = document.createElement('div');
      text.className = 'bubble-text';
      text.textContent = message.content;
      bubble.appendChild(text);
    }
  } else if (message.error) {
    bubble.innerHTML = `${icon('alert')}${escapeHtml(message.content)}`;
  } else {
    if (message.reasoning) {
      bubble.appendChild(createThinkingBlock(message.reasoning, false, message.thinkingTime || 0).block);
    }
    if (message.tools && message.tools.length) {
      const activity = createToolActivity();
      message.tools.forEach((item) => activity.add(item, false));
      // File-edit previews render independently from the activity panel.
      if (activity.previews.children.length) bubble.appendChild(activity.previews);
      if (activity.hasActions()) {
        activity.finish();
        bubble.appendChild(activity.root);
      } else {
        activity.root.remove();
      }
    }
    const answer = document.createElement('div');
    answer.className = 'answer';
    answer.innerHTML = renderMarkdown(message.content);
    bubble.appendChild(answer);
    decorateCodeBlocks(bubble);
  }

  const actions = document.createElement('div');
  actions.className = 'message-actions';
  actions.appendChild(actionButton('copy', 'Copy', () => {
    navigator.clipboard.writeText(message.content)
      .then(() => toast('Message copied.', 'success', 2000))
      .catch(() => toast('Could not access the clipboard.', 'error'));
  }));

  if (isUser) {
    actions.appendChild(actionButton('edit', 'Edit', () => startEdit(index)));
  } else if (!message.error && index === state.messages.length - 1) {
    actions.appendChild(actionButton('refresh', 'Regenerate', () => regenerate(index)));
  }
  wrapper.appendChild(actions);

  return wrapper;
}

function renderMessages() {
  const target = activeMessagesEl();
  target.innerHTML = '';
  state.messages.forEach((message, index) => {
    target.appendChild(messageElement(message, index));
  });
  renderWelcome(state.messages.length === 0);
  scrollToBottom(true);
}

/* -------------------------------------------------------------------------- */
/*  Editing a user message                                                    */
/* -------------------------------------------------------------------------- */
function startEdit(index) {
  if (state.streaming) return;
  const message = state.messages[index];
  if (!message || message.role !== 'user') return;
  dom.prompt.value = message.content;
  clearAttachments();
  if (message.attachments && message.attachments.length) {
    state.attachments = message.attachments.slice();
    renderAttachments();
  }
  autoResize();
  dom.prompt.focus();
  // Truncate at the edited message; the answer will be regenerated on resend.
  state.messages = state.messages.slice(0, index);
  renderMessages();
  toast('Editing your message — press Enter to resend.', 'info', 2600);
}

/* -------------------------------------------------------------------------- */
/*  Streaming from the backend                                                */
/* -------------------------------------------------------------------------- */
function createStreamingBubble() {
  const wrapper = document.createElement('article');
  wrapper.className = 'message assistant';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const thinking = createThinkingBlock('', true);
  thinking.block.hidden = true;

  // Loading bubble shown while the agent is working but hasn't produced text.
  const working = document.createElement('div');
  working.className = 'working-bubble';
  working.appendChild(typingDots());

  const answer = document.createElement('div');
  answer.className = 'answer';
  answer.hidden = true;

  const tools = createToolActivity();

  bubble.appendChild(thinking.block);
  bubble.appendChild(tools.previews);
  bubble.appendChild(tools.root);
  bubble.appendChild(answer);
  bubble.appendChild(working);
  wrapper.appendChild(bubble);

  activeMessagesEl().appendChild(wrapper);
  renderWelcome(false);
  scrollToBottom();
  return { wrapper, bubble, answer, thinking, tools, working };
}

async function sendMessage(text) {
  const content = (text ?? dom.prompt.value).trim();
  const attachments = state.attachments.slice();
  if ((!content && !attachments.length) || state.streaming) return;

  const message = {
    role: 'user',
    content: content || 'Please review the attached content.',
    time: Date.now() / 1000,
  };
  if (attachments.length) message.attachments = attachments;
  state.messages.push(message);
  const surface = activeMessagesEl();
  surface.appendChild(messageElement(state.messages[state.messages.length - 1], state.messages.length - 1));
  renderWelcome(false);
  dom.prompt.value = '';
  clearAttachments();
  autoResize();
  scrollToBottom(true);
  await streamAssistantReply();
}

async function streamAssistantReply() {
  setStreaming(true);
  const { wrapper, answer, thinking, tools, working } = createStreamingBubble();
  let answerText = '';
  let reasoningText = '';
  let thinkingStarted = 0;
  let thinkingSeconds = 0;
  let pendingToolItem = null;

  const controller = new AbortController();
  state.controller = controller;

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: state.messages.map(({ role, content, attachments }) => {
          const context = buildAttachmentContext(attachments);
          return { role, content: context ? `${content}\n\n${context}` : content };
        }),
        model: dom.modelSelect.value || state.defaultModel,
        reasoning_effort: state.reasoningEffort,
        conversation_id: state.conversationId,
      }),
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      let detail = `The server responded with ${response.status}.`;
      try {
        const parsed = await response.json();
        if (parsed?.error) detail = parsed.error;
      } catch { /* ignore */ }
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const paintAnswer = () => {
      answer.hidden = false;
      answer.innerHTML = renderMarkdown(answerText) + '<span class="caret"></span>';
      decorateCodeBlocks(answer);
    };

    // While the agent is working, remove the caret and show the loading bubble
    // at the very bottom (below any answer text/tool cards).
    const showWorking = () => {
      if (answerText) {
        answer.hidden = false;
        answer.innerHTML = renderMarkdown(answerText);
        decorateCodeBlocks(answer);
      }
      working.hidden = false;
    };

    const hideWorking = () => {
      working.hidden = true;
    };

    const finishThinking = () => {
      if (!reasoningText) return;
      thinking.block.classList.remove('streaming');
      thinking.block.classList.add('done');
      const status = thinking.block.querySelector('.thinking-status');
      if (status) status.textContent = '';
      if (thinkingStarted && !thinkingSeconds) {
        thinkingSeconds = Math.max(1, Math.round((Date.now() - thinkingStarted) / 1000));
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split('\n\n');
      buffer = frames.pop() || '';

      for (const frame of frames) {
        const event = parseSseFrame(frame);
        if (!event) continue;

        if (event.type === 'reasoning') {
          if (!reasoningText) thinkingStarted = Date.now();
          reasoningText += event.data.text || '';
          hideWorking();
          thinking.block.hidden = false;
          thinking.block.classList.add('streaming');
          thinking.textEl.textContent = reasoningText;
          scrollToBottom();
        } else if (event.type === 'delta') {
          answerText += event.data.text || '';
          hideWorking();
          finishThinking();
          paintAnswer();
          scrollToBottom();
        } else if (event.type === 'tool') {
          // Working on the workspace: remove the caret and show the loading
          // bubble at the bottom while the tool runs.
          showWorking();
          pendingToolItem = toolItemFromEvent(event.data);
          tools.add(pendingToolItem);
          scrollToBottom();
        } else if (event.type === 'tool_output') {
          tools.attachOutput(pendingToolItem, event.data.result);
          pendingToolItem = null;
          scrollToBottom();
        } else if (event.type === 'error') {
          throw new Error(event.data.error || 'The AI provider returned an error.');
        } else if (event.type === 'done') {
          if (!answerText && event.data.reply) answerText = event.data.reply;
          if (!reasoningText && event.data.reasoning) {
            reasoningText = event.data.reasoning;
            thinking.block.hidden = false;
            thinking.textEl.textContent = reasoningText;
            finishThinking();
          }
          hideWorking();
        }
      }
    }

    if (!answerText.trim()) throw new Error('The model returned an empty response. Please try again.');

    tools.finish();
    state.messages.push({
      role: 'assistant',
      content: answerText,
      reasoning: reasoningText || undefined,
      thinkingTime: thinkingSeconds || undefined,
      tools: tools.items.length ? tools.items : undefined,
      time: Date.now() / 1000,
    });
    renderMessages();
    await persistConversation();
  } catch (error) {
    if (error.name === 'AbortError') {
      if (answerText.trim()) {
        tools.finish();
        state.messages.push({
          role: 'assistant',
          content: answerText + '\n\n_(stopped)_',
          reasoning: reasoningText || undefined,
          thinkingTime: thinkingSeconds || undefined,
          tools: tools.items.length ? tools.items : undefined,
          time: Date.now() / 1000,
        });
        renderMessages();
        await persistConversation();
      } else {
        wrapper.remove();
      }
      toast('Generation stopped.', 'info', 2200);
    } else {
      wrapper.remove();
      const message = error.message || 'Something went wrong.';
      state.messages.push({ role: 'assistant', content: message, error: true, time: Date.now() / 1000 });
      renderMessages();
      toast(message, 'error', 6000);
      if (/api key/i.test(message)) openSettings('connection');
    }
  } finally {
    setStreaming(false);
    state.controller = null;
    dom.prompt.focus();
  }
}

function parseSseFrame(frame) {
  let type = 'message';
  let data = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { type, data: JSON.parse(data) };
  } catch {
    return null;
  }
}

async function regenerate(index) {
  if (state.streaming) return;
  const message = state.messages[index];
  if (!message || message.role !== 'assistant') return;
  state.messages = state.messages.slice(0, index);
  renderMessages();
  if (!state.messages.some((entry) => entry.role === 'user')) {
    toast('There is nothing to regenerate.', 'info');
    return;
  }
  await streamAssistantReply();
}

function setStreaming(active) {
  state.streaming = active;
  dom.send.hidden = active;
  dom.stop.hidden = !active;
  dom.composeSend.disabled = active;
  dom.composerBox.classList.toggle('busy', active);
  dom.composeComposerBox.classList.toggle('busy', active);
  dom.messages.setAttribute('aria-busy', String(active));
  if (dom.composeMessages) dom.composeMessages.setAttribute('aria-busy', String(active));
  dom.prompt.placeholder = active ? 'Pike is thinking...' : 'Message Pike...';
  dom.modelSelect.disabled = active;
  dom.modelTrigger.disabled = active;
  if (dom.composeModelSelect) dom.composeModelSelect.disabled = active;
  if (dom.composeModelTrigger) dom.composeModelTrigger.disabled = active;
  dom.attachBtn.disabled = active;
  dom.reasoningTrigger.disabled = active;
  if (dom.composeAttachBtn) dom.composeAttachBtn.disabled = active;
  if (dom.composeReasoningTrigger) dom.composeReasoningTrigger.disabled = active;
  if (active) {
    closeModelMenu(MAIN_MODEL_REFS()); closeModelMenu(COMPOSE_MODEL_REFS());
    closeReasoningMenu(MAIN_REASONING_REFS()); closeReasoningMenu(COMPOSE_REASONING_REFS());
    closeAttachMenu(MAIN_ATTACH_REFS()); closeAttachMenu(COMPOSE_ATTACH_REFS());
  }
}

/* -------------------------------------------------------------------------- */
/*  Persistence                                                               */
/* -------------------------------------------------------------------------- */
async function persistConversation() {
  if (!state.messages.some((message) => !message.error)) return;
  const payload = state.messages
    .filter((message) => !message.error)
    .map(({ role, content, attachments, reasoning, thinkingTime, tools }) => {
      const out = { role, content };
      if (reasoning) out.reasoning = reasoning;
      if (thinkingTime) out.thinkingTime = thinkingTime;
      if (tools && tools.length) out.tools = tools;
      if (attachments && attachments.length) {
        out.attachments = attachments.map(({ id, name, kind, size, text, dataUrl, truncated }) => {
          const item = { id, name, kind, size };
          if (text) item.text = text;
          if (dataUrl) item.dataUrl = dataUrl;
          if (truncated) item.truncated = true;
          return item;
        });
      }
      return out;
    });
  if (!payload.length) return;
  try {
    const result = await API.saveConversation({
      conversation_id: state.conversationId,
      messages: payload,
      title: state.title,
      model: dom.modelSelect.value || state.defaultModel,
    });
    const conversation = result.conversation;
    state.conversationId = conversation.id;
    state.title = conversation.title;
    syncTopbarTitle();
    attachActiveProject(conversation.id);
    await loadHistory();
  } catch (error) {
    console.warn('Could not save conversation:', error.message);
  }
}

/* -------------------------------------------------------------------------- */
/*  Projects (local, stored in the browser)                                   */
/* -------------------------------------------------------------------------- */
function loadProjects() {
  const parsed = readLocal(PROJECTS_KEY, []);
  state.projects = Array.isArray(parsed) ? parsed : [];
  renderProjects();
}

function persistProjects() {
  if (!writeLocal(PROJECTS_KEY, state.projects)) {
    toast('Could not save projects on this device.', 'error');
  }
}

function renderProjects() {
  dom.projectList.innerHTML = '';
  if (!state.projects.length) return;
  state.projects.forEach((project) => {
    const count = (project.conversationIds || []).length;
    const item = document.createElement('div');
    item.className = 'project-item';
    item.dataset.id = project.id;
    if (project.id === state.activeProjectId) item.classList.add('active');
    item.innerHTML = `
      ${icon('folder')}
      <span class="project-item-title">${escapeHtml(project.name)}</span>
      ${count ? `<span class="project-count">${count}</span>` : ''}
      <button class="icon-btn delete" title="Delete project" aria-label="Delete project">${icon('trash')}</button>`;
    item.addEventListener('click', (event) => {
      if (event.target.closest('.delete')) return;
      openProjectsModal(project.id);
    });
    item.querySelector('.delete').addEventListener('click', (event) => {
      event.stopPropagation();
      deleteProject(project);
    });
    dom.projectList.appendChild(item);
  });
}

function createProject(name) {
  const trimmed = (name || '').trim();
  if (!trimmed) return null;
  const project = {
    id: `p_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`,
    name: trimmed.slice(0, 60),
    conversationIds: [],
  };
  state.projects.push(project);
  persistProjects();
  renderProjects();
  renderProjectModal();
  toast('Project created.', 'success', 2000);
  return project;
}

async function deleteProject(project) {
  if (!(await confirmDialog('Delete project', `Delete “${project.name}”? Conversations are kept.`))) return;
  state.projects = state.projects.filter((entry) => entry.id !== project.id);
  if (state.activeProjectId === project.id) state.activeProjectId = null;
  persistProjects();
  renderProjects();
  renderProjectModal();
  renderHistory();
  toast('Project deleted.', 'success', 2000);
}

function selectProject(projectId) {
  state.activeProjectId = state.activeProjectId === projectId ? null : projectId;
  renderProjects();
  renderHistory();
}

function attachActiveProject(conversationId) {
  if (!state.activeProjectId || !conversationId) return;
  const project = state.projects.find((entry) => entry.id === state.activeProjectId);
  if (!project) return;
  project.conversationIds = project.conversationIds || [];
  if (!project.conversationIds.includes(conversationId)) {
    project.conversationIds.push(conversationId);
    persistProjects();
    renderProjects();
    renderProjectModal();
  }
}

/* -------------------------------------------------------------------------- */
/*  Projects modal                                                            */
/* -------------------------------------------------------------------------- */
function openProjectsModal(focusProjectId) {
  if (focusProjectId) state.activeProjectId = focusProjectId;
  renderProjectModal();
  renderProjects();
  renderHistory();
  openOverlay(dom.projectModal, dom.projectNameInput);
}

function closeProjectsModal() {
  closeOverlay(dom.projectModal);
}

function renderProjectModal() {
  dom.projectModalList.innerHTML = '';

  if (!state.projects.length) {
    dom.projectModalList.innerHTML =
      '<div class="empty-state">No projects yet — create one above to organise your conversations.</div>';
    return;
  }

  state.projects.forEach((project) => {
    const ids = project.conversationIds || [];
    const isActive = project.id === state.activeProjectId;

    const row = document.createElement('div');
    row.className = `project-row${isActive ? ' active' : ''}`;
    row.innerHTML = `
      ${icon('folder')}
      <div class="project-row-body">
        <div class="project-row-title">${escapeHtml(project.name)}</div>
        <div class="project-row-meta">${ids.length} conversation${ids.length === 1 ? '' : 's'}</div>
      </div>
      <div class="project-row-actions">
        <button class="icon-btn toggle" title="${isActive ? 'Hide conversations' : 'Show conversations'}" aria-label="Toggle conversations">${icon(isActive ? 'chevron-down' : 'chevron-right')}</button>
        <button class="icon-btn rename" title="Rename" aria-label="Rename">${icon('edit')}</button>
        <button class="icon-btn delete" title="Delete" aria-label="Delete">${icon('trash')}</button>
      </div>`;
    row.addEventListener('click', (event) => {
      if (event.target.closest('button')) return;
      selectProject(project.id);
      renderProjectModal();
    });
    row.querySelector('.toggle').addEventListener('click', (event) => {
      event.stopPropagation();
      selectProject(project.id);
      renderProjectModal();
    });
    row.querySelector('.rename').addEventListener('click', (event) => {
      event.stopPropagation();
      renameProject(project);
    });
    row.querySelector('.delete').addEventListener('click', (event) => {
      event.stopPropagation();
      deleteProject(project);
    });
    dom.projectModalList.appendChild(row);

    if (isActive) {
      const conversations = state.history.filter((c) => ids.includes(c.id));
      const sublist = document.createElement('div');
      sublist.className = 'project-sublist';
      if (!conversations.length) {
        sublist.innerHTML = '<div class="empty-state">No conversations in this project yet. Chat with this project selected to add one.</div>';
      } else {
        conversations.forEach((conversation) => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'chat-item';
          item.innerHTML = `
            ${icon('message')}
            <div class="chat-item-body">
              <div class="chat-item-title">${escapeHtml(conversation.title)}</div>
              <div class="chat-item-meta">${relativeTime(conversation.updated_at)} · ${conversation.message_count} message${conversation.message_count === 1 ? '' : 's'}</div>
            </div>`;
          item.addEventListener('click', async () => {
            closeProjectsModal();
            await openConversation(conversation.id);
          });
          sublist.appendChild(item);
        });
      }
      dom.projectModalList.appendChild(sublist);
    }
  });
}

function renameProject(project) {
  promptDialog('Rename project', project.name).then((name) => {
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    project.name = trimmed.slice(0, 60);
    persistProjects();
    renderProjects();
    renderProjectModal();
    toast('Project renamed.', 'success', 2000);
  });
}

/* -------------------------------------------------------------------------- */
/*  Connect modal                                                            */
/* -------------------------------------------------------------------------- */
const EDITORS = [
  { id: 'vscode', name: 'Visual Studio Code', icon: 'vscode', className: 'vscode', desc: 'The most popular code editor.', install: 'code --install-extension pike.pike' },
  { id: 'cursor', name: 'Cursor', icon: 'cursor', className: 'cursor', desc: 'AI-first code editor.', install: 'cursor --install-extension pike.pike' },
  { id: 'jetbrains', name: 'JetBrains IDEs', icon: 'jetbrains', className: 'jetbrains', desc: 'IntelliJ, WebStorm, PyCharm and more.', install: 'Install the Pike plugin from the marketplace' },
  { id: 'neovim', name: 'Neovim', icon: 'neovim', className: 'neovim', desc: 'Hyperextensible Vim-based editor.', install: ':PikeConnect' },
  { id: 'sublime', name: 'Sublime Text', icon: 'sublime', className: 'sublime', desc: 'A sophisticated text editor.', install: 'Install Pike via Package Control' },
];

function openConnectModal() {
  renderEditors();
  openOverlay(dom.connectModal);
}

function closeConnectModal() {
  closeOverlay(dom.connectModal);
}

function renderEditors() {
  dom.editorList.innerHTML = '';
  EDITORS.forEach((editor) => {
    const connected = state.connectedEditors.includes(editor.id);
    const card = document.createElement('div');
    card.className = `editor-card${connected ? ' connected' : ''}`;
    card.innerHTML = `
      <span class="editor-logo ${editor.className}">${icon(editor.icon)}</span>
      <div class="editor-body">
        <div class="editor-name">${escapeHtml(editor.name)}</div>
        <div class="editor-desc">${escapeHtml(editor.desc)}</div>
        <div class="editor-install">${connected ? escapeHtml(editor.install) : ''}</div>
      </div>
      <div class="editor-action">
        <button class="btn ${connected ? 'btn-ghost' : 'btn-primary'}" type="button">
          ${connected ? icon('check') + '<span>Connected</span>' : '<span>Connect</span>'}
        </button>
      </div>`;
    card.querySelector('button').addEventListener('click', () => toggleEditor(editor));
    dom.editorList.appendChild(card);
  });
}

function toggleEditor(editor) {
  const connected = state.connectedEditors.includes(editor.id);
  if (connected) {
    state.connectedEditors = state.connectedEditors.filter((id) => id !== editor.id);
    toast(`Disconnected from ${editor.name}.`, 'info', 2600);
  } else {
    state.connectedEditors = [...state.connectedEditors, editor.id];
    toast(`Connected to ${editor.name}.`, 'success', 2600);
  }
  writeLocal(EDITORS_KEY, state.connectedEditors);
  renderEditors();
  updateConnectStatus();
}

function updateConnectStatus() {
  const count = state.connectedEditors.length;
  if (count > 0) {
    dom.connectionStatus.textContent = `${count} editor${count === 1 ? '' : 's'} connected`;
  } else {
    dom.connectionStatus.textContent = 'Connect to editor';
  }
}

/* -------------------------------------------------------------------------- */
/*  Sidebar history                                                           */
/* -------------------------------------------------------------------------- */
async function loadHistory(query = state.searchQuery) {
  state.searchQuery = query;
  try {
    const result = await API.listConversations(query);
    state.history = result.conversations;
    renderHistory();
    if (!dom.projectModal.hidden) renderProjectModal();
  } catch (error) {
    console.warn('Could not load history:', error.message);
  }
}

function renderHistory() {
  dom.chatHistory.innerHTML = '';
  const activeProject = state.projects.find((entry) => entry.id === state.activeProjectId);
  const conversations = activeProject
    ? state.history.filter((conversation) => (activeProject.conversationIds || []).includes(conversation.id))
    : state.history;

  if (!conversations.length) {
    dom.chatHistory.innerHTML = `<div class="empty-state">${
      activeProject
        ? 'No conversations in this project yet.'
        : state.searchQuery
          ? 'No conversations match your search.'
          : 'No conversations yet.'
    }</div>`;
    return;
  }
  conversations.forEach((conversation) => {
    const item = document.createElement('div');
    item.className = 'chat-item';
    item.dataset.id = conversation.id;
    if (conversation.id === state.conversationId) item.classList.add('active');
    item.innerHTML = `
      ${icon('message')}
      <div class="chat-item-body">
        <div class="chat-item-title">${escapeHtml(conversation.title)}</div>
        <div class="chat-item-meta">${relativeTime(conversation.updated_at)} · ${conversation.message_count} message${conversation.message_count === 1 ? '' : 's'}</div>
      </div>
      <div class="chat-item-actions">
        <button class="icon-btn rename" title="Rename" aria-label="Rename">${icon('edit')}</button>
        <button class="icon-btn delete" title="Delete" aria-label="Delete">${icon('trash')}</button>
      </div>`;
    item.addEventListener('click', (event) => {
      if (event.target.closest('.rename') || event.target.closest('.delete')) return;
      openConversation(conversation.id);
    });
    item.querySelector('.rename').addEventListener('click', (event) => {
      event.stopPropagation();
      renameConversation(conversation);
    });
    item.querySelector('.delete').addEventListener('click', (event) => {
      event.stopPropagation();
      removeConversation(conversation);
    });
    dom.chatHistory.appendChild(item);
  });
}

function highlightActive() {
  $$('.chat-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.id === state.conversationId);
  });
}

async function openConversation(id) {
  if (state.streaming) { toast('Please wait for the current reply to finish.', 'info'); return; }
  try {
    const result = await API.getConversation(id);
    const conversation = result.conversation;
    state.conversationId = conversation.id;
    state.title = conversation.title;
    state.messages = (conversation.messages || []).map((message) => ({
      ...message,
      time: conversation.updated_at,
    }));
    clearAttachments();
    syncTopbarTitle();
    if (conversation.model && state.models.some((model) => model.id === conversation.model)) {
      selectModel(conversation.model, { save: false });
    }
    renderMessages();
    highlightActive();
    closeSidebarOnMobile();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function renameConversation(conversation) {
  const title = await promptDialog('Rename conversation', conversation.title);
  if (title === null) return;
  const trimmed = title.trim();
  if (!trimmed) return;
  try {
    await API.renameConversation(conversation.id, trimmed);
    if (conversation.id === state.conversationId) {
      state.title = trimmed;
      syncTopbarTitle();
    }
    await loadHistory();
    toast('Conversation renamed.', 'success', 2000);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function removeConversation(conversation) {
  if (!(await confirmDialog('Delete conversation', `Delete “${conversation.title}”? This cannot be undone.`))) return;
  try {
    await API.deleteConversation(conversation.id);
    state.projects.forEach((project) => {
      project.conversationIds = (project.conversationIds || []).filter((id) => id !== conversation.id);
    });
    persistProjects();
    renderProjects();
    if (!dom.projectModal.hidden) renderProjectModal();
    if (conversation.id === state.conversationId) newConversation();
    await loadHistory();
    toast('Conversation deleted.', 'success', 2000);
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* -------------------------------------------------------------------------- */
/*  Conversation lifecycle                                                    */
/* -------------------------------------------------------------------------- */
function newConversation() {
  if (state.streaming) state.controller?.abort();
  state.conversationId = null;
  state.title = 'New conversation';
  state.messages = [];
  clearAttachments();
  syncTopbarTitle();
  dom.prompt.value = '';
  autoResize();
  renderMessages();
  highlightActive();
  dom.prompt.focus();
  closeSidebarOnMobile();
}

/* -------------------------------------------------------------------------- */
/*  Attachments                                                               */
/* -------------------------------------------------------------------------- */
const MAX_ATTACH_BYTES = 1024 * 1024; // 1 MB of extracted text per file

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentIcon(kind) {
  return { image: 'image', code: 'code', text: 'file-text' }[kind] || 'file-text';
}

function openAttachMenu(refs = MAIN_ATTACH_REFS()) {
  refs.menu.hidden = false;
  refs.btn.setAttribute('aria-expanded', 'true');
  refs.btn.classList.add('attach-btn-active');
}

function closeAttachMenu(refs = MAIN_ATTACH_REFS()) {
  refs.menu.hidden = true;
  refs.btn.setAttribute('aria-expanded', 'false');
  refs.btn.classList.remove('attach-btn-active');
}

function toggleAttachMenu(refs = MAIN_ATTACH_REFS()) {
  if (refs.menu.hidden) openAttachMenu(refs);
  else closeAttachMenu(refs);
}

const MAIN_ATTACH_REFS = () => ({ menu: dom.attachMenu, btn: dom.attachBtn });
const COMPOSE_ATTACH_REFS = () => ({ menu: dom.composeAttachMenu, btn: dom.composeAttachBtn });

const CODE_EXT = /\.(js|mjs|cjs|ts|tsx|jsx|py|rb|go|rs|java|c|h|cpp|cc|hpp|cs|php|swift|kt|kts|sh|bash|zsh|ps1|sql|html|htm|css|scss|sass|less|json|jsonc|yaml|yml|toml|ini|xml|md|markdown|txt|log|csv|env|gitignore)$/i;

async function handleAttachFiles(fileList, kindHint) {
  const files = Array.from(fileList || []);
  for (const file of files) {
    const isImage = file.type.startsWith('image/') || kindHint === 'image';
    const kind = isImage ? 'image' : (CODE_EXT.test(file.name || '') ? 'code' : 'text');

    if (isImage) {
      try {
        const dataUrl = await readFileAsDataUrl(file);
        state.attachments.push({
          id: `a_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
          name: file.name || 'image',
          kind: 'image',
          size: file.size,
          dataUrl,
        });
      } catch {
        toast(`Could not read ${file.name}.`, 'error');
      }
      continue;
    }

    try {
      let text = await readFileAsText(file);
      let truncated = false;
      if (text.length > MAX_ATTACH_BYTES) {
        text = text.slice(0, MAX_ATTACH_BYTES);
        truncated = true;
      }
      state.attachments.push({
        id: `a_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        name: file.name || 'file',
        kind,
        size: file.size,
        text,
        truncated,
      });
    } catch {
      toast(`Could not read ${file.name}.`, 'error');
    }
  }
  renderAttachments();
  dom.prompt.focus();
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function addCodeSnippet() {
  promptDialog('Paste code snippet', '', 'Paste a code snippet to attach it to your message.', 'Paste or type code here...', {
    rows: 8,
  }).then((value) => {
    if (value === null) return;
    const text = String(value).trim();
    if (!text) return;
    state.attachments.push({
      id: `a_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      name: 'snippet.txt',
      kind: 'code',
      size: text.length,
      text,
    });
    renderAttachments();
    dom.prompt.focus();
  });
}

function removeAttachment(id) {
  state.attachments = state.attachments.filter((item) => item.id !== id);
  renderAttachments();
}

function clearAttachments() {
  state.attachments = [];
  renderAttachments();
}

function renderAttachments() {
  const list = state.attachments;
  [dom.attachPreview, dom.composeAttachPreview].forEach((preview) => {
    if (!preview) return;
    preview.innerHTML = '';
    preview.hidden = list.length === 0;
    list.forEach((item) => {
      const chip = document.createElement('div');
      chip.className = `attach-chip ${item.kind}`;
      chip.title = `${item.name} · ${formatBytes(item.size)}`;
      if (item.kind === 'image' && item.dataUrl) {
        chip.innerHTML = `
          <span class="attach-thumb" style="background-image:url('${item.dataUrl}')"></span>
          <span class="attach-chip-body">
            <span class="attach-name">${escapeHtml(item.name)}</span>
            <span class="attach-meta">${formatBytes(item.size)}</span>
          </span>
          <button class="attach-remove" type="button" aria-label="Remove attachment" title="Remove">${icon('x')}</button>`;
      } else {
        chip.innerHTML = `
          ${icon(attachmentIcon(item.kind))}
          <span class="attach-chip-body">
            <span class="attach-name">${escapeHtml(item.name)}</span>
            <span class="attach-meta">${formatBytes(item.size)}${item.truncated ? ' · trimmed' : ''}</span>
          </span>
          <button class="attach-remove" type="button" aria-label="Remove attachment" title="Remove">${icon('x')}</button>`;
      }
      chip.querySelector('.attach-remove').addEventListener('click', () => removeAttachment(item.id));
      preview.appendChild(chip);
    });
  });
}

function buildAttachmentContext(items) {
  if (!items || !items.length) return '';
  const blocks = items.map((item) => {
    if (item.kind === 'image') {
      return `[Attached image: ${item.name}]`;
    }
    return `--- File: ${item.name} ---\n${item.text || ''}${item.truncated ? '\n…(truncated)' : ''}`;
  });
  return `The user attached the following content:\n\n${blocks.join('\n\n')}`;
}

/* -------------------------------------------------------------------------- */
/*  Composer                                                                  */
/* -------------------------------------------------------------------------- */
function autoResize() {
  dom.prompt.style.height = 'auto';
  dom.prompt.style.height = `${Math.min(dom.prompt.scrollHeight, 200)}px`;
  if (dom.composePrompt) {
    dom.composePrompt.style.height = 'auto';
    dom.composePrompt.style.height = `${Math.min(dom.composePrompt.scrollHeight, 200)}px`;
  }
}

function scrollToBottom(force = false) {
  const surface = state.view === 'compose' ? dom.composeConversation : dom.conversation;
  if (!surface) return;
  const nearBottom = surface.scrollHeight - surface.scrollTop - surface.clientHeight < 200;
  if (force || nearBottom) surface.scrollTop = surface.scrollHeight;
}

/* -------------------------------------------------------------------------- */
/*  Model selector                                                            */
/* -------------------------------------------------------------------------- */
const MAIN_MODEL_REFS = () => ({
  select: dom.modelSelect,
  trigger: dom.modelTrigger,
  triggerLabel: dom.modelTriggerLabel,
  menu: dom.modelMenu,
  menuList: dom.modelMenuList,
  searchInput: dom.modelSearchInput,
});

const COMPOSE_MODEL_REFS = () => ({
  select: dom.composeModelSelect,
  trigger: dom.composeModelTrigger,
  triggerLabel: dom.composeModelTriggerLabel,
  menu: dom.composeModelMenu,
  menuList: dom.composeModelMenuList,
  searchInput: dom.composeModelSearchInput,
});

function renderModelMenu(refs = MAIN_MODEL_REFS()) {
  if (!refs?.menuList) return;
  const current = refs.select.value || state.defaultModel;
  const query = (refs.searchInput?.value || '').trim().toLowerCase();
  const list = refs.menuList;
  list.innerHTML = '';

  const matches = state.models.filter((model) => {
    if (!query) return true;
    return `${model.label || ''} ${model.id || ''} ${model.hint || ''}`.toLowerCase().includes(query);
  });

  if (!state.models.length) {
    list.innerHTML = '<div class="empty-state">No models available.</div>';
    return;
  }
  if (!matches.length) {
    list.innerHTML = `<div class="empty-state">No models match “${escapeHtml(query)}”.</div>`;
    return;
  }

  matches.forEach((model) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = `model-option${model.id === current ? ' active' : ''}`;
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', String(model.id === current));
    const providerLabel = model.provider_name || model.provider || '';
    option.innerHTML = `
      <div class="model-option-body">
        <div class="model-option-label">${escapeHtml(model.label || model.id)}</div>
        ${model.hint ? `<div class="model-option-hint">${escapeHtml(model.hint)}</div>` : ''}
        ${providerLabel ? `<div class="model-option-hint model-option-provider">${escapeHtml(providerLabel)}</div>` : ''}
      </div>
      ${model.badge ? `<span class="model-option-badge">${escapeHtml(model.badge)}</span>` : ''}
      ${icon('check', 'model-option-check')}`;
    option.addEventListener('click', () => {
      selectModel(model.id);
      closeModelMenu(refs);
    });
    list.appendChild(option);
  });
}

function updateModelTriggerLabel(refs = MAIN_MODEL_REFS()) {
  if (!refs?.triggerLabel) return;
  const current = refs.select.value || state.defaultModel;
  const model = state.models.find((entry) => entry.id === current);
  refs.triggerLabel.textContent = model ? (model.label || model.id) : (current || 'Select model');
}

function syncModelSelects(modelId) {
  if (state.models.some((model) => model.id === modelId)) {
    dom.modelSelect.value = modelId;
    if (dom.composeModelSelect) dom.composeModelSelect.value = modelId;
  }
  updateModelTriggerLabel(MAIN_MODEL_REFS());
  updateModelTriggerLabel(COMPOSE_MODEL_REFS());
  renderModelMenu(MAIN_MODEL_REFS());
  renderModelMenu(COMPOSE_MODEL_REFS());
}

function selectModel(modelId, { save = true } = {}) {
  if (!modelId) return;
  syncModelSelects(modelId);
  renderSettingsModels();
  renderReasoningSelect();
  if (save) {
    API.saveSettings({ model: modelId }).catch(() => {});
  }
}

function openModelMenu(refs = MAIN_MODEL_REFS()) {
  if (!refs?.menu) return;
  closeReasoningMenu(MAIN_REASONING_REFS());
  closeReasoningMenu(COMPOSE_REASONING_REFS());
  closeModelMenu(MAIN_MODEL_REFS());
  closeModelMenu(COMPOSE_MODEL_REFS());
  refs.menu.hidden = false;
  refs.trigger.setAttribute('aria-expanded', 'true');
  renderModelMenu(refs);
  if (refs.searchInput) {
    refs.searchInput.value = '';
    setTimeout(() => refs.searchInput.focus(), 20);
  }
}

function closeModelMenu(refs = MAIN_MODEL_REFS()) {
  if (!refs?.menu) return;
  refs.menu.hidden = true;
  refs.trigger.setAttribute('aria-expanded', 'false');
  if (refs.searchInput) refs.searchInput.value = '';
}

function toggleModelMenu(refs = MAIN_MODEL_REFS()) {
  if (refs.menu.hidden) openModelMenu(refs);
  else closeModelMenu(refs);
}

/* -------------------------------------------------------------------------- */
/*  Thinking level                                                            */
/* -------------------------------------------------------------------------- */
const FALLBACK_REASONING_LEVELS = [
  { id: 'off', label: 'Off', hint: 'Answer without thinking' },
  { id: 'low', label: 'Low', hint: 'Quick reasoning' },
  { id: 'medium', label: 'Medium', hint: 'Balanced (default)' },
  { id: 'high', label: 'High', hint: 'Deep reasoning' },
];

function getActiveModel() {
  const current = dom.modelSelect.value || state.defaultModel;
  return state.models.find((entry) => entry.id === current) || null;
}

function reasoningLevels() {
  return state.reasoningLevels.length ? state.reasoningLevels : FALLBACK_REASONING_LEVELS;
}

function currentReasoningLevel() {
  const levels = reasoningLevels();
  const found = levels.find((level) => level.id === state.reasoningEffort);
  return found || levels.find((level) => level.id === 'medium') || levels[0];
}

const MAIN_REASONING_REFS = () => ({
  wrap: dom.reasoningWrap,
  trigger: dom.reasoningTrigger,
  triggerLabel: dom.reasoningTriggerLabel,
  menu: dom.reasoningMenu,
  menuList: dom.reasoningMenuList,
});

const COMPOSE_REASONING_REFS = () => ({
  wrap: dom.composeReasoningWrap,
  trigger: dom.composeReasoningTrigger,
  triggerLabel: dom.composeReasoningTriggerLabel,
  menu: dom.composeReasoningMenu,
  menuList: dom.composeReasoningMenuList,
});

function reasoningRefs() {
  return state.view === 'compose' ? COMPOSE_REASONING_REFS() : MAIN_REASONING_REFS();
}

function renderReasoningMenu(refs = MAIN_REASONING_REFS()) {
  const list = refs.menuList;
  if (!list) return;
  const current = currentReasoningLevel()?.id;
  list.innerHTML = '';
  reasoningLevels().forEach((level) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = `model-option${level.id === current ? ' active' : ''}`;
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', String(level.id === current));
    option.innerHTML = `
      <div class="model-option-body">
        <div class="model-option-label">${escapeHtml(level.label)}</div>
        ${level.hint ? `<div class="model-option-hint">${escapeHtml(level.hint)}</div>` : ''}
      </div>
      ${icon('check', 'model-option-check')}`;
    option.addEventListener('click', () => {
      selectReasoning(level.id);
      closeReasoningMenu(refs);
    });
    list.appendChild(option);
  });
}

function updateReasoningTriggerLabel(refs = MAIN_REASONING_REFS()) {
  if (!refs.triggerLabel) return;
  const level = currentReasoningLevel();
  refs.triggerLabel.textContent = level ? `Thinking: ${level.label}` : 'Thinking';
}

function renderReasoningSelect() {
  const model = getActiveModel();
  const supports = !!model?.reasoning;
  const levels = reasoningLevels();
  if (!levels.some((level) => level.id === state.reasoningEffort)) {
    state.reasoningEffort = 'medium';
  }
  [MAIN_REASONING_REFS(), COMPOSE_REASONING_REFS()].forEach((refs) => {
    if (!refs.wrap) return;
    refs.wrap.hidden = !supports;
    if (!supports) {
      closeReasoningMenu(refs);
      return;
    }
    updateReasoningTriggerLabel(refs);
    renderReasoningMenu(refs);
  });
}

function selectReasoning(effort) {
  if (!reasoningLevels().some((level) => level.id === effort)) return;
  state.reasoningEffort = effort;
  updateReasoningTriggerLabel(MAIN_REASONING_REFS());
  updateReasoningTriggerLabel(COMPOSE_REASONING_REFS());
  renderReasoningMenu(MAIN_REASONING_REFS());
  renderReasoningMenu(COMPOSE_REASONING_REFS());
  API.saveSettings({ reasoning_effort: effort }).catch(() => {});
}

function openReasoningMenu(refs = MAIN_REASONING_REFS()) {
  closeModelMenu(MAIN_MODEL_REFS());
  closeModelMenu(COMPOSE_MODEL_REFS());
  closeReasoningMenu(MAIN_REASONING_REFS());
  closeReasoningMenu(COMPOSE_REASONING_REFS());
  refs.menu.hidden = false;
  refs.trigger.setAttribute('aria-expanded', 'true');
  renderReasoningMenu(refs);
}

function closeReasoningMenu(refs = MAIN_REASONING_REFS()) {
  if (!refs?.menu) return;
  refs.menu.hidden = true;
  refs.trigger.setAttribute('aria-expanded', 'false');
}

function toggleReasoningMenu(refs = MAIN_REASONING_REFS()) {
  if (refs.wrap?.hidden) return;
  if (refs.menu.hidden) openReasoningMenu(refs);
  else closeReasoningMenu(refs);
}

/* -------------------------------------------------------------------------- */
/*  Settings                                                                  */
/* -------------------------------------------------------------------------- */
function openSettings(tab = 'connection') {
  API.getSettings()
    .then((result) => {
      applyProviderData(result);
      dom.apiKeyInput.value = '';
      dom.apiKeyInput.placeholder = result.has_api_key ? '•••••••• (a key is saved)' : providerKeyHint(result.provider);
      renderSettingsModels();
      updateAbout();
      switchSettingsTab(tab);
      openOverlay(dom.settingsModal, tab === 'connection' ? dom.apiKeyInput : null);
    })
    .catch((error) => toast(error.message, 'error'));
}

function providerKeyHint(providerId) {
  const provider = state.providers.find((entry) => entry.id === providerId);
  return (provider && provider.key_hint) || 'sk-...';
}

function applyProviderData(result) {
  state.providers = result.providers || state.providers;
  state.activeProvider = result.provider || state.activeProvider;
  state.catalogUpdated = result.catalog_updated || state.catalogUpdated;
  dom.baseUrlInput.value = result.base_url || '';
  renderProviderSelect();
  updateProviderDocs();
}

// The order providers should appear in the picker. Providers whose key is
// already saved are grouped at the top, followed by the rest.
const FEATURED_PROVIDER_ORDER = [
  'openai', 'anthropic', 'google', 'xai', 'deepseek',
  'mistral', 'groq', 'openrouter', 'perplexity', 'moonshot', 'zai',
  'qwen', 'together', 'cohere', 'cerebras', 'amazon', 'ollama', 'lmstudio', 'custom',
];

function sortProviders(providers) {
  const rank = (id) => {
    const index = FEATURED_PROVIDER_ORDER.indexOf(id);
    return index === -1 ? FEATURED_PROVIDER_ORDER.length : index;
  };
  return [...providers].sort((a, b) => {
    const configured = Number(!a.has_key) - Number(!b.has_key);
    if (configured !== 0) return configured;
    return rank(a.id) - rank(b.id);
  });
}

function renderProviderSelect() {
  if (!dom.providerSelect) return;
  const providers = state.providers.length
    ? sortProviders(state.providers)
    : [{ id: state.activeProvider, name: state.activeProvider, has_key: false }];
  dom.providerSelect.innerHTML = '';
  const configured = providers.filter((provider) => provider.has_key && !provider.custom);
  if (configured.length) {
    const group = document.createElement('optgroup');
    group.label = 'Configured';
    configured.forEach((provider) => group.appendChild(providerOption(provider)));
    dom.providerSelect.appendChild(group);
  }
  const others = providers.filter(
    (provider) => !(provider.has_key && !provider.custom) && !provider.custom,
  );
  if (others.length) {
    const group = document.createElement('optgroup');
    group.label = configured.length ? 'More providers' : 'Providers';
    others.forEach((provider) => group.appendChild(providerOption(provider)));
    dom.providerSelect.appendChild(group);
  }
  const custom = providers.find((provider) => provider.custom);
  if (custom) dom.providerSelect.appendChild(providerOption(custom));
}

function providerOption(provider) {
  const option = document.createElement('option');
  option.value = provider.id;
  option.textContent = provider.has_key && !provider.custom
    ? `${provider.name} \u2022`
    : provider.name;
  if (provider.id === state.activeProvider) option.selected = true;
  return option;
}

function wireProviderEvents() {
  if (dom.providerSelect) {
    dom.providerSelect.addEventListener('change', () => onProviderChange(dom.providerSelect.value));
  }
  if (dom.refreshModels) {
    dom.refreshModels.addEventListener('click', () => refreshModels(dom.refreshModels));
  }
  if (dom.refreshModelsList) {
    dom.refreshModelsList.addEventListener('click', () => refreshModels(dom.refreshModelsList));
  }
}

function updateProviderDocs() {
  if (!dom.providerDocs) return;
  const provider = state.providers.find((entry) => entry.id === state.activeProvider);
  if (provider && provider.docs_url) {
    dom.providerDocs.href = provider.docs_url;
    const label = 'Get an API key';
    dom.providerDocs.innerHTML = `${escapeHtml(label)} ${icon('external')}`;
    dom.providerDocs.style.display = '';
  } else {
    dom.providerDocs.style.display = 'none';
  }
}

async function onProviderChange(providerId) {
  state.activeProvider = providerId;
  const provider = state.providers.find((entry) => entry.id === providerId) || {};
  // Show the correct base URL for the chosen provider immediately.
  if (!provider.custom) dom.baseUrlInput.value = provider.base_url || '';
  dom.apiKeyInput.value = '';
  dom.apiKeyInput.placeholder = provider.has_key ? '•••••••• (a key is saved)' : (provider.key_hint || 'sk-...');
  updateProviderDocs();
  try {
    const result = await API.saveSettings({ provider: providerId });
    applyProviderData(result);
    state.models = result.models || [];
    state.defaultModel = result.default_model || state.defaultModel;
    rebuildModelSelect(result.default_model);
    renderSettingsModels();
    if (result.settings?.has_api_key !== undefined) {
      dom.apiKeyInput.placeholder = result.has_api_key ? '•••••••• (a key is saved)' : (provider.key_hint || 'sk-...');
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

function rebuildModelSelect(preferred) {
  const compose = dom.composeModelSelect;
  if (!state.models.length) {
    dom.modelSelect.innerHTML = '';
    if (compose) compose.innerHTML = '';
    updateModelTriggerLabel(MAIN_MODEL_REFS());
    updateModelTriggerLabel(COMPOSE_MODEL_REFS());
    renderModelMenu(MAIN_MODEL_REFS());
    renderModelMenu(COMPOSE_MODEL_REFS());
    return;
  }
  dom.modelSelect.innerHTML = '';
  if (compose) compose.innerHTML = '';
  state.models.forEach((model) => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = model.label || model.id;
    if (model.hint) option.title = model.hint;
    dom.modelSelect.appendChild(option);
    if (compose) compose.appendChild(option.cloneNode(true));
  });
  const wanted = preferred || state.defaultModel;
  const selected = state.models.some((model) => model.id === wanted)
    ? wanted
    : state.models[0].id;
  dom.modelSelect.value = selected;
  if (compose) compose.value = selected;
  updateModelTriggerLabel(MAIN_MODEL_REFS());
  updateModelTriggerLabel(COMPOSE_MODEL_REFS());
  renderModelMenu(MAIN_MODEL_REFS());
  renderModelMenu(COMPOSE_MODEL_REFS());
  renderReasoningSelect();
}

function switchSettingsTab(tab) {
  $$('.settings-tab', dom.settingsTabs).forEach((button) => {
    const active = button.dataset.tab === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $$('.settings-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.panel === tab);
  });
  if (tab === 'models') renderSettingsModels();
  if (tab === 'about') updateAbout();
}

function renderSettingsModels() {
  if (!dom.settingsModelList) return;
  dom.settingsModelList.innerHTML = '';
  if (dom.modelsUpdatedNote && state.catalogUpdated) {
    dom.modelsUpdatedNote.textContent =
      `Showing all ${state.models.length} models across every provider · catalogue updated ${state.catalogUpdated}.`;
  }
  if (!state.models.length) {
    dom.settingsModelList.innerHTML = '<div class="empty-state">No models yet — click Refresh to fetch the live list.</div>';
    return;
  }
  const current = dom.modelSelect.value || state.defaultModel;
  state.models.forEach((model) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = `model-row${model.id === current ? ' active' : ''}`;
    const meta = [];
    if (model.context) meta.push(`${Math.round(model.context / 1000)}K context`);
    if (model.reasoning) meta.push('thinking');
    if (model.provider_name || model.provider) meta.push(model.provider_name || model.provider);
    row.innerHTML = `
      ${icon('bolt')}
      <div class="model-row-body">
        <div class="model-row-name">${escapeHtml(model.label || model.id)}</div>
        <div class="model-row-hint">${escapeHtml(model.hint || model.id)}</div>
        ${meta.length ? `<div class="model-row-meta"><span class="model-row-provider">${escapeHtml(meta.join(' · '))}</span></div>` : ''}
      </div>
      ${model.has_key === false ? '<span class="model-option-badge needs-key">Add key</span>' : ''}
      ${model.badge ? `<span class="model-option-badge">${escapeHtml(model.badge)}</span>` : ''}
      ${icon('check', 'model-row-check')}`;
    row.addEventListener('click', () => {
      selectModel(model.id);
      toast(`Default model set to ${model.label || model.id}.`, 'success', 2200);
    });
    dom.settingsModelList.appendChild(row);
  });
}

function updateAbout() {
  dom.aboutApp.textContent = state.appName;
  dom.aboutVersion.textContent = state.appVersion || '—';
  const model = state.models.find((entry) => entry.id === (dom.modelSelect.value || state.defaultModel));
  dom.aboutModel.textContent = model ? (model.label || model.id) : (state.defaultModel || '—');
  dom.aboutStatus.textContent = state.configured ? 'Connected & ready' : 'API key required';
}

async function saveSettings() {
  const body = { provider: state.activeProvider };
  const key = dom.apiKeyInput.value.trim();
  if (key) body.api_key = key;
  body.base_url = dom.baseUrlInput.value.trim();
  try {
    const result = await API.saveSettings(body);
    applyProviderData(result);
    dom.apiKeyInput.value = '';
    dom.apiKeyInput.placeholder = result.has_api_key ? '•••••••• (a key is saved)' : providerKeyHint(state.activeProvider);
    await refreshStatus();
    await loadHistory();
    toast(`Connection saved${state.activeProvider ? ' for ' + providerName(state.activeProvider) : ''}.`, 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

function providerName(providerId) {
  const provider = state.providers.find((entry) => entry.id === providerId);
  return provider ? provider.name : providerId;
}

async function removeKey() {
  try {
    await API.saveSettings({ provider: state.activeProvider, api_key: '' });
    dom.apiKeyInput.value = '';
    dom.apiKeyInput.placeholder = providerKeyHint(state.activeProvider);
    toast('API key removed.', 'info');
    await refreshStatus();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function refreshModels(button = dom.refreshModels) {
  if (!button) return;
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span><span class="btn-label">Refreshing...</span>';
  try {
    const result = await API.refreshModels({ provider: state.activeProvider });
    state.models = result.models || [];
    rebuildModelSelect();
    renderSettingsModels();
    await refreshStatus();
    toast(`Loaded ${state.models.length} models from ${providerName(state.activeProvider)}.`, 'success');
  } catch (error) {
    toast(error.message, 'error', 6000);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

async function testConnection() {
  const button = dom.testConnection;
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span><span class="btn-label">Testing...</span>';
  try {
    const body = { provider: state.activeProvider, base_url: dom.baseUrlInput.value.trim() };
    if (dom.apiKeyInput.value.trim()) body.api_key = dom.apiKeyInput.value.trim();
    await API.saveSettings(body);
    const result = await API.testConnection({
      model: dom.modelSelect.value || state.defaultModel,
      reasoning_effort: state.reasoningEffort,
    });
    button.innerHTML = `${icon('check')}<span class="btn-label">Works!</span>`;
    toast(`Connected successfully — ${result.model} replied.`, 'success');
    await refreshStatus();
  } catch (error) {
    button.innerHTML = original;
    toast(error.message, 'error', 6000);
  } finally {
    button.disabled = false;
    setTimeout(() => { button.innerHTML = original; }, 2500);
  }
}

async function exportConversations() {
  try {
    const result = await API.listConversations('');
    const summaries = result.conversations || [];
    if (!summaries.length) { toast('There is nothing to export yet.', 'info'); return; }
    const full = await Promise.all(
      summaries.map((summary) => API.getConversation(summary.id).then((r) => r.conversation).catch(() => summary)),
    );
    const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), conversations: full }, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pike-conversations-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast(`Exported ${full.length} conversation${full.length === 1 ? '' : 's'}.`, 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function clearAllConversations() {
  if (!(await confirmDialog('Delete all conversations', 'Delete all conversations? This cannot be undone.'))) return;
  try {
    await API.clearConversations();
    state.projects.forEach((project) => { project.conversationIds = []; });
    persistProjects();
    renderProjects();
    renderProjectModal();
    newConversation();
    await loadHistory('');
    dom.searchInput.value = '';
    dom.searchClear.hidden = true;
    toast('All conversations deleted.', 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function clearAllProjects() {
  if (!state.projects.length) { toast('There are no projects to delete.', 'info'); return; }
  if (!(await confirmDialog('Delete all projects', 'Delete all projects? Conversations are kept.'))) return;
  state.projects = [];
  state.activeProjectId = null;
  persistProjects();
  renderProjects();
  renderProjectModal();
  renderHistory();
  toast('All projects deleted.', 'success');
}

/* -------------------------------------------------------------------------- */
/*  Status                                                                    */
/* -------------------------------------------------------------------------- */
async function refreshStatus() {
  try {
    const result = await API.status();
    state.configured = result.configured;
    state.defaultModel = result.model;
    state.models = result.models || [];
    state.reasoningLevels = result.reasoning_levels || state.reasoningLevels;
    state.reasoningEffort = result.reasoning_effort || state.reasoningEffort;
    state.appName = result.app || state.appName;
    state.appVersion = result.version || state.appVersion;

    if (state.models.length) {
      const current = dom.modelSelect.value;
      dom.modelSelect.innerHTML = '';
      if (dom.composeModelSelect) dom.composeModelSelect.innerHTML = '';
      state.models.forEach((model) => {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.label || model.id;
        if (model.hint) option.title = model.hint;
        dom.modelSelect.appendChild(option);
        if (dom.composeModelSelect) dom.composeModelSelect.appendChild(option.cloneNode(true));
      });
      const preferred = current || result.model;
      let selected;
      if (state.models.some((model) => model.id === preferred)) {
        selected = preferred;
      } else {
        selected = state.models[0].id;
      }
      dom.modelSelect.value = selected;
      if (dom.composeModelSelect) dom.composeModelSelect.value = selected;
    }

    dom.statusDot.classList.toggle('online', result.configured);
    dom.statusDot.classList.toggle('offline', !result.configured);
    dom.modelDot.classList.toggle('online', result.configured);
    dom.modelDot.classList.toggle('offline', !result.configured);
    dom.composeModelDot?.classList.toggle('online', result.configured);
    dom.composeModelDot?.classList.toggle('offline', !result.configured);
    updateConnectStatus();
    updateModelTriggerLabel(MAIN_MODEL_REFS());
    updateModelTriggerLabel(COMPOSE_MODEL_REFS());
    renderModelMenu(MAIN_MODEL_REFS());
    renderModelMenu(COMPOSE_MODEL_REFS());
    renderReasoningSelect();
    renderSettingsModels();
    updateAbout();
  } catch (error) {
    dom.statusDot.classList.add('offline');
    dom.connectionStatus.textContent = 'Backend unavailable';
    console.warn('Status check failed:', error.message);
  }
}

/* -------------------------------------------------------------------------- */
/*  Updates                                                                   */
/* -------------------------------------------------------------------------- */
function setUpdateBusy(busy) {
  if (!dom.windowUpdate) return;
  dom.windowUpdate.classList.toggle('busy', busy);
  dom.windowUpdate.disabled = busy;
}

async function checkForUpdate() {
  if (!dom.windowUpdate || dom.windowUpdate.classList.contains('busy')) return;
  setUpdateBusy(true);
  try {
    const result = await API.checkForUpdate();
    if (result.update_available) {
      const label = `Update ${result.latest} available.`;
      toast(`${label} Opening the download page...`, 'success', 6000);
      if (result.url) {
        window.open(result.url, '_blank', 'noopener');
      }
    } else if (result.configured) {
      toast(`You're on the latest version (${result.current}).`, 'success', 3000);
    } else {
      toast(`Pike ${result.current} — no update source configured.`, 'info', 4000);
    }
  } catch (error) {
    toast(error.message || 'Could not check for updates.', 'error', 5000);
  } finally {
    setUpdateBusy(false);
  }
}

/* -------------------------------------------------------------------------- */
/*  Sidebar behaviour (mobile)                                                */
/* -------------------------------------------------------------------------- */
function openSidebar() {
  document.body.classList.add('sidebar-open');
  dom.backdrop.hidden = false;
}
function closeSidebar() {
  document.body.classList.remove('sidebar-open');
  dom.backdrop.hidden = true;
}
function closeSidebarOnMobile() {
  if (window.matchMedia('(max-width: 900px)').matches) closeSidebar();
}

/* -------------------------------------------------------------------------- */
/*  View switching (Chat / Compose)                                           */
/* -------------------------------------------------------------------------- */
function setView(view, { focus = true } = {}) {
  if (view !== 'chat' && view !== 'compose') view = 'chat';
  state.view = view;
  writeLocal(VIEW_KEY, view);
  const isCompose = view === 'compose';
  dom.composeView.hidden = !isCompose;
  dom.chatView.hidden = isCompose;
  dom.composer.hidden = isCompose;
  dom.composeComposer.hidden = !isCompose;
  // The files/editor panel stays available in both views. Compose relies on
  // it to show the file tree and editor, so open it automatically there and
  // restore the user's chat preference when coming back.
  setPanelOpen(isCompose ? true : state.rightPanelPref, { persist: false });
  // Re-render into the surface that belongs to this view so the transcript
  // follows you between Chat and Compose instead of only living in Chat.
  renderMessages();
  $$('.view-tab', dom.viewTabs).forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  syncTopbarTitle();
  if (focus) {
    if (isCompose) {
      dom.composePrompt.focus();
    } else if (state.rightPanelOpen && state.openFile) {
      dom.editorArea.focus();
    } else {
      dom.prompt.focus();
    }
  }
}

/* -------------------------------------------------------------------------- */
/*  Right files panel                                                         */
/* -------------------------------------------------------------------------- */
function setPanelOpen(open, { persist = true } = {}) {
  const isOpen = !!open;
  state.rightPanelOpen = isOpen;
  if (persist) {
    state.rightPanelPref = isOpen;
    writeLocal(PANEL_KEY, isOpen);
  }
  document.body.classList.toggle('panel-open', isOpen);
  dom.rightPanel.hidden = !isOpen;
  dom.panelToggle.classList.toggle('active', isOpen);
  dom.panelToggle.setAttribute('aria-pressed', String(isOpen));
}

function togglePanel() {
  const next = !state.rightPanelOpen;
  setPanelOpen(next);
  if (next && !state.workspace) openFolderModal();
}

/* -------------------------------------------------------------------------- */
/*  Top bar title (conversation or open folder)                               */
/* -------------------------------------------------------------------------- */
function syncTopbarTitle() {
  if (state.view === 'compose') {
    const workspace = state.workspace;
    dom.topTitleIcon.hidden = false;
    if (workspace && workspace.path) {
      dom.topTitleText.textContent = workspace.name || workspace.path;
      dom.topTitle.title = workspace.path;
    } else {
      dom.topTitleText.textContent = 'No folder open';
      dom.topTitle.title = 'Open a folder to start composing';
    }
    return;
  }
  dom.topTitleIcon.hidden = true;
  dom.topTitleText.textContent = state.title || 'New conversation';
  dom.topTitle.title = state.title || 'New conversation';
}

/* -------------------------------------------------------------------------- */
/*  Workspace (folder opened for coding)                                      */
/* -------------------------------------------------------------------------- */
function setWorkspaceLabel(workspace) {
  if (workspace && workspace.path) {
    dom.composeFolderName.textContent = workspace.name || workspace.path;
    dom.composeFolder.title = workspace.path;
    dom.composeFolderStripName.textContent = workspace.path;
    dom.composeFolderStripName.title = workspace.path;
  } else {
    dom.composeFolderName.textContent = 'No folder open';
    dom.composeFolder.title = 'No folder open';
    dom.composeFolderStripName.textContent = 'No folder open';
    dom.composeFolderStripName.title = 'No folder open';
  }
  syncTopbarTitle();
}

async function loadWorkspace() {
  try {
    const result = await API.getWorkspace();
    state.workspace = result.workspace || null;
    setWorkspaceLabel(state.workspace);
    if (state.workspace) await refreshTree();
    else renderTree();
  } catch (error) {
    console.warn('Could not load workspace:', error.message);
  }
}

async function chooseWorkspace(path) {
  try {
    const result = await API.setWorkspace(path);
    state.workspace = result.workspace || null;
    setWorkspaceLabel(state.workspace);
    closeOpenFile();
    await refreshTree();
    if (state.workspace) {
      toast(`Opened ${state.workspace.name}.`, 'success', 2200);
    } else {
      toast('Folder closed.', 'info', 2000);
    }
    if (state.terminal?.id) {
      // Restart the terminal in the new folder so its cwd is correct.
      await restartTerminal();
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function refreshTree() {
  if (!state.workspace) {
    state.tree = [];
    renderTree();
    return;
  }
  try {
    const result = await API.workspaceTree();
    state.tree = result.entries || [];
    renderTree();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function fileIconFor(entry) {
  if (entry.type === 'dir') return 'folder';
  const ext = (entry.name.split('.').pop() || '').toLowerCase();
  if (['js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'py', 'rb', 'go', 'rs', 'java', 'c', 'cpp', 'cs', 'php', 'swift', 'kt', 'sh'].includes(ext)) return 'code';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp'].includes(ext)) return 'image';
  return 'file-text';
}

function renderTree(entries = state.tree) {
  dom.fileTree.innerHTML = '';
  if (!state.workspace) {
    dom.fileTree.innerHTML = '<div class="file-empty">Open a folder to browse its files.</div>';
    return;
  }
  if (!entries.length) {
    dom.fileTree.innerHTML = '<div class="file-empty">This folder is empty.</div>';
    return;
  }
  entries.forEach((entry) => {
    const row = document.createElement('div');
    row.className = `file-row${entry.type === 'dir' ? ' dir' : ''}`;
    row.style.paddingLeft = `${8 + entry.depth * 14}px`;
    if (state.openFile && state.openFile.path === entry.path) row.classList.add('active');
    row.title = entry.path;

    const main = document.createElement('button');
    main.type = 'button';
    main.className = 'file-row-main';
    main.innerHTML = `${icon(fileIconFor(entry))}<span class="file-row-name">${escapeHtml(entry.name)}</span>`;
    if (entry.type === 'file') {
      main.addEventListener('click', () => openFile(entry.path));
    } else {
      main.addEventListener('click', () => {
        row.classList.toggle('collapsed');
        const expanded = !row.classList.contains('collapsed');
        const prefix = entry.path.replace(/\\/g, '/') + '/';
        $$('.file-row', dom.fileTree).forEach((other) => {
          const otherPath = other.title.replace(/\\/g, '/');
          if (otherPath.startsWith(prefix)) other.classList.toggle('hidden-by-collapse', !expanded);
        });
      });
    }
    row.appendChild(main);

    const actions = document.createElement('div');
    actions.className = 'file-row-actions';
    const renameBtn = document.createElement('button');
    renameBtn.type = 'button';
    renameBtn.className = 'file-row-action';
    renameBtn.title = 'Rename';
    renameBtn.innerHTML = icon('edit');
    renameBtn.addEventListener('click', (event) => { event.stopPropagation(); renameWorkspaceEntry(entry); });
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'file-row-action danger';
    deleteBtn.title = 'Delete';
    deleteBtn.innerHTML = icon('trash');
    deleteBtn.addEventListener('click', (event) => { event.stopPropagation(); deleteWorkspaceEntry(entry); });
    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    row.appendChild(actions);

    dom.fileTree.appendChild(row);
  });
}

async function renameWorkspaceEntry(entry) {
  if (!state.workspace) return;
  const next = await promptDialog(
    'Rename',
    entry.path,
    'Enter the new path (subfolders allowed).',
    entry.path,
  );
  if (next === null || next === undefined) return;
  const trimmed = next.trim();
  if (!trimmed || trimmed === entry.path) return;
  try {
    await API.renameWorkspacePath(entry.path, trimmed);
    if (state.openFile && state.openFile.path === entry.path) {
      state.openFile.path = trimmed;
      dom.editorPathText.textContent = trimmed;
    }
    await refreshTree();
    toast('Renamed.', 'success', 1800);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function deleteWorkspaceEntry(entry) {
  if (!state.workspace) return;
  const label = entry.type === 'dir' ? 'folder' : 'file';
  const confirmed = await confirmDialog(
    `Delete ${label}`,
    `Delete ${label} “${entry.path}”? This cannot be undone.`,
  );
  if (!confirmed) return;
  try {
    await API.deleteWorkspacePath(entry.path);
    if (state.openFile && state.openFile.path === entry.path) closeOpenFile();
    await refreshTree();
    toast('Deleted.', 'success', 1800);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function openFile(path) {
  if (state.openFile?.dirty) {
    const discard = await confirmDialog('Unsaved changes', `Discard unsaved changes to ${state.openFile.path}?`, 'Discard');
    if (!discard) return;
  }
  try {
    const result = await API.readWorkspaceFile(path);
    const file = result.file;
    state.openFile = { path: file.path, content: file.content, dirty: false };
    dom.editorArea.value = file.content;
    dom.editorPane.hidden = false;
    dom.composeEmpty.hidden = true;
    dom.editorPathText.textContent = file.path;
    updateEditorStatus(file.truncated ? 'Truncated (large file)' : 'Saved');
    renderTree();
    dom.editorArea.focus();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function closeOpenFile() {
  state.openFile = null;
  dom.editorArea.value = '';
  dom.editorPane.hidden = true;
  dom.composeEmpty.hidden = false;
  renderTree();
}

function updateEditorStatus(text, dirty = false) {
  dom.editorStatus.textContent = text;
  dom.editorStatus.classList.toggle('dirty', dirty);
  dom.saveFileBtn.disabled = !state.openFile || !state.openFile.dirty;
}

async function saveOpenFile() {
  if (!state.openFile) return;
  try {
    const result = await API.writeWorkspaceFile(state.openFile.path, dom.editorArea.value);
    state.openFile.content = dom.editorArea.value;
    state.openFile.dirty = false;
    dom.editorPathText.textContent = result.file.path;
    updateEditorStatus('Saved');
    toast('File saved.', 'success', 1800);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function createNewFile() {
  if (!state.workspace) { toast('Open a folder first.', 'info'); return; }
  const path = await promptDialog('New file', 'untitled.txt', 'Enter a file name (subfolders are allowed).', 'untitled.txt');
  if (path === null) return;
  const trimmed = path.trim();
  if (!trimmed) return;
  try {
    await API.writeWorkspaceFile(trimmed, '');
    await refreshTree();
    await openFile(trimmed);
  } catch (error) {
    toast(error.message, 'error');
  }
}

const runWorkspaceSearch = debounce(async (query) => {
  if (!state.workspace) return;
  if (!query) { renderTree(); return; }
  try {
    const result = await API.searchWorkspace(query);
    renderTree((result.results || []).map((item) => ({
      path: item.path,
      name: item.line ? `${item.path}:${item.line}` : item.path,
      type: 'file',
      depth: 0,
    })));
  } catch (error) {
    toast(error.message, 'error');
  }
}, 250);

/* -------------------------------------------------------------------------- */
/*  Folder picker modal                                                       */
/* -------------------------------------------------------------------------- */
async function openFolderModal(startPath) {
  openOverlay(dom.folderModal);
  await browseFolder(startPath || state.workspace?.path || '');
}

function closeFolderModal() {
  closeOverlay(dom.folderModal);
}

async function browseFolder(path) {
  try {
    const result = await API.browseFolder(path || '');
    state.folderBrowse = result;
    dom.folderPath.textContent = result.path;
    dom.folderPath.title = result.path;
    dom.folderUp.disabled = !result.parent;
    renderFolderDrives(result.drives || []);
    renderFolderList(result.directories || []);
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderFolderDrives(drives) {
  dom.folderDrives.innerHTML = '';
  if (!drives.length) return;
  drives.forEach((drive) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'folder-drive';
    button.textContent = drive.name;
    button.addEventListener('click', () => browseFolder(drive.path));
    dom.folderDrives.appendChild(button);
  });
}

function renderFolderList(directories) {
  dom.folderList.innerHTML = '';
  if (!directories.length) {
    dom.folderList.innerHTML = '<div class="file-empty">No sub-folders here.</div>';
    return;
  }
  directories.forEach((dir) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'folder-item';
    item.innerHTML = `${icon('folder')}<span>${escapeHtml(dir.name)}</span>`;
    item.addEventListener('click', () => browseFolder(dir.path));
    dom.folderList.appendChild(item);
  });
}

/* -------------------------------------------------------------------------- */
/*  Terminal                                                                  */
/* -------------------------------------------------------------------------- */
const terminalState = { id: null, poll: null, busy: false };
state.terminal = terminalState;

async function openTerminal() {
  dom.terminalPanel.hidden = false;
  document.body.classList.add('terminal-open');
  dom.terminalResize.hidden = false;
  positionTerminalResize();
  if (!terminalState.id) {
    await startTerminal();
  } else {
    dom.terminalInput.focus();
  }
}

function closeTerminal() {
  dom.terminalPanel.hidden = true;
  dom.terminalResize.hidden = true;
  document.body.classList.remove('terminal-open');
  stopTerminalPoll();
}

function stopTerminalPoll() {
  if (terminalState.poll) {
    clearInterval(terminalState.poll);
    terminalState.poll = null;
  }
}

async function startTerminal(cwd) {
  try {
    const result = await API.createTerminal(cwd || state.workspace?.path || undefined);
    terminalState.id = result.session.id;
    dom.terminalCwd.textContent = result.session.cwd;
    dom.terminalPrompt.textContent = '>';
    dom.terminalOutput.textContent = '';
    appendTerminal(`Pike terminal — ${result.session.shell}\n\n`);
    dom.terminalInput.focus();
    stopTerminalPoll();
    terminalState.poll = setInterval(pollTerminal, 600);
  } catch (error) {
    toast(error.message, 'error');
    closeTerminal();
  }
}

async function restartTerminal() {
  if (terminalState.id) {
    try { await API.closeTerminal(terminalState.id); } catch { /* ignore */ }
  }
  terminalState.id = null;
  stopTerminalPoll();
  if (!dom.terminalPanel.hidden) await startTerminal();
}

async function pollTerminal() {
  if (!terminalState.id || terminalState.busy) return;
  try {
    const result = await API.readTerminal(terminalState.id);
    if (result.output) appendTerminal(result.output);
    if (result.running === false) {
      stopTerminalPoll();
      appendTerminal('\n[terminal closed]\n');
    }
  } catch (error) {
    stopTerminalPoll();
    console.warn('Terminal poll failed:', error.message);
  }
}

function appendTerminal(text) {
  if (!text) return;
  const atBottom =
    dom.terminalOutput.scrollHeight - dom.terminalOutput.scrollTop - dom.terminalOutput.clientHeight < 60;
  dom.terminalOutput.textContent += text;
  // Keep the buffer from growing without bound.
  if (dom.terminalOutput.textContent.length > 200000) {
    dom.terminalOutput.textContent = dom.terminalOutput.textContent.slice(-150000);
  }
  if (atBottom) dom.terminalOutput.scrollTop = dom.terminalOutput.scrollHeight;
}

async function submitTerminalCommand(command) {
  if (!terminalState.id) { await startTerminal(); return; }
  appendTerminal(`${dom.terminalPrompt.textContent} ${command}\n`);
  terminalState.busy = true;
  try {
    await API.writeTerminal(terminalState.id, command);
    // Give the shell a moment so the echo/output order stays sensible.
    setTimeout(pollTerminal, 120);
  } catch (error) {
    appendTerminal(`\n${error.message}\n`);
  } finally {
    terminalState.busy = false;
  }
}

function positionTerminalResize() {
  const height = dom.terminalPanel.offsetHeight;
  dom.terminalResize.style.bottom = `${height - 3}px`;
}

function initTerminalResize() {
  let dragging = false;
  let startY = 0;
  let startHeight = 0;

  const onMove = (event) => {
    if (!dragging) return;
    const delta = startY - event.clientY;
    const height = Math.min(Math.max(startHeight + delta, 140), window.innerHeight - 120);
    dom.terminalPanel.style.height = `${height}px`;
    document.body.style.setProperty('--terminal-h', `${height}px`);
    positionTerminalResize();
  };
  const onUp = () => {
    dragging = false;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  dom.terminalResize.addEventListener('mousedown', (event) => {
    dragging = true;
    startY = event.clientY;
    startHeight = dom.terminalPanel.offsetHeight;
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    event.preventDefault();
  });
}

/* -------------------------------------------------------------------------- */
/*  Event wiring                                                              */
/* -------------------------------------------------------------------------- */
function bindEvents() {
  // Composer
  dom.composeChooseFolder.addEventListener('click', openFolderModal);
  dom.prompt.addEventListener('input', autoResize);
  dom.prompt.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  dom.send.addEventListener('click', () => sendMessage());
  dom.stop.addEventListener('click', () => state.controller?.abort());

  // Attach menu
  dom.attachBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleAttachMenu(MAIN_ATTACH_REFS());
  });
  dom.attachMenu.addEventListener('click', (event) => event.stopPropagation());
  dom.attachMenu.addEventListener('click', (event) => {
    const option = event.target.closest('.attach-option');
    if (!option) return;
    closeAttachMenu(MAIN_ATTACH_REFS());
    const action = option.dataset.attach;
    if (action === 'files') dom.fileInput.click();
    else if (action === 'images') dom.imageInput.click();
    else if (action === 'code') addCodeSnippet();
  });
  dom.fileInput.addEventListener('change', (event) => {
    handleAttachFiles(event.target.files, 'file');
    event.target.value = '';
  });
  dom.imageInput.addEventListener('change', (event) => {
    handleAttachFiles(event.target.files, 'image');
    event.target.value = '';
  });

  // Compose attach menu
  dom.composeAttachBtn?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleAttachMenu(COMPOSE_ATTACH_REFS());
  });
  dom.composeAttachMenu?.addEventListener('click', (event) => event.stopPropagation());
  dom.composeAttachMenu?.addEventListener('click', (event) => {
    const option = event.target.closest('.attach-option');
    if (!option) return;
    closeAttachMenu(COMPOSE_ATTACH_REFS());
    const action = option.dataset.attach;
    if (action === 'files') dom.composeFileInput.click();
    else if (action === 'images') dom.composeImageInput.click();
    else if (action === 'code') addCodeSnippet();
  });
  dom.composeFileInput?.addEventListener('change', (event) => {
    handleAttachFiles(event.target.files, 'file');
    event.target.value = '';
  });
  dom.composeImageInput?.addEventListener('change', (event) => {
    handleAttachFiles(event.target.files, 'image');
    event.target.value = '';
  });

  // Model dropdown
  dom.modelTrigger.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleModelMenu(MAIN_MODEL_REFS());
  });
  dom.modelMenu.addEventListener('click', (event) => event.stopPropagation());
  dom.modelSearchInput.addEventListener('input', () => renderModelMenu(MAIN_MODEL_REFS()));
  dom.modelSearchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      const first = $('.model-option', dom.modelMenuList);
      if (first) first.click();
    }
  });
  dom.modelSelect.addEventListener('change', () => selectModel(dom.modelSelect.value));

  // Compose model dropdown (mirrors the main composer)
  dom.composeModelTrigger?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleModelMenu(COMPOSE_MODEL_REFS());
  });
  dom.composeModelMenu?.addEventListener('click', (event) => event.stopPropagation());
  dom.composeModelSearchInput?.addEventListener('input', () => renderModelMenu(COMPOSE_MODEL_REFS()));
  dom.composeModelSearchInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      const first = $('.model-option', dom.composeModelMenuList);
      if (first) first.click();
    }
  });
  dom.composeModelSelect?.addEventListener('change', () => selectModel(dom.composeModelSelect.value));

  // Thinking level dropdown
  dom.reasoningTrigger?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleReasoningMenu(MAIN_REASONING_REFS());
  });
  dom.reasoningMenu?.addEventListener('click', (event) => event.stopPropagation());

  // Compose thinking level dropdown
  dom.composeReasoningTrigger?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleReasoningMenu(COMPOSE_REASONING_REFS());
  });
  dom.composeReasoningMenu?.addEventListener('click', (event) => event.stopPropagation());

  document.addEventListener('click', () => { closeModelMenu(MAIN_MODEL_REFS()); closeModelMenu(COMPOSE_MODEL_REFS()); closeReasoningMenu(MAIN_REASONING_REFS()); closeReasoningMenu(COMPOSE_REASONING_REFS()); closeAttachMenu(MAIN_ATTACH_REFS()); closeAttachMenu(COMPOSE_ATTACH_REFS()); });

  // Projects
  dom.newProject.addEventListener('click', (event) => {
    event.stopPropagation();
    openProjectsModal();
  });
  dom.projectsHead.addEventListener('click', (event) => {
    if (event.target.closest('.icon-btn')) return;
    openProjectsModal();
  });
  dom.projectsHead.addEventListener('keydown', (event) => {
    if ((event.key === 'Enter' || event.key === ' ') && !event.target.closest('.icon-btn')) {
      event.preventDefault();
      openProjectsModal();
    }
  });
  dom.createProjectBtn.addEventListener('click', () => {
    if (createProject(dom.projectNameInput.value)) dom.projectNameInput.value = '';
  });
  dom.projectNameInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (createProject(dom.projectNameInput.value)) dom.projectNameInput.value = '';
    }
  });
  dom.projectModalClose.addEventListener('click', closeProjectsModal);
  dom.projectModal.addEventListener('mousedown', (event) => {
    if (event.target === dom.projectModal) closeProjectsModal();
  });

  // Sidebar
  dom.newChat.addEventListener('click', newConversation);
  dom.menuBtn.addEventListener('click', openSidebar);
  dom.sidebarClose.addEventListener('click', closeSidebar);
  dom.backdrop.addEventListener('click', closeSidebar);
  dom.connectCard.addEventListener('click', openConnectModal);
  dom.settingsBtn.addEventListener('click', () => openSettings('connection'));
  dom.windowUpdate?.addEventListener('click', checkForUpdate);
  dom.clearHistory.addEventListener('click', async () => {
    if (!state.history.length) { toast('There is no history to clear.', 'info'); return; }
    await clearAllConversations();
  });

  // Search
  const runSearch = debounce((value) => loadHistory(value), 220);
  dom.searchInput.addEventListener('input', () => {
    const value = dom.searchInput.value.trim();
    dom.searchClear.hidden = !value;
    runSearch(value);
  });
  dom.searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      dom.searchInput.value = '';
      dom.searchClear.hidden = true;
      loadHistory('');
    }
  });
  dom.searchClear.addEventListener('click', () => {
    dom.searchInput.value = '';
    dom.searchClear.hidden = true;
    loadHistory('');
    dom.searchInput.focus();
  });

  // Connect modal
  dom.connectModalClose.addEventListener('click', closeConnectModal);
  dom.connectModal.addEventListener('mousedown', (event) => {
    if (event.target === dom.connectModal) closeConnectModal();
  });

  // Settings modal
  dom.modalClose.addEventListener('click', () => closeOverlay(dom.settingsModal));
  dom.settingsModal.addEventListener('mousedown', (event) => {
    if (event.target === dom.settingsModal) closeOverlay(dom.settingsModal);
  });
  dom.saveKey.addEventListener('click', saveSettings);
  dom.removeKey.addEventListener('click', removeKey);
  dom.testConnection.addEventListener('click', testConnection);
  wireProviderEvents();
  dom.toggleKey.addEventListener('click', () => {
    const isPassword = dom.apiKeyInput.type === 'password';
    dom.apiKeyInput.type = isPassword ? 'text' : 'password';
    dom.toggleKey.innerHTML = icon(isPassword ? 'eye-off' : 'eye');
  });
  dom.settingsTabs.addEventListener('click', (event) => {
    const tab = event.target.closest('.settings-tab');
    if (tab) switchSettingsTab(tab.dataset.tab);
  });
  dom.themeOptions.addEventListener('click', (event) => {
    const option = event.target.closest('.theme-option');
    if (option) applyTheme(option.dataset.theme);
  });
  dom.compactToggle.addEventListener('click', () => {
    setCompact(dom.compactToggle.getAttribute('aria-checked') !== 'true');
  });
  dom.exportHistory.addEventListener('click', exportConversations);
  dom.clearAllData.addEventListener('click', clearAllConversations);
  dom.clearProjects.addEventListener('click', clearAllProjects);

  // View tabs
  dom.viewTabs.addEventListener('click', (event) => {
    const tab = event.target.closest('.view-tab');
    if (tab) setView(tab.dataset.view);
  });

  // Right files panel
  dom.panelToggle.addEventListener('click', togglePanel);

  // Workspace / compose
  dom.openFolderBtn.addEventListener('click', () => openFolderModal());
  dom.newFileBtn.addEventListener('click', createNewFile);
  dom.refreshTreeBtn.addEventListener('click', refreshTree);
  dom.workspaceSearchInput.addEventListener('input', () => {
    runWorkspaceSearch(dom.workspaceSearchInput.value.trim());
  });
  dom.editorArea.addEventListener('input', () => {
    if (!state.openFile) return;
    state.openFile.dirty = dom.editorArea.value !== state.openFile.content;
    updateEditorStatus(state.openFile.dirty ? 'Unsaved changes' : 'Saved', state.openFile.dirty);
  });
  dom.editorArea.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') {
      event.preventDefault();
      const start = dom.editorArea.selectionStart;
      const end = dom.editorArea.selectionEnd;
      dom.editorArea.value = `${dom.editorArea.value.slice(0, start)}  ${dom.editorArea.value.slice(end)}`;
      dom.editorArea.selectionStart = dom.editorArea.selectionEnd = start + 2;
      dom.editorArea.dispatchEvent(new Event('input'));
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      saveOpenFile();
    }
  });
  dom.saveFileBtn.addEventListener('click', saveOpenFile);

  // Folder picker
  dom.composeChooseFolder.addEventListener('click', openFolderModal);
  dom.openFolderEmpty.addEventListener('click', openFolderModal);
  const sendComposeMessage = () => {
    const content = dom.composePrompt.value.trim();
    if (!content || state.streaming) return;
    dom.composePrompt.value = '';
    // The backend already injects workspace context, so send the message as-is.
    sendMessage(content);
  };
  dom.composePrompt.addEventListener('input', autoResize);
  dom.composePrompt.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendComposeMessage();
    }
  });
  dom.composeSend.addEventListener('click', sendComposeMessage);
  dom.folderModalClose.addEventListener('click', closeFolderModal);
  dom.folderModal.addEventListener('mousedown', (event) => {
    if (event.target === dom.folderModal) closeFolderModal();
  });
  dom.folderUp.addEventListener('click', () => {
    if (state.folderBrowse?.parent) browseFolder(state.folderBrowse.parent);
  });
  dom.folderChoose.addEventListener('click', async () => {
    if (!state.folderBrowse) return;
    closeFolderModal();
    await chooseWorkspace(state.folderBrowse.path);
  });

  // Terminal
  dom.terminalTop.addEventListener('click', () => {
    if (dom.terminalPanel.hidden) openTerminal();
    else { closeTerminal(); }
  });
  dom.terminalCloseBtn.addEventListener('click', closeTerminal);
  dom.terminalNewBtn.addEventListener('click', restartTerminal);
  dom.terminalClearBtn.addEventListener('click', () => { dom.terminalOutput.textContent = ''; });
  dom.terminalForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const command = dom.terminalInput.value;
    dom.terminalInput.value = '';
    submitTerminalCommand(command);
  });
  dom.terminalInput.addEventListener('keydown', (event) => {
    if (event.ctrlKey && event.key.toLowerCase() === 'c') {
      event.preventDefault();
      if (terminalState.id) API.interruptTerminal(terminalState.id).catch(() => {});
    }
  });
  initTerminalResize();

  // Scroll-to-bottom hint
  dom.conversation.addEventListener('scroll', () => {
    const distance = dom.conversation.scrollHeight - dom.conversation.scrollTop - dom.conversation.clientHeight;
    dom.scrollBottom.hidden = distance < 260;
  });
  dom.scrollBottom.addEventListener('click', () => scrollToBottom(true));

  // Keyboard shortcuts
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      newConversation();
    } else if (event.key === 'Escape') {
      if (openOverlays.size) closeAllOverlays();
      else if (!dom.terminalPanel.hidden) closeTerminal();
      else if (!dom.attachMenu.hidden) closeAttachMenu(MAIN_ATTACH_REFS());
      else if (dom.composeAttachMenu && !dom.composeAttachMenu.hidden) closeAttachMenu(COMPOSE_ATTACH_REFS());
      else if (!dom.modelMenu.hidden) closeModelMenu(MAIN_MODEL_REFS());
      else if (dom.composeModelMenu && !dom.composeModelMenu.hidden) closeModelMenu(COMPOSE_MODEL_REFS());
      else if (dom.reasoningMenu && !dom.reasoningMenu.hidden) closeReasoningMenu(MAIN_REASONING_REFS());
      else if (dom.composeReasoningMenu && !dom.composeReasoningMenu.hidden) closeReasoningMenu(COMPOSE_REASONING_REFS());
      else if (state.streaming) state.controller?.abort();
    }
  });

  // In-app dialog
  dom.dialogConfirm.addEventListener('click', () => {
    settleDialog(dialogReturnsValue ? dom.dialogInput.value : true);
  });
  dom.dialogCancel.addEventListener('click', () => settleDialog(dialogReturnsValue ? null : false));
  dom.dialogModal.addEventListener('mousedown', (event) => {
    if (event.target === dom.dialogModal) settleDialog(dialogReturnsValue ? null : false);
  });
  dom.dialogInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && (dom.dialogInput.rows === 1 || event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      settleDialog(dom.dialogInput.value);
    }
  });

  window.addEventListener('resize', debounce(() => {
    if (!window.matchMedia('(max-width: 900px)').matches) closeSidebar();
    autoResize();
    closeModelMenu(MAIN_MODEL_REFS());
    closeModelMenu(COMPOSE_MODEL_REFS());
    closeReasoningMenu(MAIN_REASONING_REFS());
    closeReasoningMenu(COMPOSE_REASONING_REFS());
    closeAttachMenu(MAIN_ATTACH_REFS());
    closeAttachMenu(COMPOSE_ATTACH_REFS());
    if (!dom.terminalPanel.hidden) positionTerminalResize();
  }, 150));

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (state.theme === 'system') applyTheme('system');
  });

  window.addEventListener('beforeunload', () => {
    if (state.streaming) state.controller?.abort();
    stopTerminalPoll();
  });
}

/* -------------------------------------------------------------------------- */
/*  Boot                                                                      */
/* -------------------------------------------------------------------------- */
async function init() {
  const boot = window.__pikeBoot || { setStatus() {}, done() {} };
  const setupWindowControls = () => {
    if (!window.pywebview?.api || document.body.classList.contains('desktop-window')) return;
    document.body.classList.add('desktop-window');
    window.__setWindowMaximized = (maximized) => {
      const isMax = !!maximized;
      document.body.classList.toggle('is-maximized', isMax);
      const btn = document.getElementById('windowMaximize');
      if (btn) {
        const label = isMax ? 'Restore' : 'Maximize';
        btn.title = label;
        btn.setAttribute('aria-label', label);
      }
    };
    document.getElementById('windowMinimize').addEventListener('click', () => window.pywebview.api.minimize());
    document.getElementById('windowMaximize').addEventListener('click', async () => {
      const maximized = await window.pywebview.api.toggle_maximize();
      window.__setWindowMaximized(maximized);
    });
    document.getElementById('windowClose').addEventListener('click', () => window.pywebview.api.close());
    // Signal that the title bar (close / minimize / restore / update) is wired
    // up and rendered, so the preloader can stop only once it is on screen.
    window.__pikeControlsReady = true;
  };
  setupWindowControls();
  window.__pikeSetupControls = setupWindowControls;
  window.addEventListener('pywebviewready', setupWindowControls, { once: true });

  boot.setStatus('Preparing window...', 0.1);
  // Wait for the native window controls to be ready before anything else, so
  // the preloader never hands off to a window with a missing/half-drawn bar.
  await waitForWindowControls();
  await nextPaint();

  boot.setStatus('Preparing workspace...', 0.25);
  applyTheme(state.theme);
  setCompact(readLocal(COMPACT_KEY, false));
  bindEvents();
  renderAttachments();
  autoResize();
  loadProjects();
  setView(state.view, { focus: false });

  boot.setStatus('Loading workspace...', 0.45);
  await loadWorkspace();
  boot.setStatus('Connecting to backend...', 0.7);
  await refreshStatus();
  boot.setStatus('Loading conversations...', 0.9);
  await loadHistory('');

  // Everything the first paint depends on is ready: reveal the app and stop
  // the preloader.
  boot.setStatus('Ready', 1);
  await nextPaint();
  boot.done();
  dom.prompt.focus();

  if (!state.configured) {
    setTimeout(() => toast('Add your API key to start chatting.', 'info', 5000), 700);
  }
}

/** Wait until the native window bar has been built (no-op in browser mode). */
function waitForWindowControls(timeout = 20000) {
  if (!window.__pikeDesktop) return Promise.resolve();
  if (window.__pikeControlsReady) return Promise.resolve();
  return new Promise((resolve) => {
    const started = Date.now();
    const tick = () => {
      // pywebview may have injected its API before we attached the event
      // listener; retry the setup so the flag still gets flipped.
      if (!window.__pikeControlsReady) window.__pikeSetupControls?.();
      if (window.__pikeControlsReady || Date.now() - started > timeout) {
        resolve();
        return;
      }
      requestAnimationFrame(tick);
    };
    // pywebview injects its API slightly after DOMContentLoaded; the
    // pywebviewready listener in setupWindowControls flips the flag.
    requestAnimationFrame(tick);
  });
}

/** Resolve after the browser has actually painted two frames. */
function nextPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

// If the initial load throws, never leave the user stuck on the preloader.
window.addEventListener('error', () => window.__pikeBoot?.done());
window.addEventListener('unhandledrejection', () => window.__pikeBoot?.done());

document.addEventListener('DOMContentLoaded', () => {
  init().catch((error) => {
    console.error('Boot failed:', error);
    window.__pikeBoot?.done();
  });
});