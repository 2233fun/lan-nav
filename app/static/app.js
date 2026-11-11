/* 邻页 · 局域网导航 —— 原生 JavaScript，无构建步骤、无外部依赖。 */
"use strict";

const API_BASE = "/api";
const SVG_NS = "http://www.w3.org/2000/svg";
const TONE_COUNT = 6;
const EXPANDED_KEY = "lannav.expanded";
const AUTO_CHECK_KEY = "lannav.autoCheck";
const DOCS_VISIBLE_KEY = "lannav.showDocs";
const CHECK_BATCH_SIZE = 15;
const AUTO_CHECK_LIMIT = 20;
const CHECK_TTL_MS = 60_000;
const LONG_PRESS_MS = 450;
const DRAG_TOLERANCE_PX = 8;

const state = {
  tree: { groups: [], total_groups: 0, total_links: 0 },
  selectedId: null,
  search: "",
  expanded: new Set(),
  expandedInitialized: false,
  loading: true,
  loadError: false,
  linkChecks: new Map(),
  currentEntries: [],
  currentViewMode: "all",
  currentCheckView: null,
  autoCheckEnabled: true,
  autoCheckTimer: null,
  batchRun: null,
  singleChecks: new Map(),
  progressTimer: null,
  docsVisible: false,
  docsGroupId: null,
  docs: [],
  docsLoaded: false,
  docsLoading: false,
  docsError: "",
  currentDoc: null,
  docEditing: false,
  docEditingId: null,
  docsRequestId: 0,
  dragState: null,
  suppressClick: false,
};

const els = {};

document.addEventListener("DOMContentLoaded", init);

function init() {
  els.menuToggle = document.querySelector("#menuToggle");
  els.sidebar = document.querySelector("#sidebar");
  els.scrim = document.querySelector("#scrim");
  els.searchInput = document.querySelector("#searchInput");
  els.clearSearch = document.querySelector("#clearSearch");
  els.newGroupTop = document.querySelector("#newGroupTop");
  els.newLinkTop = document.querySelector("#newLinkTop");
  els.sidebarNewGroup = document.querySelector("#sidebarNewGroup");
  els.sidebarClose = document.querySelector("#sidebarClose");
  els.allLinksNav = document.querySelector("#allLinksNav");
  els.allCount = document.querySelector("#allCount");
  els.groupCount = document.querySelector("#groupCount");
  els.groupTree = document.querySelector("#groupTree");
  els.treeEmpty = document.querySelector("#treeEmpty");
  els.treeEmptyCreate = document.querySelector("#treeEmptyCreate");
  els.breadcrumbs = document.querySelector("#breadcrumbs");
  els.pageActions = document.querySelector("#pageActions");
  els.addSubgroupBtn = document.querySelector("#addSubgroupBtn");
  els.editGroupBtn = document.querySelector("#editGroupBtn");
  els.deleteGroupBtn = document.querySelector("#deleteGroupBtn");
  els.addHereBtn = document.querySelector("#addHereBtn");
  els.openDocsBtn = document.querySelector("#openDocsBtn");
  els.pageTitle = document.querySelector("#pageTitle");
  els.pageSummary = document.querySelector("#pageSummary");
  els.checkTools = document.querySelector("#checkTools");
  els.checkProgress = document.querySelector("#checkProgress");
  els.autoCheckToggle = document.querySelector("#autoCheckToggle");
  els.checkAllBtn = document.querySelector("#checkAllBtn");
  els.checkAllLabel = document.querySelector("#checkAllLabel");
  els.loadingState = document.querySelector("#loadingState");
  els.loadError = document.querySelector("#loadError");
  els.retryBtn = document.querySelector("#retryBtn");
  els.emptyState = document.querySelector("#emptyState");
  els.emptyTitle = document.querySelector("#emptyTitle");
  els.emptyText = document.querySelector("#emptyText");
  els.emptyActions = document.querySelector("#emptyActions");
  els.linkGrid = document.querySelector("#linkGrid");
  els.statusDot = document.querySelector("#statusDot");
  els.healthText = document.querySelector("#healthText");
  els.exportBtn = document.querySelector("#exportBtn");
  els.importBtn = document.querySelector("#importBtn");
  els.importFile = document.querySelector("#importFile");
  els.groupDialog = document.querySelector("#groupDialog");
  els.groupForm = document.querySelector("#groupForm");
  els.groupDialogTitle = document.querySelector("#groupDialogTitle");
  els.groupParentSelect = document.querySelector("#groupParentSelect");
  els.groupSubmitBtn = document.querySelector("#groupSubmitBtn");
  els.linkDialog = document.querySelector("#linkDialog");
  els.linkForm = document.querySelector("#linkForm");
  els.linkDialogTitle = document.querySelector("#linkDialogTitle");
  els.linkGroupSelect = document.querySelector("#linkGroupSelect");
  els.linkSubmitBtn = document.querySelector("#linkSubmitBtn");
  els.linkFormError = document.querySelector("#linkFormError");
  els.confirmDialog = document.querySelector("#confirmDialog");
  els.confirmTitle = document.querySelector("#confirmTitle");
  els.confirmMessage = document.querySelector("#confirmMessage");
  els.confirmOk = document.querySelector("#confirmOk");
  els.confirmCancel = document.querySelector("#confirmCancel");
  els.toasts = document.querySelector("#toasts");
  els.mainInner = document.querySelector(".main-inner");
  els.contentSplit = document.querySelector("#contentSplit");
  els.docsPane = document.querySelector("#docsPane");
  els.docsMeta = document.querySelector("#docsMeta");
  els.docToggle = document.querySelector("#docToggle");
  els.docSelect = document.querySelector("#docSelect");
  els.docNewBtn = document.querySelector("#docNewBtn");
  els.docEditBtn = document.querySelector("#docEditBtn");
  els.docDeleteBtn = document.querySelector("#docDeleteBtn");
  els.docBody = document.querySelector("#docBody");
  els.docEditor = document.querySelector("#docEditor");
  els.docNameInput = document.querySelector("#docNameInput");
  els.docContentInput = document.querySelector("#docContentInput");
  els.docEditorStatus = document.querySelector("#docEditorStatus");
  els.docSaveBtn = document.querySelector("#docSaveBtn");
  els.docCancelBtn = document.querySelector("#docCancelBtn");

  initAutoCheckPreference();
  initDocsPreference();
  bindEvents();
  syncSidebarA11y();
  boot();
}

async function boot() {
  state.loading = true;
  state.loadError = false;
  renderMain();
  await loadTree(true);
  await loadHealth();
}

async function loadHealth() {
  try {
    const health = await api("/health");
    els.statusDot.classList.remove("is-offline");
    els.statusDot.classList.add("is-online");
    els.healthText.textContent = `服务正常 · v${health.version}`;
  } catch {
    els.statusDot.classList.remove("is-online");
    els.statusDot.classList.add("is-offline");
    els.healthText.textContent = "服务暂时不可用";
  }
}

async function loadTree(initial = false) {
  try {
    const data = await api("/tree");
    state.tree = data;
    state.loadError = false;

    if (!state.expandedInitialized) {
      initExpandedState();
    }
    if (state.selectedId !== null && !findGroupById(state.selectedId)) {
      state.selectedId = null;
    }

    renderSidebar();
    renderMain();
  } catch (error) {
    if (initial || state.tree.groups.length === 0) {
      state.loadError = true;
      renderMain();
    } else {
      toast(error.message, "error");
    }
  } finally {
    state.loading = false;
    if (initial) {
      renderMain();
    }
  }
}

function initExpandedState() {
  state.expandedInitialized = true;
  let stored = null;
  try {
    stored = localStorage.getItem(EXPANDED_KEY);
  } catch {
    stored = null;
  }
  const allIds = new Set(flattenGroups().map((item) => item.group.id));
  if (stored !== null) {
    try {
      const ids = JSON.parse(stored);
      if (Array.isArray(ids)) {
        const valid = ids.filter((id) => Number.isInteger(id) && allIds.has(id));
        // 数据被导入/恢复后 id 会变化；旧 id 全部失效时重新展开整棵树。
        if (valid.length > 0 || allIds.size === 0) {
          state.expanded = new Set(valid);
          return;
        }
      }
    } catch {
      // 损坏的本地状态不影响使用，退回全部展开。
    }
  }
  state.expanded = new Set(allIds);
}

function persistExpanded() {
  try {
    localStorage.setItem(EXPANDED_KEY, JSON.stringify([...state.expanded]));
  } catch {
    // 浏览器禁用 localStorage 时仅在本次会话保留展开状态。
  }
}

function expandAncestors(groupId) {
  const item = flattenGroups().find((entry) => entry.group.id === groupId);
  if (!item) return;
  item.path.forEach((group) => state.expanded.add(group.id));
  persistExpanded();
}

/* ---------- 通用工具 ---------- */

function icon(name, className = "icon") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

function button(className, label, iconName) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  if (label) {
    node.title = label;
    node.setAttribute("aria-label", label);
  }
  if (iconName) node.append(icon(iconName));
  return node;
}

function api(path, options = {}) {
  const request = {
    method: options.method || "GET",
    headers: { ...(options.headers || {}) },
  };
  if (options.signal) request.signal = options.signal;
  if (options.body !== undefined) {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(options.body);
  }
  return fetch(`${API_BASE}${path}`, request).then(async (response) => {
    if (!response.ok) {
      let message = `请求失败（${response.status}）`;
      try {
        const data = await response.json();
        if (typeof data.detail === "string") message = data.detail;
        else if (Array.isArray(data.detail)) message = "请求参数不合法";
      } catch {
        // 保留默认错误文案。
      }
      throw new Error(message);
    }
    if (response.status === 204) return null;
    const type = response.headers.get("content-type") || "";
    return type.includes("application/json") ? response.json() : response.text();
  }).catch((error) => {
    if (error instanceof TypeError) {
      throw new Error("网络连接失败，请确认服务正在运行");
    }
    throw error;
  });
}

function toast(message, type = "success") {
  while (els.toasts.children.length >= 4) {
    els.toasts.firstElementChild.remove();
  }
  const node = el("div", `toast${type === "error" ? " is-error" : ""}`);
  node.append(el("span", "toast-dot"));
  node.append(el("span", "", message));
  els.toasts.append(node);
  window.setTimeout(() => {
    node.classList.add("is-leaving");
    window.setTimeout(() => node.remove(), 320);
  }, type === "error" ? 4800 : 3200);
}

function setButtonBusy(buttonEl, busy, busyText) {
  if (!buttonEl) return;
  if (busy) {
    buttonEl.dataset.originalText = buttonEl.textContent;
    buttonEl.textContent = busyText || "处理中…";
    buttonEl.disabled = true;
  } else {
    buttonEl.textContent = buttonEl.dataset.originalText || buttonEl.textContent;
    buttonEl.disabled = false;
  }
}

function toneFor(group) {
  const name = group && group.name ? group.name : "";
  let hash = 0;
  for (const char of name) {
    hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  }
  return hash % TONE_COUNT;
}

/* ---------- 数据查找 ---------- */

function flattenGroups(groups = state.tree.groups, depth = 0, parentPath = []) {
  const result = [];
  for (const group of groups) {
    const path = [...parentPath, group];
    result.push({ group, depth, path });
    if (group.children && group.children.length) {
      result.push(...flattenGroups(group.children, depth + 1, path));
    }
  }
  return result;
}

function findGroupById(id) {
  const item = flattenGroups().find((entry) => entry.group.id === id);
  return item ? item.group : null;
}

function findGroupItem(id) {
  return flattenGroups().find((entry) => entry.group.id === id) || null;
}

function locateLink(linkId) {
  let found = null;
  function walk(groups, path) {
    for (const group of groups) {
      const nextPath = [...path, group];
      const link = group.links.find((entry) => entry.id === linkId);
      if (link) {
        found = { link, group, path: nextPath };
        return true;
      }
      if (group.children && walk(group.children, nextPath)) {
        return true;
      }
    }
    return false;
  }
  walk(state.tree.groups, []);
  return found;
}

function allLinksWithGroups() {
  const result = [];
  function walk(groups, path) {
    for (const group of groups) {
      const nextPath = [...path, group];
      for (const link of group.links) {
        result.push({ link, group, path: nextPath });
      }
      if (group.children && group.children.length) {
        walk(group.children, nextPath);
      }
    }
  }
  walk(state.tree.groups, []);
  return result;
}

function descendantIds(group) {
  const ids = new Set();
  function walk(node) {
    for (const child of node.children || []) {
      ids.add(child.id);
      walk(child);
    }
  }
  walk(group);
  return ids;
}

function groupPathText(path) {
  return path.map((group) => group.name).join(" / ");
}

/* ---------- 侧栏 ---------- */

function renderSidebar() {
  els.allCount.textContent = String(state.tree.total_links || 0);
  els.groupCount.textContent = String(state.tree.total_groups || 0);
  els.allLinksNav.classList.toggle("is-active", !state.search && state.selectedId === null);
  els.groupTree.replaceChildren();

  if (!state.tree.groups.length) {
    els.treeEmpty.hidden = false;
    return;
  }
  els.treeEmpty.hidden = true;
  const fragment = document.createDocumentFragment();
  for (const group of state.tree.groups) {
    fragment.append(buildTreeNode(group));
  }
  els.groupTree.append(fragment);
}

function buildTreeNode(group) {
  const hasChildren = Boolean(group.children && group.children.length);
  const expanded = state.expanded.has(group.id);
  const node = el("div", "tree-node");
  node.dataset.groupId = String(group.id);
  if (hasChildren && !expanded) node.classList.add("is-collapsed");

  const row = el("div", "tree-row");
  row.classList.toggle("is-active", !state.search && state.selectedId === group.id);

  if (hasChildren) {
    const toggle = button("tree-toggle", expanded ? "折叠子分组" : "展开子分组");
    toggle.dataset.action = "toggle";
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.append(icon("chevron"));
    row.append(toggle);
  } else {
    row.append(el("span", "tree-no-children"));
  }

  const select = button("tree-select");
  select.dataset.action = "select";
  select.append(icon("folder", "icon folder-icon"));
  select.append(el("span", "tree-name", group.name));
  select.append(el("span", "tree-count", String(group.total_link_count || 0)));
  if (state.selectedId === group.id && !state.search) {
    select.setAttribute("aria-current", "page");
  }
  row.append(select);

  if ((group.direct_document_count || 0) > 0) {
    const docs = button("tree-doc", `查看「${group.name}」的文档`, "doc");
    docs.dataset.action = "docs";
    row.append(docs);
  }

  const actions = el("span", "tree-actions");
  const add = button("tree-action", "在「" + group.name + "」下新建子分组", "plus");
  add.dataset.action = "add-child";
  const edit = button("tree-action", "编辑分组「" + group.name + "」", "edit");
  edit.dataset.action = "edit-group";
  actions.append(add, edit);
  row.append(actions);

  node.append(row);

  if (hasChildren && expanded) {
    const children = el("div", "tree-children");
    for (const child of group.children) {
      children.append(buildTreeNode(child));
    }
    node.append(children);
  }
  return node;
}

/* ---------- 主内容 ---------- */

function renderMain() {
  els.loadingState.hidden = !state.loading;
  els.loadError.hidden = !state.loadError || state.loading;

  if (state.loading) {
    els.linkGrid.replaceChildren();
    els.emptyState.hidden = true;
    els.pageActions.hidden = true;
    els.checkTools.hidden = true;
    state.currentEntries = [];
    hideDocsPane();
    return;
  }

  if (state.loadError) {
    els.linkGrid.replaceChildren();
    els.emptyState.hidden = true;
    els.pageActions.hidden = true;
    els.checkTools.hidden = true;
    state.currentEntries = [];
    els.pageTitle.textContent = "无法加载导航";
    els.pageSummary.textContent = "服务连接中断，请稍后重试。";
    els.breadcrumbs.replaceChildren();
    hideDocsPane();
    return;
  }

  els.linkGrid.replaceChildren();
  const search = state.search.trim();
  let entries = [];
  let showGroup = false;
  let canReorder = false;
  let mode = "all";
  let currentItem = null;

  if (search) {
    mode = "search";
    const needle = search.toLocaleLowerCase();
    entries = allLinksWithGroups().filter(({ link }) => {
      return (
        link.title.toLocaleLowerCase().includes(needle) ||
        link.url.toLocaleLowerCase().includes(needle) ||
        (link.description || "").toLocaleLowerCase().includes(needle)
      );
    });
    showGroup = true;
    setPageHeader("搜索结果", `找到 ${entries.length} 条包含「${search}」的链接`);
    document.title = `搜索 ${search} · 邻页`;
  } else if (state.selectedId !== null) {
    currentItem = findGroupItem(state.selectedId);
    if (!currentItem) {
      state.selectedId = null;
      renderSidebar();
    } else {
      mode = "group";
      canReorder = true;
      const group = currentItem.group;
      entries = group.links.map((link) => ({ link, group, path: currentItem.path }));
      const summary = [];
      summary.push(`${group.direct_link_count || 0} 条直属链接`);
      if (group.children.length) summary.push(`${group.children.length} 个子分组`);
      if (group.children.length) summary.push(`共 ${group.total_link_count} 条链接`);
      setPageHeader(group.name, summary.join(" · "));
      document.title = `${group.name} · 邻页`;
    }
  }

  if (!search && state.selectedId === null) {
    entries = allLinksWithGroups();
    showGroup = true;
    setPageHeader(
      "全部链接",
      state.tree.total_groups
        ? `${state.tree.total_groups} 个分组 · ${state.tree.total_links} 条链接`
        : "从建立第一个分组开始，收藏局域网里的入口"
    );
    document.title = "邻页 · 局域网导航";
  }

  const viewKey = search
    ? `search:${search}`
    : state.selectedId === null
      ? "all"
      : `group:${state.selectedId}`;
  const viewChanged = viewKey !== state.currentCheckView;
  state.currentEntries = entries;
  state.currentViewMode = mode;
  if (viewChanged) {
    state.currentCheckView = viewKey;
    cancelAllChecks();
  }
  updateCheckToolbar();
  updateDocsLayout(mode, currentItem);

  renderBreadcrumbs(mode, currentItem, search);
  els.pageActions.hidden = mode !== "group";
  const hasGroupDocs =
    mode === "group" && Boolean(currentItem && currentItem.group.direct_document_count);
  els.openDocsBtn.hidden = !hasGroupDocs;
  els.openDocsBtn.classList.toggle("is-active", hasGroupDocs && state.docsVisible);
  els.emptyActions.replaceChildren();
  els.emptyState.hidden = true;

  if (!entries.length) {
    showEmptyState(mode, currentItem, search);
    return;
  }

  const fragment = document.createDocumentFragment();
  entries.forEach((entry, index) => {
    fragment.append(
      createLinkCard(entry, index, entries.length, {
        showGroup,
        canReorder,
        query: search,
      })
    );
  });
  els.linkGrid.append(fragment);

  if (viewChanged && state.autoCheckEnabled && mode !== "search") {
    scheduleAutoCheck();
  }
}

function setPageHeader(title, summary) {
  els.pageTitle.textContent = title;
  els.pageSummary.textContent = summary;
}

/* ---------- 分组文档 ---------- */

function hideDocsPane() {
  els.docsPane.hidden = true;
  els.contentSplit.classList.remove("has-docs");
  els.mainInner.classList.remove("docs-open");
}

function updateDocsLayout(mode, currentItem) {
  const show = Boolean(
    state.docsVisible && mode === "group" && currentItem && currentItem.group
  );
  els.docsPane.hidden = !show;
  els.contentSplit.classList.toggle("has-docs", show);
  els.mainInner.classList.toggle("docs-open", show);
  if (show) ensureDocsForGroup(currentItem.group.id);
}

function ensureDocsForGroup(groupId) {
  if (state.docsGroupId === groupId) {
    renderDocsPane();
    if (
      state.docsLoaded &&
      !state.docsLoading &&
      !state.docEditing &&
      !state.currentDoc &&
      state.docs.length
    ) {
      loadDocument(state.docs[0].id);
    }
    return;
  }

  state.docsGroupId = groupId;
  state.docs = [];
  state.docsLoaded = false;
  state.docsLoading = true;
  state.docsError = "";
  state.currentDoc = null;
  state.docEditing = false;
  state.docEditingId = null;
  const requestId = ++state.docsRequestId;
  renderDocsPane();

  api(`/groups/${groupId}/documents`)
    .then((data) => {
      if (requestId !== state.docsRequestId || state.docsGroupId !== groupId) return;
      state.docs = data.documents || [];
      state.docsLoaded = true;
      state.docsLoading = false;
      renderDocsPane();
      if (state.docs.length) {
        const preferred =
          state.docs.find((doc) => doc.name.toLowerCase() === "readme.md") ||
          state.docs[0];
        loadDocument(preferred.id);
      }
    })
    .catch((error) => {
      if (requestId !== state.docsRequestId || state.docsGroupId !== groupId) return;
      state.docsLoading = false;
      state.docsError = error.message;
      renderDocsPane();
    });
}

async function loadDocument(documentId) {
  const groupId = state.docsGroupId;
  const requestId = state.docsRequestId;
  try {
    const doc = await api(`/documents/${documentId}`);
    if (requestId !== state.docsRequestId || state.docsGroupId !== groupId) return;
    state.currentDoc = doc;
    state.docEditing = false;
    state.docEditingId = null;
    state.docsError = "";
    renderDocsPane();
  } catch (error) {
    if (requestId !== state.docsRequestId || state.docsGroupId !== groupId) return;
    state.docsError = error.message;
    renderDocsPane();
  }
}

function renderDocsPane() {
  const docs = state.docs;
  els.docSelect.replaceChildren(
    ...docs.map((doc) => new Option(doc.name, String(doc.id)))
  );
  if (state.currentDoc) {
    els.docSelect.value = String(state.currentDoc.id);
  }
  els.docSelect.disabled = state.docEditing || docs.length === 0;
  els.docNewBtn.disabled = state.docEditing;
  els.docEditBtn.disabled = state.docEditing || !state.currentDoc;
  els.docDeleteBtn.disabled = state.docEditing || !state.currentDoc;
  els.docsMeta.textContent = state.docsLoading
    ? "加载中…"
    : state.docs.length
      ? `${state.docs.length} 篇`
      : "";

  els.docEditor.hidden = !state.docEditing;
  els.docBody.hidden = state.docEditing;
  if (state.docEditing) return;

  if (state.docsLoading) {
    els.docBody.innerHTML = '<div class="docs-empty">正在加载文档…</div>';
    return;
  }
  if (state.docsError) {
    els.docBody.innerHTML =
      '<div class="docs-empty"><div class="docs-error">' +
      escapeHtml(state.docsError) +
      '</div><button class="btn btn-quiet btn-small" type="button" data-doc-action="reload">重试</button></div>';
    return;
  }
  if (!docs.length) {
    els.docBody.innerHTML =
      '<div class="docs-empty"><div>这个分组还没有文档</div>' +
      '<div>可以新建一篇 README.md，记录备忘、说明或常用信息。</div>' +
      '<button class="btn btn-primary btn-small" type="button" data-doc-action="new">新建 README.md</button></div>';
    return;
  }
  if (!state.currentDoc) {
    els.docBody.innerHTML = '<div class="docs-empty">从上方选择一篇文档</div>';
    return;
  }
  if (!(state.currentDoc.content || "").trim()) {
    els.docBody.innerHTML =
      '<div class="docs-empty"><div>这篇文档还是空的</div>' +
      '<button class="btn btn-quiet btn-small" type="button" data-doc-action="edit">开始编辑</button></div>';
    return;
  }
  els.docBody.innerHTML =
    '<div class="markdown-body">' + state.currentDoc.html + "</div>";
}

function startDocEditor(doc) {
  state.docEditing = true;
  state.docEditingId = doc ? doc.id : null;
  const hasReadme = state.docs.some(
    (item) => item.name.toLowerCase() === "readme.md"
  );
  els.docNameInput.value = doc
    ? doc.name
    : hasReadme
      ? "notes.md"
      : "README.md";
  els.docContentInput.value = doc ? doc.content || "" : "";
  els.docEditorStatus.textContent = doc ? "编辑文档" : "新建文档";
  renderDocsPane();
  els.docNameInput.focus();
  els.docNameInput.select();
}

function closeDocEditor() {
  state.docEditing = false;
  state.docEditingId = null;
  els.docEditorStatus.textContent = "";
  renderDocsPane();
}

async function saveDoc() {
  const name = els.docNameInput.value.trim();
  const content = els.docContentInput.value;
  const groupId = state.docsGroupId;
  if (!groupId) return;
  if (!name) {
    els.docEditorStatus.textContent = "文档名不能为空";
    return;
  }
  els.docSaveBtn.disabled = true;
  els.docEditorStatus.textContent = "保存中…";
  try {
    const doc =
      state.docEditingId === null
        ? await api(`/groups/${groupId}/documents`, {
            method: "POST",
            body: { name, content },
          })
        : await api(`/documents/${state.docEditingId}`, {
            method: "PATCH",
            body: { name, content },
          });
    if (state.docsGroupId !== groupId) return;
    state.currentDoc = doc;
    state.docEditing = false;
    state.docEditingId = null;
    await refreshDocsList(groupId);
    renderDocsPane();
    toast("文档已保存");
  } catch (error) {
    els.docEditorStatus.textContent = error.message;
    toast(error.message, "error");
  } finally {
    els.docSaveBtn.disabled = false;
  }
}

async function refreshDocsList(groupId) {
  const data = await api(`/groups/${groupId}/documents`);
  if (state.docsGroupId !== groupId) return;
  state.docs = data.documents || [];
  state.docsLoaded = true;
}

async function deleteCurrentDoc() {
  const doc = state.currentDoc;
  if (!doc) return;
  const confirmed = await confirmAction({
    title: "删除文档",
    message: `确定删除「${doc.name}」吗？此操作不可撤销。`,
    okText: "删除文档",
  });
  if (!confirmed) return;
  try {
    await api(`/documents/${doc.id}`, { method: "DELETE" });
    state.docs = state.docs.filter((item) => item.id !== doc.id);
    state.currentDoc = null;
    state.docEditing = false;
    state.docEditingId = null;
    renderDocsPane();
    if (state.docs.length) await loadDocument(state.docs[0].id);
    toast("文档已删除");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderBreadcrumbs(mode, item, search) {
  els.breadcrumbs.replaceChildren();
  const all = button("crumb", mode === "all" ? "邻页首页" : "返回全部链接");
  all.dataset.nav = "all";
  all.textContent = mode === "all" ? "首页" : "全部链接";
  if (mode === "all") all.classList.add("is-current");
  els.breadcrumbs.append(all);

  if (mode === "group" && item) {
    item.path.forEach((group, index) => {
      els.breadcrumbs.append(el("span", "crumb-sep", "/"));
      const crumb = button("crumb", `前往分组「${group.name}」`);
      crumb.dataset.nav = String(group.id);
      crumb.textContent = group.name;
      if (index === item.path.length - 1) crumb.classList.add("is-current");
      els.breadcrumbs.append(crumb);
    });
  } else if (mode === "search") {
    els.breadcrumbs.append(el("span", "crumb-sep", "/"));
    const current = el("span", "crumb is-current", "搜索");
    els.breadcrumbs.append(current);
    if (search) {
      els.breadcrumbs.lastElementChild.title = search;
    }
  }
}

function showEmptyState(mode, item, search) {
  els.emptyState.hidden = false;
  let title = "";
  let text = "";
  const actions = [];

  if (mode === "search") {
    title = "没有找到匹配的网址";
    text = "换一个更短的关键词，或检查标题、网址和描述里的写法。";
    actions.push({
      label: "清除搜索",
      primary: true,
      action: () => clearSearch(),
    });
  } else if (mode === "group") {
    title = "这个分组还是空的";
    text = item && item.group.children.length
      ? "可以在当前分组添加链接，也可以用左侧的子分组继续整理。"
      : "添加第一个网址，让局域网里的同事也能一键找到它。";
    actions.push({
      label: "添加链接",
      primary: true,
      action: () => openLinkDialog(),
    });
    actions.push({
      label: "新建子分组",
      action: () => openGroupDialog({ parentId: state.selectedId }),
    });
  } else if (!state.tree.groups.length) {
    title = "从一个分组开始";
    text = "先按用途建立分组，比如「内部系统」「常用工具」，再把网址放进去。";
    actions.push({
      label: "新建第一个分组",
      primary: true,
      action: () => openGroupDialog(),
    });
  } else {
    title = "还没有收藏任何网址";
    text = "在任意分组里添加第一个入口，局域网内打开这个页面的人都能看到。";
    actions.push({
      label: "新建链接",
      primary: true,
      action: () => openLinkDialog(),
    });
  }

  els.emptyTitle.textContent = title;
  els.emptyText.textContent = text;
  els.emptyActions.replaceChildren();
  for (const itemAction of actions) {
    const btn = el("button", `btn ${itemAction.primary ? "btn-primary" : "btn-quiet"}`);
    btn.type = "button";
    btn.textContent = itemAction.label;
    btn.addEventListener("click", itemAction.action);
    els.emptyActions.append(btn);
  }
  if (search) {
    els.emptyText.textContent = `没有网址包含「${search}」。换一个更短的关键词试试。`;
  }
}

/* ---------- 链接卡片 ---------- */

function createLinkCard(entry, index, total, options) {
  const { link, group, path } = entry;
  const card = el("article", "link-card");
  card.dataset.linkId = String(link.id);
  card.dataset.linkUrl = link.url;
  card.classList.add(`tone-${toneFor(group)}`);
  if (options.canReorder) card.classList.add("has-reorder");

  const anchor = document.createElement("a");
  anchor.className = "link-body";
  anchor.href = link.url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.title = `在新标签页打开 ${link.url}`;
  anchor.draggable = false;

  const favicon = el("span", "favicon");
  favicon.setAttribute("aria-hidden", "true");
  favicon.append(el("span", "favicon-fallback", firstCharacter(link.title)));
  const iconUrl = link.icon || faviconUrl(link.url);
  if (iconUrl) {
    const image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    image.draggable = false;
    image.addEventListener("load", () => favicon.classList.add("is-loaded"));
    image.addEventListener("error", () => image.remove());
    image.src = iconUrl;
    favicon.append(image);
  }
  anchor.append(favicon);

  const copy = el("div", "link-copy");
  const titleRow = el("div", "link-title-row");
  const title = el("h3", "link-title");
  appendHighlighted(title, link.title, options.query);
  titleRow.append(title, icon("external", "icon external-mark"));
  copy.append(titleRow);

  if (link.description) {
    const desc = el("div", "link-desc");
    appendHighlighted(desc, link.description, options.query);
    copy.append(desc);
  }

  anchor.append(copy);
  card.append(anchor);

  const meta = el("div", "card-meta");
  const domain = el("span", "domain");
  domain.title = link.url;
  domain.append(icon("globe", "icon"));
  domain.append(el("span", "domain-text", options.query ? shortUrl(link.url) : domainOf(link.url)));
  meta.append(domain);

  if (options.showGroup) {
    const pill = el("span", "group-pill");
    pill.title = `所属分组：${groupPathText(path)}`;
    pill.append(icon("folder", "icon folder-icon"));
    pill.append(el("span", "group-pill-text", group.name));
    meta.append(pill);
  }
  meta.append(createCheckBadge(link.id));
  card.append(meta);

  const tools = el("div", "card-tools");
  if (options.canReorder) {
    const up = button("card-tool", "上移", "up");
    up.dataset.action = "up";
    up.disabled = index === 0;
    const down = button("card-tool", "下移", "down");
    down.dataset.action = "down";
    down.disabled = index === total - 1;
    tools.append(up, down);
  }
  const edit = button("card-tool", `编辑「${link.title}」`, "edit");
  edit.dataset.action = "edit";
  const remove = button("card-tool danger", `删除「${link.title}」`, "trash");
  remove.dataset.action = "delete";
  tools.append(edit, remove);
  card.append(tools);

  // 整卡覆盖一层原生链接，避免 JS 打开新标签页被 Safari 间歇性拦截
  const overlay = document.createElement("a");
  overlay.className = "card-overlay";
  overlay.href = link.url;
  overlay.target = "_blank";
  overlay.rel = "noopener noreferrer";
  overlay.tabIndex = -1;
  overlay.setAttribute("aria-hidden", "true");
  overlay.title = options.canReorder
    ? `在新标签页打开 ${link.url}（长按卡片可拖动排序）`
    : `在新标签页打开 ${link.url}`;
  overlay.draggable = false;
  card.append(overlay);

  return card;
}

function firstCharacter(title) {
  const chars = Array.from((title || "").trim());
  return chars.length ? chars[0].toLocaleUpperCase() : "·";
}

function domainOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function shortUrl(url) {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    return `${parsed.host}${path}${parsed.search}`;
  } catch {
    return url;
  }
}

function openExternalLink(url) {
  if (!url) return;
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

function faviconUrl(url) {
  try {
    return `${new URL(url).origin}/favicon.ico`;
  } catch {
    return "";
  }
}

function appendHighlighted(parent, text, query) {
  const value = String(text || "");
  const needle = (query || "").trim();
  if (!needle) {
    parent.textContent = value;
    return;
  }
  const lowerValue = value.toLocaleLowerCase();
  const lowerNeedle = needle.toLocaleLowerCase();
  if (!lowerNeedle) {
    parent.textContent = value;
    return;
  }
  let cursor = 0;
  let match = lowerValue.indexOf(lowerNeedle, cursor);
  if (match === -1) {
    parent.textContent = value;
    return;
  }
  while (match !== -1) {
    if (match > cursor) parent.append(document.createTextNode(value.slice(cursor, match)));
    const mark = document.createElement("mark");
    mark.textContent = value.slice(match, match + needle.length);
    parent.append(mark);
    cursor = match + needle.length;
    match = lowerValue.indexOf(lowerNeedle, cursor);
  }
  if (cursor < value.length) parent.append(document.createTextNode(value.slice(cursor)));
}

/* ---------- 连通性检测 ---------- */

function initAutoCheckPreference() {
  let stored = null;
  try {
    stored = localStorage.getItem(AUTO_CHECK_KEY);
  } catch {
    stored = null;
  }
  state.autoCheckEnabled = stored === null ? true : stored !== "0";
  els.autoCheckToggle.checked = state.autoCheckEnabled;
}

function persistAutoCheckPreference() {
  try {
    localStorage.setItem(AUTO_CHECK_KEY, state.autoCheckEnabled ? "1" : "0");
  } catch {
    // 浏览器禁用 localStorage 时只影响下次打开页面。
  }
}

function initDocsPreference() {
  let stored = null;
  try {
    stored = localStorage.getItem(DOCS_VISIBLE_KEY);
  } catch {
    stored = null;
  }
  // 默认不展示文档
  state.docsVisible = stored === "1";
  els.docToggle.checked = state.docsVisible;
}

function persistDocsPreference() {
  try {
    localStorage.setItem(DOCS_VISIBLE_KEY, state.docsVisible ? "1" : "0");
  } catch {
    // 忽略存储异常。
  }
}

function getCheckInfo(linkId) {
  return state.linkChecks.get(Number(linkId)) || { status: "unchecked" };
}

function createCheckBadge(linkId) {
  const badge = document.createElement("button");
  badge.type = "button";
  badge.className = "check-badge";
  badge.dataset.action = "check";
  badge.dataset.checkLinkId = String(linkId);
  applyCheckBadge(badge, getCheckInfo(linkId));
  return badge;
}

function setLinkCheck(linkId, info) {
  const numericId = Number(linkId);
  state.linkChecks.set(numericId, info);
  const badge = els.linkGrid.querySelector(
    `.check-badge[data-check-link-id="${numericId}"]`
  );
  if (badge) applyCheckBadge(badge, info);
}

function hasActiveCheckFor(linkId) {
  const numericId = Number(linkId);
  return Boolean(
    state.singleChecks.has(numericId) ||
    (state.batchRun && state.batchRun.pending.has(numericId)) ||
    state.linkChecks.get(numericId)?.status === "checking"
  );
}

function clearLinkCheck(linkId) {
  const numericId = Number(linkId);
  if (hasActiveCheckFor(numericId)) cancelAllChecks();
  state.linkChecks.delete(numericId);
  const badge = els.linkGrid.querySelector(
    `.check-badge[data-check-link-id="${numericId}"]`
  );
  if (badge) applyCheckBadge(badge, { status: "unchecked" });
}

function forgetGroupChecks(group) {
  for (const link of group.links || []) state.linkChecks.delete(link.id);
  for (const child of group.children || []) forgetGroupChecks(child);
}

function formatCheckTime(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString("zh-CN", { hour12: false });
}

function shortCheckReason(reason) {
  const text = String(reason || "");
  if (text.includes("DNS")) return "DNS 失败";
  if (text.includes("拒绝")) return "连接拒绝";
  if (text.includes("超时")) return "超时";
  if (text.includes("重定向")) return "重定向";
  if (text.includes("证书")) return "证书错误";
  if (text.includes("不可达")) return "不可达";
  if (text.includes("http/https")) return "网址无效";
  return "检测失败";
}

function applyCheckBadge(badge, info) {
  const status = info && info.status ? info.status : "unchecked";
  badge.className = "check-badge";
  badge.replaceChildren();
  badge.disabled = status === "checking";

  let toneClass = "is-unchecked";
  let label = "未检测";
  let title = "点击检测连通性";
  let showSpinner = false;

  if (status === "checking") {
    toneClass = "is-checking";
    label = "检测中";
    title = "正在检测连通性…";
    showSpinner = true;
  } else if (status === "ok" || status === "slow") {
    toneClass = status === "ok" ? "is-ok" : "is-slow";
    label = `${status === "ok" ? "正常" : "较慢"} · ${Math.max(0, Number(info.latency_ms) || 0)} ms`;
    const details = [];
    if (info.http_status) details.push(`HTTP ${info.http_status}`);
    if (info.reason) details.push(info.reason);
    if (info.cached) details.push("缓存结果");
    const time = formatCheckTime(info.checked_at);
    if (time) details.push(`检测于 ${time}`);
    title = `${status === "ok" ? "连通正常" : "响应较慢"}${details.length ? ` · ${details.join(" · ")}` : ""} · 点击重新检测`;
  } else if (status === "error") {
    const httpStatus = Number(info.http_status) || null;
    if (httpStatus && httpStatus >= 400 && httpStatus < 500) {
      toneClass = "is-warn";
    } else {
      toneClass = "is-error";
    }
    label = httpStatus ? `HTTP ${httpStatus}` : shortCheckReason(info.reason);
    const details = [info.reason || "检测失败"];
    if (httpStatus) details.push(`HTTP ${httpStatus}`);
    if (info.cached) details.push("缓存结果");
    const time = formatCheckTime(info.checked_at);
    if (time) details.push(`检测于 ${time}`);
    title = `${details.join(" · ")} · 点击重新检测`;
  }

  badge.classList.add(toneClass);
  badge.title = title;
  badge.setAttribute("aria-label", title);
  badge.append(el("span", showSpinner ? "check-spinner" : "check-dot"));
  badge.append(el("span", "check-label", label));
  if (!showSpinner) badge.append(icon("activity", "icon check-action-icon"));
}

function normalizeCheckResult(result) {
  const allowed = new Set(["ok", "slow", "error"]);
  const status = allowed.has(result && result.status) ? result.status : "error";
  return {
    status,
    ok: Boolean(result && result.ok),
    reachable: Boolean(result && result.reachable),
    latency_ms: result && Number.isFinite(Number(result.latency_ms)) ? Number(result.latency_ms) : null,
    http_status: result && result.http_status !== null && result.http_status !== undefined
      ? Number(result.http_status)
      : null,
    reason: result && result.reason ? String(result.reason) : null,
    checked_at: result && result.checked_at ? String(result.checked_at) : new Date().toISOString(),
    cached: Boolean(result && result.cached),
    tls_insecure: Boolean(result && result.tls_insecure),
  };
}

function localCheckError(reason) {
  return {
    status: "error",
    ok: false,
    reachable: false,
    latency_ms: 0,
    http_status: null,
    reason,
    checked_at: new Date().toISOString(),
    cached: false,
    tls_insecure: false,
  };
}

function isCheckFresh(linkId) {
  const info = state.linkChecks.get(Number(linkId));
  if (!info || !["ok", "slow", "error"].includes(info.status) || !info.checked_at) {
    return false;
  }
  const checkedAt = Date.parse(info.checked_at);
  return Number.isFinite(checkedAt) && Date.now() - checkedAt < CHECK_TTL_MS;
}

function clearProgressTimer() {
  if (state.progressTimer) {
    window.clearTimeout(state.progressTimer);
    state.progressTimer = null;
  }
}

function setCheckProgress(text, clearAfter = 0) {
  clearProgressTimer();
  els.checkProgress.textContent = text || "";
  if (clearAfter > 0) {
    state.progressTimer = window.setTimeout(() => {
      state.progressTimer = null;
      if (!state.batchRun) els.checkProgress.textContent = "";
    }, clearAfter);
  }
}

function updateCheckToolbar() {
  const running = Boolean(state.batchRun);
  els.checkAllBtn.classList.toggle("is-running", running);
  els.checkAllLabel.textContent = running ? "停止检测" : "检测全部";
  els.checkAllBtn.title = running ? "停止当前检测" : "检测当前列表中的全部链接";
  const canCheck = !state.loading && !state.loadError && state.currentEntries.length > 0;
  els.checkTools.hidden = !canCheck;
}

function clearAutoCheckTimer() {
  if (state.autoCheckTimer) {
    window.clearTimeout(state.autoCheckTimer);
    state.autoCheckTimer = null;
  }
}

function scheduleAutoCheck() {
  clearAutoCheckTimer();
  if (
    !state.autoCheckEnabled ||
    state.currentViewMode === "search" ||
    state.batchRun ||
    state.singleChecks.size > 0
  ) {
    return;
  }
  const ids = [];
  const seen = new Set();
  for (const entry of state.currentEntries) {
    const linkId = Number(entry.link.id);
    if (seen.has(linkId) || isCheckFresh(linkId)) continue;
    if (state.linkChecks.get(linkId)?.status === "checking") continue;
    seen.add(linkId);
    ids.push(linkId);
    if (ids.length >= AUTO_CHECK_LIMIT) break;
  }
  if (!ids.length) return;

  const viewKey = state.currentCheckView;
  state.autoCheckTimer = window.setTimeout(() => {
    state.autoCheckTimer = null;
    if (
      state.currentCheckView !== viewKey ||
      !state.autoCheckEnabled ||
      state.currentViewMode === "search" ||
      state.batchRun ||
      state.singleChecks.size > 0
    ) {
      return;
    }
    startBatchCheck(ids, { source: "auto" });
  }, 380);
}

function restoreCheckBefore(linkId, previous) {
  if (previous && previous.status !== "checking") {
    setLinkCheck(linkId, previous);
  } else {
    setLinkCheck(linkId, { status: "unchecked" });
  }
}

function cancelAutoBatch() {
  const run = state.batchRun;
  if (!run || run.source !== "auto") return;
  abortBatchRun({ announce: false });
}

function abortBatchRun({ announce = false } = {}) {
  const run = state.batchRun;
  if (!run) return;
  state.batchRun = null;
  run.controller.abort();
  for (const linkId of run.pending) {
    restoreCheckBefore(linkId, run.previous.get(linkId));
  }
  run.pending.clear();
  clearProgressTimer();
  if (announce) setCheckProgress("已停止", 2200);
  else setCheckProgress("");
  updateCheckToolbar();
}

function cancelSingleChecks() {
  for (const [linkId, active] of state.singleChecks) {
    active.controller.abort();
    restoreCheckBefore(linkId, active.previous);
  }
  state.singleChecks.clear();
}

function cancelAllChecks() {
  clearAutoCheckTimer();
  abortBatchRun({ announce: false });
  cancelSingleChecks();
  clearProgressTimer();
  els.checkProgress.textContent = "";
  updateCheckToolbar();
}

function checkBatchLabel(source) {
  return source === "auto" ? "自动检测" : "检测中";
}

async function startBatchCheck(ids, { source = "manual" } = {}) {
  const uniqueIds = [...new Set(ids.map(Number).filter((value) => Number.isInteger(value)))];
  if (!uniqueIds.length) return;

  clearAutoCheckTimer();
  cancelSingleChecks();
  if (state.batchRun) abortBatchRun({ announce: false });

  const previous = new Map();
  for (const linkId of uniqueIds) {
    previous.set(linkId, state.linkChecks.get(linkId) || null);
  }
  const run = {
    controller: new AbortController(),
    ids: uniqueIds,
    source,
    total: uniqueIds.length,
    completed: 0,
    pending: new Set(uniqueIds),
    previous,
  };
  state.batchRun = run;
  for (const linkId of uniqueIds) {
    setLinkCheck(linkId, { status: "checking" });
  }
  updateCheckToolbar();
  setCheckProgress(`${checkBatchLabel(source)} 0/${run.total}`);

  try {
    for (let offset = 0; offset < uniqueIds.length; offset += CHECK_BATCH_SIZE) {
      const batchIds = uniqueIds.slice(offset, offset + CHECK_BATCH_SIZE);
      const data = await api("/check-links", {
        method: "POST",
        body: { ids: batchIds },
        signal: run.controller.signal,
      });
      if (state.batchRun !== run) return;
      const resultMap = new Map(
        (Array.isArray(data.results) ? data.results : []).map((result) => [
          Number(result.id),
          result,
        ])
      );
      for (const linkId of batchIds) {
        const result = resultMap.get(linkId);
        if (result) {
          setLinkCheck(linkId, normalizeCheckResult(result));
        } else {
          setLinkCheck(linkId, localCheckError("未返回检测结果"));
        }
        run.pending.delete(linkId);
      }
      run.completed += batchIds.length;
      setCheckProgress(`${checkBatchLabel(source)} ${run.completed}/${run.total}`);
      if (offset + CHECK_BATCH_SIZE < uniqueIds.length) {
        await sleep(40);
        if (state.batchRun !== run) return;
      }
    }
    if (state.batchRun !== run) return;
    state.batchRun = null;
    setCheckProgress(`检测完成 ${run.total}/${run.total}`, 3000);
    updateCheckToolbar();
  } catch (error) {
    if (state.batchRun !== run) return;
    state.batchRun = null;
    if (error && error.name === "AbortError") {
      for (const linkId of run.pending) {
        restoreCheckBefore(linkId, run.previous.get(linkId));
      }
      run.pending.clear();
      setCheckProgress("已停止", 2200);
    } else {
      for (const linkId of run.pending) {
        restoreCheckBefore(linkId, run.previous.get(linkId));
      }
      run.pending.clear();
      setCheckProgress("检测失败", 5000);
      toast(`连通性检测失败：${error.message}`, "error");
    }
    updateCheckToolbar();
  }
}

function startManualCheck() {
  const ids = [...new Set(state.currentEntries.map((entry) => Number(entry.link.id)))];
  if (!ids.length) return;
  startBatchCheck(ids, { source: "manual" });
}

async function checkSingleLink(linkId) {
  const numericId = Number(linkId);
  const current = state.linkChecks.get(numericId);
  if (current && current.status === "checking") return;
  if (!locateLink(numericId)) return;
  clearAutoCheckTimer();

  const controller = new AbortController();
  state.singleChecks.set(numericId, {
    controller,
    previous: current || null,
  });
  setLinkCheck(numericId, { status: "checking" });

  try {
    const data = await api("/check-links", {
      method: "POST",
      body: { ids: [numericId] },
      signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    const result = Array.isArray(data.results)
      ? data.results.find((item) => Number(item.id) === numericId)
      : null;
    if (result) setLinkCheck(numericId, normalizeCheckResult(result));
    else setLinkCheck(numericId, localCheckError("未返回检测结果"));
  } catch (error) {
    if (controller.signal.aborted) return;
    setLinkCheck(numericId, localCheckError(`检测服务不可用：${error.message}`));
  } finally {
    const active = state.singleChecks.get(numericId);
    if (active && active.controller === controller) {
      state.singleChecks.delete(numericId);
    }
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

/* ---------- 编辑与删除 ---------- */

function openGroupDialog({ group = null, parentId = null } = {}) {
  els.groupForm.reset();
  els.groupDialogTitle.textContent = group ? "编辑分组" : "新建分组";
  els.groupSubmitBtn.textContent = group ? "保存修改" : "创建分组";
  els.groupForm.dataset.groupId = group ? String(group.id) : "";

  els.groupParentSelect.replaceChildren();
  const topOption = document.createElement("option");
  topOption.value = "";
  topOption.textContent = "（顶级分组）";
  els.groupParentSelect.append(topOption);

  const excluded = group ? descendantIds(group) : new Set();
  if (group) excluded.add(group.id);
  for (const item of flattenGroups()) {
    if (excluded.has(item.group.id)) continue;
    const option = document.createElement("option");
    option.value = String(item.group.id);
    option.textContent = `${"　".repeat(item.depth)}${item.depth ? "↳ " : ""}${item.group.name}`;
    els.groupParentSelect.append(option);
  }

  let selectedParent = null;
  if (group) selectedParent = group.parent_id;
  else if (parentId !== null) selectedParent = parentId;
  if (selectedParent !== null && selectedParent !== undefined) {
    els.groupParentSelect.value = String(selectedParent);
  }

  const nameInput = els.groupForm.elements.namedItem("name");
  nameInput.value = group ? group.name : "";
  const sortInput = els.groupForm.elements.namedItem("sort_order");
  sortInput.value = group ? String(group.sort_order) : "";

  els.groupDialog.showModal();
  window.setTimeout(() => nameInput.focus(), 30);
}

function openLinkDialog(linkId = null) {
  const groups = flattenGroups();
  if (!groups.length) {
    toast("请先建立一个分组，再添加链接", "error");
    openGroupDialog();
    return;
  }

  const located = linkId !== null ? locateLink(linkId) : null;
  if (linkId !== null && !located) {
    toast("这条链接已不存在", "error");
    return;
  }

  els.linkForm.reset();
  hideLinkFormError();
  els.linkDialogTitle.textContent = located ? "编辑链接" : "新建链接";
  els.linkSubmitBtn.textContent = located ? "保存修改" : "保存链接";
  els.linkForm.dataset.linkId = located ? String(located.link.id) : "";

  els.linkGroupSelect.replaceChildren();
  for (const item of groups) {
    const option = document.createElement("option");
    option.value = String(item.group.id);
    option.textContent = `${"　".repeat(item.depth)}${item.depth ? "↳ " : ""}${item.group.name}`;
    els.linkGroupSelect.append(option);
  }

  const defaultGroupId = located
    ? located.link.group_id
    : state.selectedId !== null
      ? state.selectedId
      : groups[0].group.id;
  els.linkGroupSelect.value = String(defaultGroupId);

  const form = els.linkForm.elements;
  form.namedItem("title").value = located ? located.link.title : "";
  form.namedItem("url").value = located ? located.link.url : "";
  form.namedItem("description").value = located ? located.link.description : "";
  form.namedItem("icon").value = located ? located.link.icon : "";
  form.namedItem("sort_order").value = located ? String(located.link.sort_order) : "";

  els.linkDialog.showModal();
  window.setTimeout(() => form.namedItem("title").focus(), 30);
}

async function saveGroup(event) {
  event.preventDefault();
  const form = els.groupForm;
  const name = String(form.elements.namedItem("name").value || "").trim();
  if (!name) {
    toast("请填写分组名称", "error");
    form.elements.namedItem("name").focus();
    return;
  }
  const parentRaw = String(form.elements.namedItem("parent_id").value || "");
  const sortRaw = String(form.elements.namedItem("sort_order").value || "");
  const payload = {
    name,
    parent_id: parentRaw ? Number(parentRaw) : null,
  };
  if (sortRaw !== "") {
    const value = Number(sortRaw);
    if (!Number.isInteger(value)) {
      toast("排序值必须是整数", "error");
      return;
    }
    payload.sort_order = value;
  }

  const editingId = form.dataset.groupId;
  setButtonBusy(els.groupSubmitBtn, true, "保存中…");
  try {
    let result;
    if (editingId) {
      result = await api(`/groups/${editingId}`, { method: "PATCH", body: payload });
    } else {
      result = await api("/groups", { method: "POST", body: payload });
      state.selectedId = result.id;
      if (payload.parent_id !== null) state.expanded.add(payload.parent_id);
      expandAncestors(payload.parent_id);
    }
    if (editingId && payload.parent_id !== null) expandAncestors(payload.parent_id);
    els.groupDialog.close();
    toast(editingId ? "分组已更新" : "分组已创建");
    await loadTree();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonBusy(els.groupSubmitBtn, false);
  }
}

function showLinkFormError(message) {
  els.linkFormError.textContent = message;
  els.linkFormError.hidden = false;
}

function hideLinkFormError() {
  els.linkFormError.hidden = true;
  els.linkFormError.textContent = "";
}

async function saveLink(event) {
  event.preventDefault();
  const form = els.linkForm;
  const title = String(form.elements.namedItem("title").value || "").trim();
  const url = String(form.elements.namedItem("url").value || "").trim();
  if (!title) {
    showLinkFormError("请填写标题");
    form.elements.namedItem("title").focus();
    return;
  }
  if (!url) {
    showLinkFormError("请填写网址");
    form.elements.namedItem("url").focus();
    return;
  }
  const sortRaw = String(form.elements.namedItem("sort_order").value || "");
  const payload = {
    group_id: Number(form.elements.namedItem("group_id").value),
    title,
    url,
    description: String(form.elements.namedItem("description").value || "").trim(),
    icon: String(form.elements.namedItem("icon").value || "").trim(),
  };
  if (sortRaw !== "") {
    const value = Number(sortRaw);
    if (!Number.isInteger(value)) {
      showLinkFormError("排序值必须是整数");
      return;
    }
    payload.sort_order = value;
  }

  const editingId = form.dataset.linkId;
  setButtonBusy(els.linkSubmitBtn, true, "保存中…");
  try {
    if (editingId) {
      await api(`/links/${editingId}`, { method: "PATCH", body: payload });
    } else {
      await api("/links", { method: "POST", body: payload });
    }
    if (editingId) clearLinkCheck(Number(editingId));
    if (!state.search && state.selectedId !== null) {
      state.selectedId = payload.group_id;
      if (payload.group_id !== null) {
        state.expanded.add(payload.group_id);
        expandAncestors(payload.group_id);
      }
    }
    hideLinkFormError();
    els.linkDialog.close();
    toast(editingId ? "链接已更新" : "链接已添加");
    await loadTree();
  } catch (error) {
    showLinkFormError(error.message);
  } finally {
    setButtonBusy(els.linkSubmitBtn, false);
  }
}

async function moveLink(linkId, direction) {
  const located = locateLink(linkId);
  if (!located) return;
  const siblings = located.group.links;
  const index = siblings.findIndex((link) => link.id === linkId);
  if (index === -1) return;
  const target = direction === "up" ? siblings[index - 1] : siblings[index + 1];
  if (!target) return;
  const payload = {
    group_id: located.group.id,
    ...(direction === "up" ? { before_id: target.id } : { after_id: target.id }),
  };
  try {
    await api(`/links/${linkId}/move`, { method: "POST", body: payload });
    await loadTree();
  } catch (error) {
    toast(error.message, "error");
  }
}

/* ---------- 长按拖动排序 ---------- */

function canDragCards() {
  return (
    state.currentViewMode === "group" &&
    state.selectedId !== null &&
    !state.search.trim() &&
    !state.loading
  );
}

function onCardPointerDown(event) {
  if (event.button !== 0 || event.pointerType !== "mouse") return;
  if (!canDragCards() || state.dragState) return;
  if (!(event.target instanceof Element)) return;
  if (event.target.closest("button")) return;
  const card = event.target.closest(".link-card");
  if (!card) return;

  const rect = card.getBoundingClientRect();
  const cards = [...els.linkGrid.querySelectorAll(".link-card")];
  state.dragState = {
    card,
    linkId: Number(card.dataset.linkId),
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
    width: rect.width,
    height: rect.height,
    startIndex: cards.indexOf(card),
    dragging: false,
    timer: window.setTimeout(startCardDrag, LONG_PRESS_MS),
    placeholder: null,
    ghost: null,
  };
}

function startCardDrag() {
  const drag = state.dragState;
  if (!drag || drag.dragging) return;
  drag.dragging = true;
  drag.timer = null;
  window.getSelection()?.removeAllRanges();

  const { card, width, height, startX, startY, offsetX, offsetY } = drag;
  const placeholder = document.createElement("div");
  placeholder.className = "link-drop-placeholder";
  placeholder.style.height = `${height}px`;
  card.parentNode.insertBefore(placeholder, card);

  const ghost = card.cloneNode(true);
  ghost.classList.remove("is-drag-origin");
  ghost.classList.add("link-drag-ghost");
  ghost.setAttribute("aria-hidden", "true");
  ghost.style.width = `${width}px`;
  ghost.style.height = `${height}px`;
  ghost.style.left = `${startX - offsetX}px`;
  ghost.style.top = `${startY - offsetY}px`;
  ghost.querySelectorAll(".card-overlay").forEach((node) => node.remove());
  document.body.append(ghost);

  try {
    document.body.setPointerCapture(drag.pointerId);
    drag.captured = true;
  } catch {
    drag.captured = false;
  }

  card.classList.add("is-drag-origin");
  document.body.classList.add("is-card-dragging");
  drag.placeholder = placeholder;
  drag.ghost = ghost;
}

function onCardPointerMove(event) {
  const drag = state.dragState;
  if (!drag) return;
  if (!drag.dragging) {
    if (
      Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >
      DRAG_TOLERANCE_PX
    ) {
      window.clearTimeout(drag.timer);
      state.dragState = null;
    }
    return;
  }

  event.preventDefault();
  drag.ghost.style.left = `${event.clientX - drag.offsetX}px`;
  drag.ghost.style.top = `${event.clientY - drag.offsetY}px`;

  const edge = 70;
  if (event.clientY < edge) window.scrollBy(0, -12);
  else if (event.clientY > window.innerHeight - edge) window.scrollBy(0, 12);

  const under = document.elementFromPoint(event.clientX, event.clientY);
  const targetCard =
    under instanceof Element ? under.closest(".link-card") : null;
  if (!targetCard || targetCard === drag.card) return;

  const rect = targetCard.getBoundingClientRect();
  const insertBefore = event.clientY < rect.top + rect.height / 2;
  const parent = targetCard.parentNode;
  if (!parent) return;
  if (insertBefore) {
    if (drag.placeholder.nextSibling !== targetCard) {
      parent.insertBefore(drag.placeholder, targetCard);
    }
  } else {
    const reference = targetCard.nextSibling;
    if (drag.placeholder !== reference && drag.placeholder.previousSibling !== targetCard) {
      parent.insertBefore(drag.placeholder, reference);
    }
  }
}

function onCardPointerUp(event) {
  const drag = state.dragState;
  if (!drag) return;
  if (event.pointerId !== drag.pointerId) return;
  if (!drag.dragging) {
    window.clearTimeout(drag.timer);
    state.dragState = null;
    return;
  }
  finishCardDrag();
}

function onCardPointerCancel() {
  cancelCardDrag();
}

function finishCardDrag() {
  const drag = state.dragState;
  if (!drag) return;
  if (!drag.dragging) {
    window.clearTimeout(drag.timer);
    state.dragState = null;
    return;
  }

  const { card, placeholder, ghost, linkId, startIndex } = drag;
  if (drag.captured) {
    try {
      document.body.releasePointerCapture(drag.pointerId);
    } catch {
      // 指针已释放时忽略
    }
  }
  if (placeholder && placeholder.parentNode) placeholder.replaceWith(card);
  card.classList.remove("is-drag-origin");
  ghost?.remove();
  document.body.classList.remove("is-card-dragging");
  state.dragState = null;
  state.suppressClick = true;
  window.setTimeout(() => {
    state.suppressClick = false;
  }, 250);

  const ids = [...els.linkGrid.querySelectorAll(".link-card")].map((node) =>
    Number(node.dataset.linkId)
  );
  const newIndex = ids.indexOf(linkId);
  if (newIndex < 0 || newIndex === startIndex || ids.length < 2) return;
  const groupId = state.selectedId;
  if (groupId === null) return;

  const payload = { group_id: groupId };
  if (newIndex > 0) payload.after_id = ids[newIndex - 1];
  else if (newIndex < ids.length - 1) payload.before_id = ids[newIndex + 1];
  else return;

  saveCardOrder(linkId, payload);
}

function cancelCardDrag() {
  const drag = state.dragState;
  if (!drag) return;
  window.clearTimeout(drag.timer);
  if (drag.dragging) {
    if (drag.captured) {
      try {
        document.body.releasePointerCapture(drag.pointerId);
      } catch {
        // 指针已释放时忽略
      }
    }
    if (drag.placeholder && drag.placeholder.parentNode) {
      drag.placeholder.replaceWith(drag.card);
    }
    drag.card.classList.remove("is-drag-origin");
    drag.ghost?.remove();
    document.body.classList.remove("is-card-dragging");
    state.suppressClick = true;
    window.setTimeout(() => {
      state.suppressClick = false;
    }, 250);
  }
  state.dragState = null;
}

async function saveCardOrder(linkId, payload) {
  try {
    await api(`/links/${linkId}/move`, { method: "POST", body: payload });
    await loadTree();
  } catch (error) {
    toast(`排序保存失败：${error.message}`, "error");
    await loadTree();
  }
}

async function deleteCurrentGroup() {
  if (state.selectedId === null) return;
  const item = findGroupItem(state.selectedId);
  if (!item) return;
  const childCount = descendantIds(item.group).size;
  const linkCount = item.group.total_link_count || 0;
  const docCount = item.group.total_document_count || 0;
  const messageParts = [];
  if (childCount) messageParts.push(`${childCount} 个子分组`);
  if (linkCount) messageParts.push(`${linkCount} 条链接`);
  if (docCount) messageParts.push(`${docCount} 篇文档`);
  const message = messageParts.length
    ? `这会同时删除 ${messageParts.join("、")}，且无法撤销。`
    : "这个分组里没有链接、文档或子分组，删除后无法撤销。";
  const confirmed = await confirmAction({
    title: `删除分组「${item.group.name}」？`,
    message,
    okText: "删除分组及内容",
  });
  if (!confirmed) return;
  const parentId = item.group.parent_id;
  try {
    await api(`/groups/${item.group.id}?cascade=true`, { method: "DELETE" });
    cancelAllChecks();
    forgetGroupChecks(item.group);
    state.selectedId = parentId;
    await loadTree();
    toast("分组及其内容已删除");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function deleteLink(linkId) {
  const located = locateLink(linkId);
  if (!located) return;
  const confirmed = await confirmAction({
    title: `删除「${located.link.title}」？`,
    message: "删除后无法恢复。如需保留，请先导出数据。",
    okText: "删除链接",
  });
  if (!confirmed) return;
  try {
    await api(`/links/${linkId}`, { method: "DELETE" });
    clearLinkCheck(Number(linkId));
    await loadTree();
    toast("链接已删除");
  } catch (error) {
    toast(error.message, "error");
  }
}

/* ---------- 确认框 ---------- */

function confirmAction({ title, message, okText = "确认删除", isDanger = true }) {
  return new Promise((resolve) => {
    els.confirmTitle.textContent = title;
    els.confirmMessage.textContent = message;
    els.confirmOk.textContent = okText;
    els.confirmOk.className = `btn ${isDanger ? "btn-danger" : "btn-primary"}`;
    let settled = false;

    const cleanup = () => {
      els.confirmOk.removeEventListener("click", onOk);
      els.confirmCancel.removeEventListener("click", onCancel);
      els.confirmDialog.removeEventListener("cancel", onCancelEvent);
      els.confirmDialog.removeEventListener("close", onClose);
    };
    const finish = (value) => {
      if (settled) return;
      settled = true;
      cleanup();
      els.confirmDialog.close();
      resolve(value);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onCancelEvent = (event) => {
      event.preventDefault();
      finish(false);
    };
    const onClose = () => {
      if (!settled) {
        settled = true;
        cleanup();
        resolve(false);
      }
    };

    els.confirmOk.addEventListener("click", onOk);
    els.confirmCancel.addEventListener("click", onCancel);
    els.confirmDialog.addEventListener("cancel", onCancelEvent);
    els.confirmDialog.addEventListener("close", onClose);
    els.confirmDialog.showModal();
  });
}

/* ---------- 导入 / 导出 ---------- */

async function exportData() {
  try {
    const data = await api("/export");
    const text = JSON.stringify(data, null, 2);
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    anchor.href = url;
    anchor.download = `lan-nav-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1200);
    toast("数据已导出为 JSON 文件");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function importData(file) {
  if (!file) return;
  if (file.size > 15 * 1024 * 1024) {
    toast("导入文件过大（最大 15 MB）", "error");
    return;
  }
  let payload;
  try {
    payload = JSON.parse(await file.text());
  } catch {
    toast("导入文件不是有效的 JSON", "error");
    return;
  }
  if (!payload || !Array.isArray(payload.groups) || !Array.isArray(payload.links)) {
    toast("导入文件缺少 groups 或 links 数据", "error");
    return;
  }
  const docCount = Array.isArray(payload.documents) ? payload.documents.length : 0;
  const confirmed = await confirmAction({
    title: "导入并覆盖现有数据？",
    message:
      `将使用「${file.name}」中的 ${payload.groups.length} 个分组、` +
      `${payload.links.length} 条链接` +
      (docCount ? `、${docCount} 篇文档` : "") +
      "替换当前数据。覆盖前会自动备份数据库。",
    okText: "导入并覆盖",
  });
  if (!confirmed) return;

  try {
    const result = await api("/import", { method: "POST", body: payload });
    cancelAllChecks();
    state.linkChecks.clear();
    state.currentCheckView = null;
    state.search = "";
    els.searchInput.value = "";
    updateSearchClear();
    state.selectedId = null;
    state.expandedInitialized = false;
    state.expanded = new Set();
    try {
      localStorage.removeItem(EXPANDED_KEY);
    } catch {
      // 忽略存储异常。
    }
    await loadTree();
    toast(
      `导入完成：${result.groups} 个分组，${result.links} 条链接` +
        (result.documents ? `，${result.documents} 篇文档` : "")
    );
  } catch (error) {
    toast(error.message, "error");
  }
}

/* ---------- 导航 / 交互 ---------- */

function selectGroup(groupId) {
  state.selectedId = groupId;
  state.search = "";
  els.searchInput.value = "";
  updateSearchClear();
  renderSidebar();
  renderMain();
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openGroupDocs(groupId) {
  state.selectedId = groupId;
  state.search = "";
  els.searchInput.value = "";
  updateSearchClear();
  state.docsVisible = true;
  els.docToggle.checked = true;
  persistDocsPreference();
  renderSidebar();
  renderMain();
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function selectAll() {
  state.selectedId = null;
  state.search = "";
  els.searchInput.value = "";
  updateSearchClear();
  renderSidebar();
  renderMain();
  closeSidebar();
}

function clearSearch() {
  state.search = "";
  els.searchInput.value = "";
  updateSearchClear();
  renderSidebar();
  renderMain();
  els.searchInput.focus();
}

function updateSearchClear() {
  els.clearSearch.hidden = els.searchInput.value.length === 0;
}

function syncSidebarA11y() {
  const mobile = window.innerWidth <= 960;
  const open = document.body.classList.contains("sidebar-open");
  const hidden = mobile && !open;
  els.sidebar.inert = hidden;
  if (hidden) els.sidebar.setAttribute("aria-hidden", "true");
  else els.sidebar.removeAttribute("aria-hidden");
}

function openSidebar() {
  document.body.classList.add("sidebar-open");
  els.scrim.hidden = false;
  els.menuToggle.setAttribute("aria-expanded", "true");
  syncSidebarA11y();
  window.setTimeout(() => {
    if (window.innerWidth <= 960) els.sidebarClose.focus();
  }, 40);
}

function closeSidebar() {
  const wasOpen = document.body.classList.contains("sidebar-open");
  document.body.classList.remove("sidebar-open");
  els.scrim.hidden = true;
  els.menuToggle.setAttribute("aria-expanded", "false");
  syncSidebarA11y();
  if (wasOpen && window.innerWidth <= 960) els.menuToggle.focus();
}

function toggleSidebar() {
  if (document.body.classList.contains("sidebar-open")) closeSidebar();
  else openSidebar();
}

function isTypingTarget(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(
    target.closest("input, textarea, select, [contenteditable='true']")
  );
}

/* ---------- 事件绑定 ---------- */

function bindEvents() {
  els.menuToggle.addEventListener("click", toggleSidebar);
  els.sidebarClose.addEventListener("click", closeSidebar);
  els.scrim.addEventListener("click", closeSidebar);
  window.addEventListener("resize", () => {
    if (window.innerWidth > 960) closeSidebar();
    syncSidebarA11y();
  });

  els.searchInput.addEventListener("input", () => {
    state.search = els.searchInput.value;
    updateSearchClear();
    renderSidebar();
    renderMain();
  });
  els.searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (els.searchInput.value) clearSearch();
      else els.searchInput.blur();
    }
  });
  els.clearSearch.addEventListener("click", clearSearch);

  document.addEventListener("keydown", (event) => {
    if (document.querySelector("dialog[open]")) return;
    if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) {
      closeSidebar();
      return;
    }
    const isSlash = event.key === "/";
    const isCtrlK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
    if ((isSlash || isCtrlK) && !isTypingTarget(event.target)) {
      event.preventDefault();
      els.searchInput.focus();
      els.searchInput.select();
    }
  });

  els.newGroupTop.addEventListener("click", () => openGroupDialog());
  els.sidebarNewGroup.addEventListener("click", () => openGroupDialog());
  els.treeEmptyCreate.addEventListener("click", () => openGroupDialog());
  els.newLinkTop.addEventListener("click", () => openLinkDialog());
  els.addHereBtn.addEventListener("click", () => openLinkDialog());
  els.openDocsBtn.addEventListener("click", () => {
    if (state.selectedId === null) return;
    state.docsVisible = !state.docsVisible;
    els.docToggle.checked = state.docsVisible;
    persistDocsPreference();
    renderMain();
  });
  els.addSubgroupBtn.addEventListener("click", () => {
    if (state.selectedId !== null) openGroupDialog({ parentId: state.selectedId });
  });
  els.editGroupBtn.addEventListener("click", () => {
    if (state.selectedId === null) return;
    const group = findGroupById(state.selectedId);
    if (group) openGroupDialog({ group });
  });
  els.deleteGroupBtn.addEventListener("click", deleteCurrentGroup);

  els.allLinksNav.addEventListener("click", selectAll);

  els.groupTree.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-action]") : null;
    if (!target) return;
    const node = target.closest("[data-group-id]");
    if (!node) return;
    const groupId = Number(node.dataset.groupId);
    const action = target.dataset.action;
    if (action === "toggle") {
      if (state.expanded.has(groupId)) state.expanded.delete(groupId);
      else state.expanded.add(groupId);
      persistExpanded();
      renderSidebar();
    } else if (action === "select") {
      selectGroup(groupId);
    } else if (action === "add-child") {
      openGroupDialog({ parentId: groupId });
    } else if (action === "edit-group") {
      const group = findGroupById(groupId);
      if (group) openGroupDialog({ group });
    } else if (action === "docs") {
      openGroupDocs(groupId);
    }
  });

  els.breadcrumbs.addEventListener("click", (event) => {
    const crumb = event.target instanceof Element ? event.target.closest("[data-nav]") : null;
    if (!crumb) return;
    if (crumb.dataset.nav === "all") selectAll();
    else selectGroup(Number(crumb.dataset.nav));
  });

  els.linkGrid.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const card = event.target.closest("[data-link-id]");
    if (!card) return;

    const target = event.target.closest("button[data-action]");
    if (target) {
      const linkId = Number(card.dataset.linkId);
      const action = target.dataset.action;
      if (action === "up" || action === "down") moveLink(linkId, action);
      else if (action === "check") checkSingleLink(linkId);
      else if (action === "edit") openLinkDialog(linkId);
      else if (action === "delete") deleteLink(linkId);
      return;
    }

    // 链接本体由浏览器原生处理（新标签页、Cmd/Ctrl 点击等）
    if (event.target.closest("a")) return;

    // 兜底：极少数点不到覆盖层的情况也直接打开，避免静默无响应
    openExternalLink(card.dataset.linkUrl);
  });

  els.linkGrid.addEventListener("pointerdown", onCardPointerDown);
  document.addEventListener("pointermove", onCardPointerMove);
  document.addEventListener("pointerup", onCardPointerUp);
  document.addEventListener("pointercancel", onCardPointerCancel);
  els.linkGrid.addEventListener("dragstart", (event) => {
    if (event.target instanceof Element && event.target.closest(".link-card")) {
      event.preventDefault();
    }
  });
  document.addEventListener(
    "click",
    (event) => {
      if (!state.suppressClick) return;
      if (
        !(event.target instanceof Element) ||
        !event.target.closest("#linkGrid")
      ) {
        return;
      }
      state.suppressClick = false;
      event.preventDefault();
      event.stopPropagation();
    },
    true
  );
  window.addEventListener("blur", cancelCardDrag);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.dragState?.dragging) {
      event.preventDefault();
      cancelCardDrag();
    }
  });

  els.docToggle.addEventListener("change", () => {
    state.docsVisible = els.docToggle.checked;
    persistDocsPreference();
    renderMain();
  });

  els.docSelect.addEventListener("change", () => {
    const documentId = Number(els.docSelect.value);
    if (documentId) loadDocument(documentId);
  });
  els.docNewBtn.addEventListener("click", () => startDocEditor(null));
  els.docEditBtn.addEventListener("click", () => {
    if (state.currentDoc) startDocEditor(state.currentDoc);
  });
  els.docDeleteBtn.addEventListener("click", deleteCurrentDoc);
  els.docSaveBtn.addEventListener("click", saveDoc);
  els.docCancelBtn.addEventListener("click", closeDocEditor);
  els.docBody.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const actionNode = event.target.closest("[data-doc-action]");
    if (!actionNode) return;
    const action = actionNode.dataset.docAction;
    if (action === "new") startDocEditor(null);
    else if (action === "edit" && state.currentDoc) startDocEditor(state.currentDoc);
    else if (action === "reload" && state.docsGroupId) {
      const groupId = state.docsGroupId;
      state.docsGroupId = null;
      ensureDocsForGroup(groupId);
    }
  });
  els.docContentInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      saveDoc();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeDocEditor();
    }
  });

  els.checkAllBtn.addEventListener("click", () => {
    if (state.batchRun) {
      abortBatchRun({ announce: true });
    } else {
      startManualCheck();
    }
  });

  els.autoCheckToggle.addEventListener("change", () => {
    state.autoCheckEnabled = els.autoCheckToggle.checked;
    persistAutoCheckPreference();
    if (!state.autoCheckEnabled) {
      clearAutoCheckTimer();
      cancelAutoBatch();
      setCheckProgress("");
    } else {
      scheduleAutoCheck();
    }
  });

  window.addEventListener("beforeunload", () => {
    clearAutoCheckTimer();
    if (state.batchRun) state.batchRun.controller.abort();
    for (const active of state.singleChecks.values()) active.controller.abort();
  });

  els.retryBtn.addEventListener("click", boot);
  els.exportBtn.addEventListener("click", exportData);
  els.importBtn.addEventListener("click", () => {
    els.importFile.value = "";
    els.importFile.click();
  });
  els.importFile.addEventListener("change", () => {
    const file = els.importFile.files && els.importFile.files[0];
    importData(file);
  });

  els.groupForm.addEventListener("submit", saveGroup);
  els.linkForm.addEventListener("submit", saveLink);
  els.linkForm.addEventListener("input", hideLinkFormError);

  document.querySelectorAll("[data-close-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dialog = btn.closest("dialog");
      if (dialog) dialog.close();
    });
  });

  // 链接弹窗不响应遮罩层点击，也不响应 Esc，只能通过“取消”、关闭按钮或保存后关闭；分组弹窗保持原行为
  els.linkDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
  });
  for (const dialog of [els.groupDialog]) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  }
}
