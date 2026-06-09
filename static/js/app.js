const api = window.helpdeskAPI;

const state = {
  user: null,
  users: [],
  roles: [],
  permissions: [],
  tickets: [],
  categories: [],
  departments: [],
  notifications: [],
  audit: [],
  settings: {},
  backups: [],
  updateStatus: null,
  updateJobTimer: null,
  settingsTab: "settings-users-panel",
  ticketTab: "ticket-main-panel",
  selectedTicketIds: new Set(),
  selectedTicketId: null,
  selectedUserId: null,
  selectedRoleCode: null,
  socket: null,
  page: 0,
  pageSize: 20,
};

const statusLabels = {
  new: "Новая",
  in_progress: "В работе",
  waiting: "Ожидает",
  resolved: "Ожидает подтверждения",
  closed: "Закрыта",
  cancelled: "Отменена",
};

const priorityLabels = {
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
  critical: "Критический",
};

const roleLabels = {
  user: "Пользователь",
  service: "Сервисный сотрудник",
  operator: "Сервисный сотрудник",
  admin: "Администратор",
};

const historyActionLabels = {
  created: "Заявка создана",
  updated: "Поле изменено",
  status_changed: "Статус изменен",
  attachment_added: "Добавлено вложение",
  attachment_deleted: "Удалено вложение",
};

const viewTitles = {
  "create-view": "Создать заявку",
  "tickets-view": "Заявки",
  "ticket-edit-view": "Редактирование заявки",
  "reports-view": "Отчеты",
  "notifications-view": "Уведомления",
  "user-edit-view": "Редактирование пользователя",
  "role-edit-view": "Редактирование роли",
  "settings-view": "Настройки",
  "profile-view": "Профиль",
};

function byId(id) {
  return document.getElementById(id);
}

function isViewVisible(viewId) {
  return !byId(viewId).classList.contains("hidden");
}

function staffMode() {
  return hasPerm("tickets.read_all") || hasPerm("tickets.update_all");
}

function hasPerm(permission) {
  return Boolean(state.user?.permissions?.includes(permission));
}

function roleName(code) {
  const role = state.roles.find((item) => item.code === code);
  return role?.name || roleLabels[code] || code;
}

function roleHasPerm(code, permission) {
  const role = state.roles.find((item) => item.code === code);
  return role ? role.permissions.includes(permission) : ["service", "operator", "admin"].includes(code);
}

function roleOptions(selectedRole = "user") {
  const roles = state.roles.length
    ? state.roles
    : [
        { code: "user", name: "Пользователь" },
        { code: "service", name: "Сервисный сотрудник" },
        { code: "admin", name: "Администратор" },
      ];
  return roles
    .map((role) => `<option value="${role.code}" ${role.code === selectedRole ? "selected" : ""}>${escapeHtml(role.name)}</option>`)
    .join("");
}

function categoryOptions(selectedId = null, includeEmpty = true) {
  return [
    ...(includeEmpty ? ['<option value="">Без категории</option>'] : []),
    ...state.categories
      .filter((item) => item.is_active || item.id === selectedId)
      .map((item) => `<option value="${item.id}" ${item.id === selectedId ? "selected" : ""}>${escapeHtml(item.name)}</option>`),
  ].join("");
}

function departmentOptions(selectedId = null) {
  return [
    '<option value="">Без отдела</option>',
    ...state.departments
      .filter((item) => item.is_active || item.id === selectedId)
      .map((item) => `<option value="${item.id}" ${item.id === selectedId ? "selected" : ""}>${escapeHtml(item.name)}</option>`),
  ].join("");
}

function userOptions(selectedId = null, emptyLabel = "Не выбран") {
  return [
    `<option value="">${emptyLabel}</option>`,
    ...state.users
      .filter((item) => !item.is_archived)
      .map((item) => `<option value="${item.id}" ${item.id === selectedId ? "selected" : ""}>${escapeHtml(item.full_name || item.username)}</option>`),
  ].join("");
}

function refreshStatsIfAllowed() {
  return hasPerm("reports.view") ? loadStats() : Promise.resolve();
}

function configurePermissionUI() {
  byId("reports-nav").classList.toggle("hidden", !hasPerm("reports.view"));
  const canSeeUsersSettings = hasPerm("users.read") || hasPerm("users.create");
  const canSeeSettings = canSeeUsersSettings
    || hasPerm("roles.manage")
    || hasPerm("catalogs.manage")
    || hasPerm("audit.read")
    || hasPerm("manage_backups")
    || hasPerm("manage_updates");
  byId("settings-nav").classList.toggle("hidden", !canSeeSettings);
  byId("settings-users-tab").classList.toggle("hidden", !canSeeUsersSettings);
  byId("settings-roles-tab").classList.toggle("hidden", !hasPerm("roles.manage"));
  byId("settings-categories-tab").classList.toggle("hidden", !hasPerm("catalogs.manage"));
  byId("settings-departments-tab").classList.toggle("hidden", !hasPerm("catalogs.manage"));
  byId("settings-sla-tab").classList.toggle("hidden", !hasPerm("catalogs.manage"));
  byId("settings-audit-tab").classList.toggle("hidden", !hasPerm("audit.read"));
  byId("settings-backups-tab").classList.toggle("hidden", !hasPerm("manage_backups"));
  byId("settings-updates-tab").classList.toggle("hidden", !hasPerm("manage_updates"));
  byId("create-user").classList.toggle("hidden", !hasPerm("users.create"));
  byId("export-tickets").classList.toggle("hidden", !hasPerm("reports.export"));
  byId("export-users").classList.toggle("hidden", !hasPerm("reports.export"));
  byId("bulk-tickets").classList.toggle("hidden", !hasPerm("tickets.bulk"));

  const scope = byId("ticket-scope");
  const availableScopes = [
    ["all", "tickets.read_all"],
    ["mine", "tickets.read_own"],
    ["assigned", "tickets.read_assigned"],
    ["department", "tickets.read_department"],
  ].filter(([, permission]) => hasPerm(permission));
  [...scope.options].forEach((option) => {
    option.hidden = !availableScopes.some(([value]) => value === option.value);
  });
  if (!availableScopes.some(([value]) => value === scope.value)) {
    scope.value = availableScopes[0]?.[0] || "mine";
  }
  scope.classList.toggle("hidden", availableScopes.length <= 1);
  byId("tickets-heading").textContent = hasPerm("tickets.read_all") ? "Все заявки" : "Мои заявки";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDateShort(value) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) {
    return `${bytes} Б`;
  }
  const units = ["КБ", "МБ", "ГБ"];
  let size = bytes / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[index]}`;
}

function setPanelMessage(id, message, isError = false) {
  const element = byId(id);
  element.textContent = message || "";
  element.classList.toggle("hidden", !message);
  element.classList.toggle("error", isError);
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function showMaintenanceOverlay(title, message) {
  byId("maintenance-title").textContent = title;
  byId("maintenance-message").textContent = message;
  byId("maintenance-overlay").classList.remove("hidden");
}

function updateMaintenanceOverlay(title, message) {
  byId("maintenance-title").textContent = title;
  byId("maintenance-message").textContent = message;
}

function hideMaintenanceOverlay() {
  byId("maintenance-overlay").classList.add("hidden");
}

async function waitForServerReady({
  title = "Система запускается",
  message = "Подождите, сервер снова становится доступен.",
  timeoutMs = 120000,
  initialDelayMs = 2000,
  reload = true,
} = {}) {
  updateMaintenanceOverlay(title, message);
  await sleep(initialDelayMs);
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch("/health", { cache: "no-store" });
      if (response.ok) {
        updateMaintenanceOverlay("Система готова", "Обновляю страницу...");
        await sleep(800);
        if (reload) {
          window.location.reload();
        }
        return true;
      }
    } catch (error) {
      // Server can be temporarily unavailable while systemd restarts the app.
    }
    await sleep(2000);
  }
  updateMaintenanceOverlay("Сервер долго не отвечает", "Обновите страницу вручную через минуту или проверьте службу helpdesk.");
  await sleep(5000);
  hideMaintenanceOverlay();
  return false;
}

function slaBadge(ticket) {
  if (!ticket.due_at) {
    return "";
  }
  const className = ticket.is_overdue ? "sla-overdue" : "sla-ok";
  const label = ticket.is_overdue ? "SLA просрочен" : "SLA до";
  return `<span class="badge ${className}">${label}: ${formatDateShort(ticket.due_at)}</span>`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function toast(message) {
  const element = byId("toast");
  element.textContent = message;
  element.classList.remove("hidden");
  window.clearTimeout(toast.timeoutId);
  toast.timeoutId = window.setTimeout(() => element.classList.add("hidden"), 3000);
}

function showAuthMessage(message, isError = false) {
  const element = byId("auth-message");
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.remove("hidden");
}

function clearAuthMessage() {
  byId("auth-message").classList.add("hidden");
}

function switchAuthTab(mode) {
  const loginMode = mode === "login";
  byId("login-form").classList.toggle("hidden", !loginMode);
  byId("register-form").classList.toggle("hidden", loginMode);
  byId("login-tab").classList.toggle("active", loginMode);
  byId("register-tab").classList.toggle("active", !loginMode);
  clearAuthMessage();
}

function switchLoginMethod(mode) {
  const usernameMode = mode === "username";
  const form = byId("login-form");
  form.dataset.method = usernameMode ? "username" : "name";
  byId("name-login-fields").classList.toggle("hidden", usernameMode);
  byId("username-login-fields").classList.toggle("hidden", !usernameMode);
  byId("name-login-tab").classList.toggle("active", !usernameMode);
  byId("username-login-tab").classList.toggle("active", usernameMode);
  form.elements.first_name.disabled = usernameMode;
  form.elements.last_name.disabled = usernameMode;
  form.elements.username.disabled = !usernameMode;
  clearAuthMessage();
}

async function startSession() {
  state.user = await api.me();
  byId("auth-screen").classList.add("hidden");
  byId("app-screen").classList.remove("hidden");
  await loadRoles(true);
  byId("current-user").textContent = `${state.user.full_name || state.user.username} · ${roleName(state.user.role)}`;
  configurePermissionUI();
  fillProfileForm();
  switchView("create-view");

  await Promise.all([
    loadCatalogs(),
    loadUsers(),
    loadTickets().catch(() => {
      state.tickets = [];
      renderTickets();
    }),
    refreshStatsIfAllowed(),
    loadNotifications(),
  ]);
  if (state.user.must_change_password) {
    switchView("profile-view");
    toast("Необходимо сменить временный пароль");
  }
  connectSocket();
}

function fillProfileForm() {
  byId("profile-form").elements.email.value = state.user?.email || "";
  byId("profile-form").elements.first_name.value = state.user?.first_name || "";
  byId("profile-form").elements.last_name.value = state.user?.last_name || "";
}

function stopSession() {
  if (state.updateJobTimer) {
    window.clearInterval(state.updateJobTimer);
    state.updateJobTimer = null;
  }
  if (state.socket) {
    state.socket.close();
    state.socket = null;
  }
  api.setToken(null);
  state.user = null;
  state.users = [];
  state.tickets = [];
  state.categories = [];
  state.departments = [];
  state.notifications = [];
  state.backups = [];
  state.updateStatus = null;
  state.selectedTicketIds.clear();
  state.selectedTicketId = null;
  state.selectedRoleCode = null;
  byId("app-screen").classList.add("hidden");
  byId("auth-screen").classList.remove("hidden");
  byId("login-form").reset();
  switchLoginMethod("name");
  switchAuthTab("login");
}

function connectSocket() {
  if (state.socket) {
    state.socket.close();
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/all?token=${encodeURIComponent(api.token)}`);
  state.socket = socket;

  socket.addEventListener("open", () => {
    byId("connection-state").textContent = "online";
    byId("connection-state").classList.add("online");
  });
  socket.addEventListener("close", () => {
    byId("connection-state").textContent = "offline";
    byId("connection-state").classList.remove("online");
  });
  socket.addEventListener("message", async () => {
    await Promise.all([loadTickets(false), refreshStatsIfAllowed(), loadNotifications()]);
    if (state.selectedTicketId && isViewVisible("ticket-edit-view")) {
      await loadTicketDetail(state.selectedTicketId, false);
    }
  });
}

function switchView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.add("hidden"));
  byId(viewId).classList.remove("hidden");
  const activeNavView = viewId === "ticket-edit-view"
    ? "tickets-view"
    : viewId === "user-edit-view"
      ? "settings-view"
    : viewId === "role-edit-view"
      ? "settings-view"
      : viewId;
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === activeNavView);
  });
  byId("view-title").textContent = viewTitles[viewId] || "Help Desk";
}

function ticketBadge(ticket) {
  return `
    <span class="badge status-${ticket.status}">${statusLabels[ticket.status] || ticket.status}</span>
    <span class="badge priority-${ticket.priority}">${priorityLabels[ticket.priority] || ticket.priority}</span>
  `;
}

function userName(id) {
  const user = state.users.find((item) => item.id === id);
  return user ? user.full_name || user.username : "Не назначен";
}

async function loadTickets(keepSelection = true) {
  const form = new FormData(byId("filter-form"));
  const params = {
    scope: form.get("scope"),
    q: form.get("q"),
    status: form.get("status"),
    priority: form.get("priority"),
    category_id: form.get("category_id"),
    sort_by: form.get("sort_by"),
    sort_dir: form.get("sort_dir"),
    skip: state.page * state.pageSize,
    limit: state.pageSize,
  };
  state.tickets = await api.tickets(params);
  renderTickets();
  renderPager();

  if (!keepSelection || !state.selectedTicketId) {
    return;
  }
  const stillExists = state.tickets.some((ticket) => ticket.id === state.selectedTicketId);
  if (stillExists && isViewVisible("ticket-edit-view")) {
    await loadTicketDetail(state.selectedTicketId, false);
  } else if (!stillExists) {
    state.selectedTicketId = null;
    if (isViewVisible("ticket-edit-view")) {
      switchView("tickets-view");
      toast("Заявка больше не найдена");
    }
  }
}

function renderPager() {
  byId("page-label").textContent = `Страница ${state.page + 1}`;
  byId("prev-page").disabled = state.page === 0;
  byId("next-page").disabled = state.tickets.length < state.pageSize;
}

function renderTickets() {
  const list = byId("ticket-list");
  if (!state.tickets.length) {
    list.innerHTML = '<div class="empty-state">Заявок нет</div>';
    renderRecentTickets();
    return;
  }
  list.innerHTML = state.tickets.map((ticket) => `
    <article class="ticket-item ${ticket.id === state.selectedTicketId ? "active" : ""}" data-ticket-id="${ticket.id}">
      <span class="ticket-title-row">
        <input class="ticket-select ${hasPerm("tickets.bulk") ? "" : "hidden"}" type="checkbox" aria-label="Выбрать заявку ${ticket.id}" ${state.selectedTicketIds.has(ticket.id) ? "checked" : ""}>
        <span class="ticket-title">#${ticket.id} ${escapeHtml(ticket.title)}</span>
      </span>
      <span class="ticket-meta">${ticketBadge(ticket)}</span>
      <span class="ticket-meta">${slaBadge(ticket)}</span>
      <span class="ticket-meta">Создана ${formatDate(ticket.created_at)}</span>
      <span class="ticket-kpis">
        <span>Автор: ${escapeHtml(ticket.creator_name || userName(ticket.created_by))}</span>
        <span>Исполнитель: ${escapeHtml(ticket.assignee_name || "Не назначен")}</span>
        <span>Категория: ${escapeHtml(ticket.category_name || "Без категории")}</span>
        <span>Вложения: ${ticket.attachments_count}</span>
      </span>
    </article>
  `).join("");
  renderRecentTickets();
}

function renderRecentTickets() {
  const container = byId("recent-tickets");
  if (!container) {
    return;
  }
  const recent = state.tickets.slice(0, 5);
  if (!recent.length) {
    container.innerHTML = '<div class="empty-state">Заявок пока нет</div>';
    return;
  }
  container.innerHTML = recent.map((ticket) => `
    <button class="recent-ticket" type="button" data-ticket-id="${ticket.id}">
      <strong>#${ticket.id} ${escapeHtml(ticket.title)}</strong>
      <span class="ticket-meta">${ticketBadge(ticket)}</span>
      <span class="ticket-meta">${formatDate(ticket.created_at)}</span>
    </button>
  `).join("");
}

function renderEmptyDetail() {
  byId("ticket-detail").innerHTML = '<div class="empty-state">Загрузка заявки</div>';
}

async function openTicketEdit(ticketId) {
  state.ticketTab = "ticket-main-panel";
  state.selectedTicketId = ticketId;
  renderEmptyDetail();
  switchView("ticket-edit-view");
  await loadTicketDetail(ticketId);
}

async function loadTicketDetail(ticketId, markActive = true) {
  const [ticket, attachments, history] = await Promise.all([
    api.ticket(ticketId),
    api.attachments(ticketId),
    api.history(ticketId),
  ]);
  state.selectedTicketId = ticket.id;
  byId("view-title").textContent = `Заявка #${ticket.id}`;
  renderTicketDetail(ticket, attachments, history);
  if (markActive) {
    renderTickets();
  }
}

function switchTicketTab(panelId = state.ticketTab) {
  let tab = byId("ticket-detail").querySelector(`[data-ticket-tab="${panelId}"]`);
  if (!tab) {
    tab = byId("ticket-detail").querySelector("[data-ticket-tab]");
  }
  if (!tab) {
    return;
  }
  state.ticketTab = tab.dataset.ticketTab;
  byId("ticket-detail").querySelectorAll("[data-ticket-tab]").forEach((item) => {
    const active = item === tab;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  byId("ticket-detail").querySelectorAll(".ticket-detail-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.id !== state.ticketTab);
  });
}

function statusOptionsForTicket(ticket) {
  if (hasPerm("tickets.workflow")) {
    return Object.keys(statusLabels).filter((status) => status !== ticket.status);
  }
  if (ticket.created_by !== state.user.id) {
    return [];
  }
  if (ticket.status === "resolved") {
    return ["closed", "cancelled", "in_progress"];
  }
  if (["closed", "cancelled"].includes(ticket.status)) {
    return ["in_progress"];
  }
  return ["cancelled"];
}

function renderTicketDetail(ticket, attachments, history) {
  const canManage = hasPerm("tickets.update_all") || (hasPerm("tickets.update_own") && ticket.created_by === state.user.id);
  const canAssign = hasPerm("tickets.assign");
  const canDelete = hasPerm("tickets.delete");
  const statusOptions = statusOptionsForTicket(ticket);
  const assigneeOptions = [
    '<option value="">Не назначен</option>',
    ...state.users
      .filter((user) => roleHasPerm(user.role, "tickets.update_all") || roleHasPerm(user.role, "tickets.read_assigned"))
      .map((user) => `<option value="${user.id}" ${ticket.assigned_to === user.id ? "selected" : ""}>${escapeHtml(user.full_name || user.username)}</option>`),
  ].join("");

  byId("ticket-detail").innerHTML = `
    <div class="detail-toolbar">
      <button id="back-to-tickets" class="secondary-button" type="button">← К списку заявок</button>
    </div>
    <div class="detail-header">
      <div class="ticket-title-row">
        <h3>#${ticket.id} ${escapeHtml(ticket.title)}</h3>
        <span class="ticket-meta">${ticketBadge(ticket)}</span>
      </div>
      <span class="ticket-meta">${slaBadge(ticket)}</span>
      <span class="ticket-meta">Создана ${formatDate(ticket.created_at)} · Автор: ${escapeHtml(ticket.creator_name || userName(ticket.created_by))} · Исполнитель: ${escapeHtml(ticket.assignee_name || "Не назначен")}</span>
    </div>

    <nav class="ticket-detail-tabs" role="tablist" aria-label="Разделы заявки">
      <button class="ticket-detail-tab active" type="button" role="tab" aria-selected="true" data-ticket-tab="ticket-main-panel">Основное</button>
      <button class="ticket-detail-tab" type="button" role="tab" aria-selected="false" data-ticket-tab="ticket-work-panel">Выполнение</button>
      <button class="ticket-detail-tab" type="button" role="tab" aria-selected="false" data-ticket-tab="ticket-files-panel">
        Файлы <span class="tab-count">${attachments.length}</span>
      </button>
      <button class="ticket-detail-tab" type="button" role="tab" aria-selected="false" data-ticket-tab="ticket-history-panel">
        История <span class="tab-count">${history.length}</span>
      </button>
    </nav>

    <section id="ticket-main-panel" class="ticket-detail-panel" role="tabpanel">
      <form id="detail-form" class="stack-form">
        <div class="detail-grid">
          <label class="full">
            Тема
            <input name="title" value="${escapeHtml(ticket.title)}" required minlength="3" maxlength="200" ${canManage ? "" : "disabled"}>
          </label>
          <label>
            Приоритет
            <select name="priority" ${canManage ? "" : "disabled"}>
              ${Object.entries(priorityLabels).map(([value, label]) => `<option value="${value}" ${ticket.priority === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <label>
            Категория
            <select name="category_id" ${canManage ? "" : "disabled"}>${categoryOptions(ticket.category_id)}</select>
          </label>
          <label class="full ${canAssign ? "" : "hidden"}">
            Исполнитель
            <select name="assigned_to">${assigneeOptions}</select>
          </label>
          <label class="full">
            Описание
            <textarea name="description" required minlength="5" rows="5" ${canManage ? "" : "disabled"}>${escapeHtml(ticket.description)}</textarea>
          </label>
        </div>
        <div class="detail-actions">
          <button class="primary-button ${canManage ? "" : "hidden"}" type="submit">Сохранить</button>
          <button id="delete-ticket" class="secondary-button ${canDelete ? "danger-button" : "hidden"}" type="button">Удалить</button>
        </div>
      </form>
    </section>

    <section id="ticket-work-panel" class="ticket-detail-panel hidden" role="tabpanel">
      <div class="detail-section status-decision-section">
        <div>
          <h3>Решение по заявке</h3>
          <p class="muted-text">Текущий статус: <strong>${escapeHtml(statusLabels[ticket.status] || ticket.status)}</strong></p>
          ${ticket.closure_reason ? `<p class="decision-summary">${escapeHtml(ticket.closure_reason)}</p>` : ""}
        </div>
        ${statusOptions.length ? `
          <form id="status-decision-form" class="status-decision-form">
            <label>
              Новый статус
              <select name="status" required>
                ${statusOptions.map((status) => `<option value="${status}">${escapeHtml(statusLabels[status] || status)}</option>`).join("")}
              </select>
            </label>
            <label>
              Комментарий к решению
              <textarea name="comment" rows="5" minlength="1" maxlength="2000" required placeholder="Опишите выполненные действия или причину смены статуса"></textarea>
            </label>
            <div class="detail-actions">
              <button class="primary-button" type="submit">Сохранить решение</button>
            </div>
          </form>
        ` : '<div class="empty-state compact-empty">Для этой заявки сейчас нет доступных переходов статуса</div>'}
      </div>
    </section>

    <section id="ticket-files-panel" class="ticket-detail-panel hidden" role="tabpanel">
      <div class="detail-section">
        <h3>Файлы заявки</h3>
        <form id="attachment-form" class="compact-inline-form ${hasPerm("attachments.manage") ? "" : "hidden"}">
          <input name="file" type="file" required>
          <button class="secondary-button" type="submit">Загрузить файл</button>
        </form>
        <div id="attachment-list" class="attachment-list">
          ${attachments.length ? attachments.map((item) => renderAttachment(ticket.id, item)).join("") : '<div class="empty-state">Вложений нет</div>'}
        </div>
      </div>
    </section>

    <section id="ticket-history-panel" class="ticket-detail-panel hidden" role="tabpanel">
      <div class="detail-section">
        <h3>История изменений</h3>
      <div class="history-list">
        ${history.length ? history.map(renderHistoryItem).join("") : '<div class="empty-state">История пока пустая</div>'}
      </div>
      </div>
    </section>
  `;

  byId("back-to-tickets").addEventListener("click", () => {
    switchView("tickets-view");
  });

  byId("ticket-detail").querySelectorAll("[data-ticket-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTicketTab(button.dataset.ticketTab));
  });
  switchTicketTab();

  byId("detail-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = {
      title: data.get("title"),
      description: data.get("description"),
      priority: data.get("priority"),
      category_id: data.get("category_id") ? Number(data.get("category_id")) : null,
    };
    if (canAssign) {
      payload.assigned_to = data.get("assigned_to") ? Number(data.get("assigned_to")) : null;
    }
    await api.updateTicket(ticket.id, payload);
    toast("Заявка сохранена");
    await Promise.all([loadTickets(false), refreshStatsIfAllowed(), loadTicketDetail(ticket.id, false)]);
  });

  const deleteButton = byId("delete-ticket");
  if (deleteButton) {
    deleteButton.addEventListener("click", async () => {
      if (!window.confirm("Удалить заявку?")) {
        return;
      }
      await api.deleteTicket(ticket.id);
      state.selectedTicketId = null;
      toast("Заявка удалена");
      switchView("tickets-view");
      await Promise.all([loadTickets(false), refreshStatsIfAllowed()]);
    });
  }

  const statusDecisionForm = byId("status-decision-form");
  statusDecisionForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await api.changeTicketStatus(ticket.id, data.get("status"), data.get("comment"));
    state.ticketTab = "ticket-work-panel";
    toast("Статус заявки изменен");
    await Promise.all([loadTickets(false), refreshStatsIfAllowed(), loadTicketDetail(ticket.id, false)]);
  });

  byId("attachment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fileInput = form.elements.file;
    if (!fileInput.files.length) {
      return;
    }
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    await api.uploadAttachment(ticket.id, formData);
    form.reset();
    toast("Файл загружен");
    await Promise.all([loadTickets(false), loadTicketDetail(ticket.id, false)]);
  });

  byId("attachment-list").querySelectorAll("[data-delete-attachment]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api.deleteAttachment(ticket.id, Number(button.dataset.deleteAttachment));
      toast("Вложение удалено");
      await Promise.all([loadTickets(false), loadTicketDetail(ticket.id, false)]);
    });
  });
  byId("attachment-list").querySelectorAll("[data-download-attachment]").forEach((button) => {
    button.addEventListener("click", async () => {
      const blob = await api.downloadAttachment(Number(button.dataset.downloadAttachment));
      downloadBlob(blob, button.dataset.filename || "attachment");
    });
  });
}

function renderAttachment(ticketId, attachment) {
  return `
    <div class="attachment-item">
      <div>
        <strong>${escapeHtml(attachment.filename)}</strong>
        <small>${formatDate(attachment.uploaded_at)}</small>
      </div>
      <div class="detail-actions">
        <button class="secondary-button" type="button" data-download-attachment="${attachment.id}" data-filename="${escapeHtml(attachment.filename)}">Скачать</button>
        <button class="secondary-button danger-button ${hasPerm("attachments.manage") ? "" : "hidden"}" type="button" data-delete-attachment="${attachment.id}">Удалить</button>
      </div>
    </div>
  `;
}

function renderHistoryItem(item) {
  const action = historyActionLabels[item.action] || item.action;
  const field = item.field ? ` · ${escapeHtml(item.field)}` : "";
  const values = item.old_value || item.new_value
    ? `<div>${escapeHtml(item.old_value || "пусто")} → ${escapeHtml(item.new_value || "пусто")}</div>`
    : "";
  const note = item.note
    ? `<div class="history-note">${escapeHtml(item.note).replaceAll("\n", "<br>")}</div>`
    : "";
  return `
    <article class="history-item">
      <div>
        <strong>${escapeHtml(action)}${field}</strong>
        ${values}
        ${note}
        <small>${escapeHtml(item.user_name || "Система")} · ${formatDate(item.created_at)}</small>
      </div>
    </article>
  `;
}

async function loadUsers() {
  if (!hasPerm("users.read")) {
    state.users = [state.user];
    renderUsers();
    byId("settings-user-count").textContent = state.users.length;
    return;
  }
  state.users = await api.users();
  renderUsers();
  byId("settings-user-count").textContent = state.users.length;
}

async function loadCatalogs() {
  const [categories, departments] = await Promise.all([
    api.categories(),
    api.departments(),
  ]);
  state.categories = categories;
  state.departments = departments;
  byId("create-category").innerHTML = categoryOptions();
  byId("filter-category").innerHTML = '<option value="">Все категории</option>' + categoryOptions(null, false);
}

async function loadNotifications() {
  state.notifications = await api.notifications();
  const unread = state.notifications.filter((item) => !item.is_read).length;
  byId("notification-count").textContent = unread ? `(${unread})` : "";
  renderNotifications();
}

function renderNotifications() {
  const container = byId("notifications-list");
  if (!state.notifications.length) {
    container.innerHTML = '<div class="empty-state">Уведомлений нет</div>';
    return;
  }
  container.innerHTML = state.notifications.map((item) => `
    <button class="notification-item ${item.is_read ? "" : "unread"}" type="button" data-notification-id="${item.id}" data-ticket-id="${item.ticket_id || ""}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.message)}</span>
      <small>${formatDate(item.created_at)}</small>
    </button>
  `).join("");
  container.querySelectorAll("[data-notification-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api.readNotification(Number(button.dataset.notificationId));
      if (button.dataset.ticketId) {
        await openTicketEdit(Number(button.dataset.ticketId));
      } else {
        await loadNotifications();
      }
    });
  });
}

function switchSettingsTab(panelId = state.settingsTab) {
  let tab = document.querySelector(`[data-settings-tab="${panelId}"]`);
  if (!tab || tab.classList.contains("hidden")) {
    tab = document.querySelector(".settings-tab:not(.hidden)");
  }
  if (!tab) {
    return;
  }
  state.settingsTab = tab.dataset.settingsTab;
  document.querySelectorAll(".settings-tab").forEach((item) => {
    const active = item === tab;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".settings-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.id !== state.settingsTab);
  });
}

function openSettingsSection(panelId) {
  state.settingsTab = panelId;
  switchView("settings-view");
  switchSettingsTab(panelId);
}

function resetSettingsEditor(formId, createLabel) {
  const form = byId(formId);
  form.reset();
  delete form.dataset.editId;
  form.querySelector('[type="submit"]').textContent = createLabel;
  form.querySelector(".cancel-settings-edit")?.classList.add("hidden");
}

function editCategory(item) {
  const form = byId("category-form");
  form.dataset.editId = item.id;
  form.elements.name.value = item.name;
  form.elements.sla_hours.value = item.sla_hours || "";
  form.elements.default_assignee_id.value = item.default_assignee_id || "";
  form.elements.is_active.value = String(item.is_active);
  form.querySelector('[type="submit"]').textContent = "Сохранить категорию";
  form.querySelector(".cancel-settings-edit").classList.remove("hidden");
  form.elements.name.focus();
}

function editDepartment(item) {
  const form = byId("department-form");
  form.dataset.editId = item.id;
  form.elements.name.value = item.name;
  form.elements.manager_id.value = item.manager_id || "";
  form.elements.is_active.value = String(item.is_active);
  form.querySelector('[type="submit"]').textContent = "Сохранить отдел";
  form.querySelector(".cancel-settings-edit").classList.remove("hidden");
  form.elements.name.focus();
}

async function loadSettingsView() {
  await Promise.all([
    hasPerm("users.read") ? loadUsers() : Promise.resolve(),
    hasPerm("roles.manage") ? loadRoles(true) : Promise.resolve(),
    hasPerm("manage_backups") ? loadBackups(true) : Promise.resolve(),
    hasPerm("manage_updates") ? loadUpdateStatus(true) : Promise.resolve(),
  ]);
  const [settings, audit] = await Promise.all([
    hasPerm("catalogs.manage") ? api.settings() : Promise.resolve({}),
    hasPerm("audit.read") ? api.audit() : Promise.resolve([]),
  ]);
  state.settings = settings;
  state.audit = audit;
  if (hasPerm("catalogs.manage")) {
    ["critical", "high", "medium", "low"].forEach((key) => {
      byId("sla-form").elements[`sla.${key}`].value = settings[`sla.${key}`] || "";
    });
    byId("category-form").elements.default_assignee_id.innerHTML = userOptions(null, "Без автоназначения");
    byId("department-form").elements.manager_id.innerHTML = userOptions(null, "Без руководителя");
  }
  byId("settings-user-count").textContent = state.users.length;
  byId("settings-role-count").textContent = state.roles.length;
  byId("settings-category-count").textContent = state.categories.length;
  byId("settings-department-count").textContent = state.departments.length;
  byId("settings-backup-count").textContent = state.backups.length;

  byId("categories-list").innerHTML = state.categories.map((item) => `
    <div class="catalog-item" data-category-id="${item.id}">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${item.default_assignee_id ? `Автоназначение: ${escapeHtml(userName(item.default_assignee_id))}` : "Без автоназначения"} · SLA: ${item.sla_hours ? `${item.sla_hours} ч.` : "по приоритету"}</span>
      <span class="badge catalog-state">${item.is_active ? "Активна" : "Отключена"}</span>
      <button class="secondary-button edit-category" type="button">Изменить</button>
    </div>
  `).join("") || '<div class="empty-state compact-empty">Категорий пока нет</div>';
  byId("departments-list").innerHTML = state.departments.map((item) => `
    <div class="catalog-item" data-department-id="${item.id}">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${item.manager_id ? `Руководитель: ${escapeHtml(userName(item.manager_id))}` : "Без руководителя"}</span>
      <span class="badge catalog-state">${item.is_active ? "Активен" : "Отключен"}</span>
      <button class="secondary-button edit-department" type="button">Изменить</button>
    </div>
  `).join("") || '<div class="empty-state compact-empty">Отделов пока нет</div>';
  byId("audit-list").innerHTML = state.audit.map((item) => `
    <article class="history-item"><div><strong>${escapeHtml(item.action)}</strong><div>${escapeHtml(item.entity_type)} ${escapeHtml(item.entity_id || "")}</div><small>${escapeHtml(item.user_name || "Система")} · ${formatDate(item.created_at)}</small></div></article>
  `).join("") || '<div class="empty-state">Журнал пуст</div>';

  byId("categories-list").querySelectorAll(".edit-category").forEach((button) => {
    button.addEventListener("click", () => {
      const item = state.categories.find((value) => value.id === Number(button.closest("[data-category-id]").dataset.categoryId));
      editCategory(item);
    });
  });
  byId("departments-list").querySelectorAll(".edit-department").forEach((button) => {
    button.addEventListener("click", () => {
      const item = state.departments.find((value) => value.id === Number(button.closest("[data-department-id]").dataset.departmentId));
      editDepartment(item);
    });
  });
  switchSettingsTab();
}

async function loadBackups(silent = false) {
  if (!hasPerm("manage_backups")) {
    state.backups = [];
    return;
  }
  try {
    state.backups = await api.backups();
    renderBackups();
    byId("settings-backup-count").textContent = state.backups.length;
  } catch (error) {
    if (!silent) {
      setPanelMessage("backups-status", error.message, true);
    }
  }
}

function renderBackups() {
  const container = byId("backups-list");
  if (!state.backups.length) {
    container.innerHTML = '<div class="empty-state">Резервных копий пока нет</div>';
    return;
  }
  container.innerHTML = `
    <div class="backup-list-header" aria-hidden="true">
      <span>Файл</span>
      <span>Дата</span>
      <span>Размер</span>
      <span>База</span>
      <span>Версия</span>
      <span>Commit</span>
      <span></span>
    </div>
    ${state.backups.map((backup) => `
      <article class="backup-row" data-backup-file="${escapeHtml(backup.filename)}">
        <strong title="${escapeHtml(backup.filename)}">${escapeHtml(backup.filename)}</strong>
        <span>${formatDate(backup.created_at)}</span>
        <span>${formatBytes(backup.size_bytes)}</span>
        <span>${escapeHtml(backup.database_type || "-")}</span>
        <span>${escapeHtml(backup.app_version || "-")}</span>
        <span>${escapeHtml(backup.git_commit || "-")}</span>
        <span class="detail-actions">
          <button class="secondary-button download-backup" type="button">Скачать</button>
          <button class="secondary-button restore-backup" type="button">Восстановить</button>
          <button class="secondary-button danger-button delete-backup" type="button">Удалить</button>
        </span>
      </article>
    `).join("")}
  `;

  container.querySelectorAll(".download-backup").forEach((button) => {
    button.addEventListener("click", async () => {
      const filename = button.closest("[data-backup-file]").dataset.backupFile;
      const blob = await api.downloadBackup(filename);
      downloadBlob(blob, filename);
    });
  });
  container.querySelectorAll(".restore-backup").forEach((button) => {
    button.addEventListener("click", async () => {
      const filename = button.closest("[data-backup-file]").dataset.backupFile;
      if (!window.confirm("Восстановление заменит текущие данные системы. Перед восстановлением будет создана аварийная копия текущего состояния, а старые backup-файлы будут очищены.")) {
        return;
      }
      showMaintenanceOverlay("Восстановление системы", "Данные восстанавливаются из резервной копии. Не закрывайте страницу.");
      setPanelMessage("backups-status", "Восстановление выполняется...");
      try {
        await api.restoreBackup(filename);
        setPanelMessage("backups-status", "Система восстановлена из резервной копии");
        updateMaintenanceOverlay("Восстановление завершено", "Обновляю страницу...");
        await sleep(800);
        window.location.reload();
      } catch (error) {
        hideMaintenanceOverlay();
        setPanelMessage("backups-status", error.message, true);
      }
    });
  });
  container.querySelectorAll(".delete-backup").forEach((button) => {
    button.addEventListener("click", async () => {
      const filename = button.closest("[data-backup-file]").dataset.backupFile;
      if (!window.confirm(`Удалить резервную копию ${filename}?`)) {
        return;
      }
      await api.deleteBackup(filename);
      setPanelMessage("backups-status", "Резервная копия удалена");
      await loadBackups(true);
    });
  });
}

async function loadUpdateStatus(silent = false) {
  if (!hasPerm("manage_updates")) {
    state.updateStatus = null;
    return;
  }
  try {
    state.updateStatus = await api.updateStatus();
    renderUpdateStatus();
    await loadUpdateLog(true);
  } catch (error) {
    if (!silent) {
      setPanelMessage("update-job-status", error.message, true);
    }
  }
}

function updateStatusLabel(value) {
  return {
    idle: "не запускалось",
    running: "выполняется",
    success: "успешно",
    failed: "ошибка",
  }[value] || value || "-";
}

function checkStatusLabel(value) {
  return {
    idle: "не проверялось",
    success: "успешно",
    failed: "ошибка",
  }[value] || value || "-";
}

function renderUpdateStatus() {
  const status = state.updateStatus;
  const container = byId("update-summary");
  if (!status) {
    container.innerHTML = '<div class="empty-state">Статус обновления не загружен</div>';
    return;
  }
  const available = status.update_available === null || status.update_available === undefined
    ? "не проверялось"
    : status.update_available
      ? "есть новая версия"
      : "обновлений нет";
  const canRunUpdate = status.web_update_enabled && status.last_update_status !== "running";
  const currentCommit = status.current_commit ? status.current_commit.slice(0, 12) : "-";
  const remoteCommit = status.remote_commit ? status.remote_commit.slice(0, 12) : "-";
  container.innerHTML = `
    <div class="update-hero">
      <div>
        <span class="section-eyebrow">Текущая версия</span>
        <strong>${escapeHtml(status.app_version || "-")}</strong>
        <small>${escapeHtml(status.current_branch || "-")} · ${escapeHtml(currentCommit)}</small>
      </div>
      <span class="state-pill ${status.update_available ? "warning" : "ok"}">${escapeHtml(available)}</span>
    </div>
    <div class="summary-grid update-grid">
      <div>
        <span>Режим работы</span>
        <strong>${escapeHtml(status.runtime_mode || "-")}</strong>
      </div>
      <div>
        <span>Обновление кнопкой</span>
        <strong>${status.web_update_enabled ? "включено" : "отключено"}</strong>
      </div>
      <div>
        <span>Commit в GitHub</span>
        <strong>${escapeHtml(remoteCommit)}</strong>
      </div>
      <div>
        <span>Последняя проверка</span>
        <strong>${status.last_check_at ? formatDate(status.last_check_at) : "-"}</strong>
        <small>${checkStatusLabel(status.last_check_status)}</small>
      </div>
      <div>
        <span>Последний запуск</span>
        <strong>${updateStatusLabel(status.last_update_status)}</strong>
        <small>${status.last_update_at ? formatDate(status.last_update_at) : "запусков не было"}</small>
      </div>
      <div>
        <span>Лог</span>
        <strong>${escapeHtml(status.update_log_path || "-")}</strong>
      </div>
    </div>
    ${status.web_update_enabled
      ? '<div class="settings-note ok">Кнопка обновления включена. Перед запуском система автоматически создаст резервную копию.</div>'
      : '<div class="settings-note warning"><strong>Почему кнопка отключена:</strong> на сервере не включен параметр HELPDESK_ENABLE_WEB_UPDATE. На Windows-локалхосте это нормально, потому что обновление запускает Linux-скрипт для Raspberry Pi. После установки на Pi установщик включит этот режим в .env.</div>'}
    ${status.last_check_message ? `<div class="settings-note ${status.last_check_status === "failed" ? "error" : ""}">${escapeHtml(status.last_check_message)}</div>` : ""}
    ${status.last_update_message ? `<div class="settings-note ${status.last_update_status === "failed" ? "error" : ""}">${escapeHtml(status.last_update_message)}</div>` : ""}
  `;
  const runButton = byId("run-update");
  runButton.disabled = !canRunUpdate;
  runButton.title = status.web_update_enabled
    ? "Запустить обновление системы"
    : "Кнопка включается параметром HELPDESK_ENABLE_WEB_UPDATE на сервере";
}

async function loadUpdateLog(silent = false) {
  if (!hasPerm("manage_updates")) {
    return;
  }
  try {
    const log = await api.updateLogs(120);
    byId("update-log").textContent = log.lines.length ? log.lines.join("\n") : "Лог пока пуст";
  } catch (error) {
    if (!silent) {
      setPanelMessage("update-job-status", error.message, true);
    }
  }
}

async function pollUpdateJob(jobId) {
  if (state.updateJobTimer) {
    window.clearInterval(state.updateJobTimer);
    state.updateJobTimer = null;
  }
  const startedAt = Date.now();
  while (Date.now() - startedAt < 10 * 60 * 1000) {
    try {
      const job = await api.updateJob(jobId);
      const message = job.message || updateStatusLabel(job.status);
      setPanelMessage("update-job-status", message, job.status === "failed");
      updateMaintenanceOverlay("Обновление системы", message);
      await Promise.all([loadUpdateStatus(true), loadUpdateLog(true)]).catch(() => null);
      if (job.status === "success") {
        setPanelMessage("update-job-status", "Обновление завершено. Система перезапускается...");
        await waitForServerReady({
          title: "Обновление завершено",
          message: "Система перезапускается. Не закрывайте страницу.",
          initialDelayMs: 2500,
        });
        return job;
      }
      if (job.status === "failed") {
        hideMaintenanceOverlay();
        return job;
      }
    } catch (error) {
      await waitForServerReady({
        title: "Система перезапускается",
        message: "Соединение временно пропало. Жду, пока Help Desk снова поднимется.",
        initialDelayMs: 1000,
      });
      return null;
    }
    await sleep(2500);
  }
  hideMaintenanceOverlay();
  setPanelMessage("update-job-status", "Обновление выполняется слишком долго. Проверьте лог и состояние службы.", true);
  return null;
}

async function loadRoles(silent = false) {
  if (!hasPerm("roles.manage")) {
    return;
  }
  try {
    const [permissions, roles] = await Promise.all([api.permissions(), api.roles()]);
    state.permissions = permissions;
    state.roles = roles;
    renderRoles();
    byId("settings-role-count").textContent = state.roles.length;
    refreshRoleSelects();
  } catch (error) {
    if (!silent) {
      toast(error.message);
    }
  }
}

function refreshRoleSelects() {
  const userRoleSelect = byId("user-detail")?.querySelector('[name="role"]');
  if (userRoleSelect) {
    const current = userRoleSelect.value || "user";
    userRoleSelect.innerHTML = roleOptions(current);
  }
}

function renderUsers() {
  const container = byId("users-list");
  if (!state.users.length) {
    container.innerHTML = '<div class="empty-state">Пользователей нет</div>';
    return;
  }
  container.innerHTML = `
    <div class="user-list-header" aria-hidden="true">
      <span>Пользователь</span>
      <span>Логин</span>
      <span>Роль</span>
      <span>Статус</span>
      <span></span>
    </div>
    ${state.users.map((user) => `
    <article class="user-row" data-user-id="${user.id}">
      <strong>${escapeHtml(user.full_name || user.username)}</strong>
      <span>${escapeHtml(user.username)}</span>
      <span>${escapeHtml(roleName(user.role))}</span>
      <span class="badge ${user.is_active ? "status-closed" : "status-new"}">${user.is_archived ? "Архив" : user.is_active ? "Активен" : "Отключен"}</span>
      <button class="secondary-button open-user" type="button">Открыть</button>
    </article>
    `).join("")}
  `;

  container.querySelectorAll(".open-user").forEach((button) => {
    button.addEventListener("click", () => {
      openUserEdit(Number(button.closest("[data-user-id]").dataset.userId));
    });
  });
}

function renderUserDetail(user = null) {
  const creating = !user;
  const canEdit = creating ? hasPerm("users.create") : hasPerm("users.update");
  const ownAccount = user?.id === state.user?.id;
  byId("user-detail").innerHTML = `
    <div class="detail-toolbar">
      <button id="back-to-users" class="secondary-button" type="button">← К списку пользователей</button>
    </div>
    <form id="user-detail-form" class="stack-form">
      <div class="detail-grid user-detail-grid">
        <label>
          Логин
          <input name="username" value="${escapeHtml(user?.username || "")}" required minlength="2" maxlength="50" ${canEdit && !ownAccount ? "" : "disabled"}>
        </label>
        <label>
          Email (необязательно)
          <input name="email" type="email" value="${escapeHtml(user?.email || "")}" ${canEdit ? "" : "disabled"}>
        </label>
        <label>
          Имя
          <input name="first_name" value="${escapeHtml(user?.first_name || "")}" required minlength="1" maxlength="60" ${canEdit ? "" : "disabled"}>
        </label>
        <label>
          Фамилия
          <input name="last_name" value="${escapeHtml(user?.last_name || "")}" required minlength="1" maxlength="60" ${canEdit ? "" : "disabled"}>
        </label>
        <label>
          Роль
          <select name="role" ${canEdit ? "" : "disabled"}>${roleOptions(user?.role || "user")}</select>
        </label>
        <label>
          Активен
          <select name="is_active" ${canEdit ? "" : "disabled"}>
            <option value="true" ${user?.is_active !== false ? "selected" : ""}>Да</option>
            <option value="false" ${user?.is_active === false ? "selected" : ""}>Нет</option>
          </select>
        </label>
        <label>
          Отдел
          <select name="department_id" ${canEdit ? "" : "disabled"}>${departmentOptions(user?.department_id || null)}</select>
        </label>
        <label class="full">
          ${creating ? "Пароль" : "Новый пароль (оставьте пустым, чтобы не менять)"}
          <input name="password" type="password" ${creating ? "required" : ""} minlength="4" maxlength="72" ${canEdit ? "" : "disabled"}>
        </label>
      </div>
      <div id="user-detail-message" class="message hidden"></div>
      ${canEdit ? `
        <div class="detail-actions">
          <button class="primary-button" type="submit">${creating ? "Создать пользователя" : "Сохранить пользователя"}</button>
          ${!creating && hasPerm("users.reset_password") ? '<button id="reset-user-password" class="secondary-button" type="button">Сбросить пароль</button>' : ""}
          ${!creating && hasPerm("users.archive") && !ownAccount ? `<button id="archive-user" class="secondary-button danger-button" type="button">${user.is_archived ? "Вернуть из архива" : "Архивировать"}</button>` : ""}
          ${!creating && user.is_archived && hasPerm("users.delete") && !ownAccount ? '<button id="delete-user" class="secondary-button danger-button" type="button">Удалить окончательно</button>' : ""}
        </div>
      ` : ""}
    </form>
  `;

  byId("back-to-users").addEventListener("click", () => openSettingsSection("settings-users-panel"));
  if (!canEdit) {
    return;
  }
  byId("user-detail-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submitButton = form.querySelector('button[type="submit"]');
    const rawEmail = form.elements.email.value.trim();
    const email = rawEmail || null;
    const payload = {
      username: form.elements.username.value,
      email,
      first_name: form.elements.first_name.value.trim(),
      last_name: form.elements.last_name.value.trim(),
      role: form.elements.role.value,
      is_active: form.elements.is_active.value === "true",
      department_id: form.elements.department_id.value ? Number(form.elements.department_id.value) : null,
    };
    if (ownAccount) {
      delete payload.username;
    }
    if (form.elements.password.value) {
      payload.password = form.elements.password.value;
    }
    submitButton.disabled = true;
    setPanelMessage("user-detail-message", creating ? "Создание пользователя..." : "Сохранение пользователя...");
    try {
      const saved = creating
        ? await api.createUser(payload)
        : await api.updateUser(user.id, payload);
      await loadUsers();
      if (saved.id === state.user.id) {
        state.user = await api.me();
        configurePermissionUI();
        byId("current-user").textContent = `${state.user.full_name || state.user.username} · ${roleName(state.user.role)}`;
      }
      setPanelMessage("user-detail-message", creating ? "Пользователь создан" : "Пользователь сохранен");
      toast(creating ? "Пользователь создан" : "Пользователь сохранен");
      openUserEdit(saved.id);
    } catch (error) {
      setPanelMessage("user-detail-message", error.message, true);
    } finally {
      submitButton.disabled = false;
    }
  });
  const resetButton = byId("reset-user-password");
  if (resetButton) {
    resetButton.addEventListener("click", async () => {
      const password = window.prompt("Введите временный пароль");
      if (!password) return;
      await api.resetUserPassword(user.id, password);
      toast("Временный пароль установлен");
    });
  }
  const archiveButton = byId("archive-user");
  if (archiveButton) {
    archiveButton.addEventListener("click", async () => {
      const saved = await api.archiveUser(user.id, !user.is_archived);
      await loadUsers();
      openUserEdit(saved.id);
    });
  }
  const deleteUserButton = byId("delete-user");
  if (deleteUserButton) {
    deleteUserButton.addEventListener("click", async () => {
      if (!window.confirm("Окончательно удалить пользователя без связанных данных?")) return;
      await api.deleteUser(user.id);
      await loadUsers();
      openSettingsSection("settings-users-panel");
    });
  }
}

function openUserEdit(userId) {
  const user = state.users.find((item) => item.id === userId);
  if (!user) {
    toast("Пользователь не найден");
    return;
  }
  state.settingsTab = "settings-users-panel";
  state.selectedUserId = user.id;
  renderUserDetail(user);
  switchView("user-edit-view");
  byId("view-title").textContent = `Пользователь: ${user.full_name || user.username}`;
}

function openUserCreate() {
  state.settingsTab = "settings-users-panel";
  state.selectedUserId = null;
  renderUserDetail();
  switchView("user-edit-view");
  byId("view-title").textContent = "Новый пользователь";
}

function renderRoles() {
  const container = byId("roles-list");
  if (!container) {
    return;
  }
  if (!state.roles.length) {
    container.innerHTML = '<div class="empty-state">Ролей нет</div>';
    return;
  }
  container.innerHTML = `
    <div class="role-list-header" aria-hidden="true">
      <span>Название</span>
      <span>Код</span>
      <span>Количество прав</span>
      <span></span>
    </div>
    ${state.roles.map((role) => `
      <article class="role-row" data-role-code="${escapeHtml(role.code)}">
        <strong>${escapeHtml(role.name)}</strong>
        <span>${escapeHtml(role.code)}</span>
        <span>${role.permissions.length}</span>
        <button class="secondary-button open-role" type="button">Открыть</button>
      </article>
    `).join("")}
  `;

  container.querySelectorAll(".open-role").forEach((button) => {
    button.addEventListener("click", () => {
      openRoleEdit(button.closest("[data-role-code]").dataset.roleCode);
    });
  });
}

function openRoleEdit(roleCode) {
  const role = state.roles.find((item) => item.code === roleCode);
  if (!role) {
    toast("Роль не найдена");
    return;
  }
  state.settingsTab = "settings-roles-panel";
  state.selectedRoleCode = role.code;
  renderRoleDetail(role);
  switchView("role-edit-view");
  byId("view-title").textContent = `Роль: ${role.name}`;
}

function renderRoleDetail(role) {
  byId("role-detail").innerHTML = `
    <div class="detail-toolbar">
      <button id="back-to-roles" class="secondary-button" type="button">← К списку ролей</button>
    </div>
    <form id="role-edit-form" class="stack-form">
      <div class="detail-grid">
        <label>
          Код роли
          <input value="${escapeHtml(role.code)}" disabled>
        </label>
        <label>
          Название
          <input name="name" value="${escapeHtml(role.name)}" required minlength="2" maxlength="120">
        </label>
      </div>
      <div class="detail-section">
        <h3>Права роли</h3>
        <div class="permissions-grid">
          ${state.permissions.map((permission) => `
            <label class="permission-check">
              <input type="checkbox" name="permissions" value="${permission.code}" ${role.permissions.includes(permission.code) ? "checked" : ""}>
              <span>${escapeHtml(permission.name)}</span>
            </label>
          `).join("")}
        </div>
      </div>
      <div class="detail-actions">
        <button class="primary-button" type="submit">Сохранить роль</button>
      </div>
    </form>
  `;

  byId("back-to-roles").addEventListener("click", () => openSettingsSection("settings-roles-panel"));
  byId("role-edit-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const updated = await api.updateRole(role.code, {
      name: form.elements.name.value,
      permissions: [...form.querySelectorAll('[name="permissions"]:checked')].map((item) => item.value),
    });
    const index = state.roles.findIndex((item) => item.code === updated.code);
    if (index >= 0) {
      state.roles[index] = updated;
    }
    if (updated.code === state.user.role) {
      state.user = await api.me();
      configurePermissionUI();
    }
    renderRoles();
    renderUsers();
    refreshRoleSelects();
    byId("current-user").textContent = `${state.user.full_name || state.user.username} · ${roleName(state.user.role)}`;
    renderRoleDetail(updated);
    byId("view-title").textContent = `Роль: ${updated.name}`;
    toast("Роль сохранена");
  });
}

function openRoleCreate() {
  state.settingsTab = "settings-roles-panel";
  state.selectedRoleCode = null;
  byId("role-detail").innerHTML = `
    <div class="detail-toolbar">
      <button id="back-to-roles" class="secondary-button" type="button">← К списку ролей</button>
    </div>
    <form id="role-create-form" class="stack-form">
      <div class="detail-grid">
        <label>
          Код роли
          <input name="code" required minlength="2" maxlength="40" pattern="[a-z][a-z0-9_-]*" placeholder="support_lead">
        </label>
        <label>
          Название
          <input name="name" required minlength="2" maxlength="120">
        </label>
      </div>
      <div class="detail-section">
        <h3>Права роли</h3>
        <div class="permissions-grid">
          ${state.permissions.map((permission) => `
            <label class="permission-check">
              <input type="checkbox" name="permissions" value="${permission.code}">
              <span>${escapeHtml(permission.name)}</span>
            </label>
          `).join("")}
        </div>
      </div>
      <div class="detail-actions">
        <button class="primary-button" type="submit">Создать роль</button>
      </div>
    </form>
  `;
  switchView("role-edit-view");
  byId("view-title").textContent = "Новая роль";
  byId("back-to-roles").addEventListener("click", () => openSettingsSection("settings-roles-panel"));
  byId("role-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const created = await api.createRole({
      code: form.elements.code.value,
      name: form.elements.name.value,
      permissions: [...form.querySelectorAll('[name="permissions"]:checked')].map((item) => item.value),
    });
    state.roles.push(created);
    renderRoles();
    refreshRoleSelects();
    toast("Роль создана");
    openRoleEdit(created.code);
  });
}

async function loadStats() {
  if (!hasPerm("reports.view")) {
    return;
  }
  const stats = await api.dashboard();
  byId("metric-total").textContent = stats.total;
  byId("metric-overdue").textContent = stats.overdue || 0;
  renderBarList(byId("status-report"), stats.by_status, statusLabels);
  renderBarList(byId("priority-report"), stats.by_priority, priorityLabels);
  renderDays(stats.by_day);
}

function renderBarList(container, values, labels) {
  const entries = Object.entries(labels).map(([key, label]) => [key, label, values[key] || 0]);
  const max = Math.max(1, ...entries.map((entry) => entry[2]));
  container.innerHTML = entries.map(([key, label, count]) => `
    <div class="bar-row">
      <span>${label}</span>
      <span class="bar-track"><span class="bar-fill ${key}" style="width: ${(count / max) * 100}%"></span></span>
      <strong>${count}</strong>
    </div>
  `).join("");
}

function renderDays(days) {
  const max = Math.max(1, ...days.map((item) => item.count));
  byId("day-report").innerHTML = days.map((item) => {
    const date = new Date(item.day);
    const label = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit" }).format(date);
    return `
      <div class="day-column">
        <span class="day-bar" style="height: ${Math.max(4, (item.count / max) * 150)}px"></span>
        <strong>${item.count}</strong>
        <span>${label}</span>
      </div>
    `;
  }).join("");
}

function bindEvents() {
  byId("login-tab").addEventListener("click", () => switchAuthTab("login"));
  byId("register-tab").addEventListener("click", () => switchAuthTab("register"));
  byId("name-login-tab").addEventListener("click", () => switchLoginMethod("name"));
  byId("username-login-tab").addEventListener("click", () => switchLoginMethod("username"));

  byId("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAuthMessage();
    const data = new FormData(event.currentTarget);
    const payload = {
      password: data.get("password"),
      remember: data.get("remember") === "on",
    };
    if (event.currentTarget.dataset.method === "username") {
      payload.username = data.get("username");
    } else {
      payload.first_name = data.get("first_name");
      payload.last_name = data.get("last_name");
    }
    try {
      await api.login(payload);
      await startSession();
    } catch (error) {
      showAuthMessage(error.message, true);
    }
  });

  byId("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAuthMessage();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      await api.register(data);
      showAuthMessage("Аккаунт создан. Можно войти.");
      form.reset();
      switchAuthTab("login");
    } catch (error) {
      showAuthMessage(error.message, true);
    }
  });

  byId("logout-button").addEventListener("click", stopSession);

  document.querySelectorAll(".nav-button").forEach((button) => {
    button.addEventListener("click", async () => {
      switchView(button.dataset.view);
      if (button.dataset.view === "tickets-view") {
        await loadTickets(false);
      }
      if (button.dataset.view === "reports-view") {
        await refreshStatsIfAllowed();
      }
      if (button.dataset.view === "notifications-view") {
        await loadNotifications();
      }
      if (button.dataset.view === "settings-view") {
        await loadSettingsView();
      }
    });
  });

  document.querySelectorAll(".settings-tab").forEach((button) => {
    button.addEventListener("click", () => switchSettingsTab(button.dataset.settingsTab));
  });

  byId("ticket-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const ticket = await api.createTicket({
      title: data.get("title"),
      priority: data.get("priority"),
      description: data.get("description"),
      category_id: data.get("category_id") ? Number(data.get("category_id")) : null,
    });
    const file = form.elements.file.files[0];
    if (file) {
      const attachment = new FormData();
      attachment.append("file", file);
      await api.uploadAttachment(ticket.id, attachment);
    }
    form.reset();
    toast("Заявка создана");
    await Promise.all([loadTickets(false), refreshStatsIfAllowed()]);
  });

  byId("open-all-tickets").addEventListener("click", async () => {
    switchView("tickets-view");
    await loadTickets(false);
  });

  byId("recent-tickets").addEventListener("click", async (event) => {
    const item = event.target.closest("[data-ticket-id]");
    if (item) {
      await openTicketEdit(Number(item.dataset.ticketId));
    }
  });

  byId("filter-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.page = 0;
    await loadTickets();
  });

  byId("refresh-tickets").addEventListener("click", async () => {
    await loadTickets();
    toast("Очередь обновлена");
  });

  byId("prev-page").addEventListener("click", async () => {
    if (state.page === 0) {
      return;
    }
    state.page -= 1;
    await loadTickets(false);
  });

  byId("next-page").addEventListener("click", async () => {
    state.page += 1;
    await loadTickets(false);
  });

  byId("export-tickets").addEventListener("click", async () => {
    if (!hasPerm("reports.export")) {
      return;
    }
    const blob = await api.exportTickets();
    downloadBlob(blob, "tickets.csv");
  });

  byId("bulk-tickets").addEventListener("click", async () => {
    if (!state.selectedTicketIds.size) {
      toast("Выберите заявки");
      return;
    }
    const status = window.prompt("Новый статус: new, in_progress, waiting, resolved, closed или cancelled");
    if (!status) return;
    await api.bulkUpdateTickets({ ticket_ids: [...state.selectedTicketIds], status });
    state.selectedTicketIds.clear();
    await loadTickets(false);
  });

  byId("read-all-notifications").addEventListener("click", async () => {
    await api.readAllNotifications();
    await loadNotifications();
  });

  byId("refresh-users").addEventListener("click", async () => {
    await loadUsers();
    toast("Список обновлен");
  });

  byId("create-user").addEventListener("click", openUserCreate);

  byId("create-role").addEventListener("click", openRoleCreate);

  byId("refresh-roles").addEventListener("click", async () => {
    await loadRoles();
    toast("Роли обновлены");
  });

  byId("refresh-backups").addEventListener("click", async () => {
    await loadBackups();
    toast("Список резервных копий обновлен");
  });

  byId("create-backup").addEventListener("click", async () => {
    setPanelMessage("backups-status", "Создание резервной копии...");
    await api.createBackup();
    setPanelMessage("backups-status", "Резервная копия создана");
    await loadBackups(true);
  });

  byId("upload-backup-trigger").addEventListener("click", () => {
    byId("backup-upload-input").click();
  });

  byId("backup-upload-input").addEventListener("change", async (event) => {
    const file = event.currentTarget.files[0];
    if (!file) {
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setPanelMessage("backups-status", "Загрузка резервной копии...");
    await api.uploadBackup(formData);
    event.currentTarget.value = "";
    setPanelMessage("backups-status", "Резервная копия загружена");
    await loadBackups(true);
  });

  byId("check-updates").addEventListener("click", async () => {
    setPanelMessage("update-job-status", "Проверка обновлений...");
    state.updateStatus = await api.checkUpdates();
    renderUpdateStatus();
    setPanelMessage("update-job-status", "Проверка обновлений завершена", state.updateStatus.last_check_status === "failed");
  });

  byId("run-update").addEventListener("click", async () => {
    if (!window.confirm("Перед обновлением будет создана резервная копия. Запустить обновление системы?")) {
      return;
    }
    showMaintenanceOverlay("Обновление системы", "Создается резервная копия и загружается новая версия.");
    try {
      const job = await api.runUpdate();
      setPanelMessage("update-job-status", job.message || "Обновление запущено");
      await pollUpdateJob(job.job_id);
    } catch (error) {
      hideMaintenanceOverlay();
      setPanelMessage("update-job-status", error.message, true);
    }
  });

  byId("refresh-update-log").addEventListener("click", async () => {
    await Promise.all([loadUpdateStatus(true), loadUpdateLog()]);
    toast("Лог обновлен");
  });

  byId("category-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      name: form.elements.name.value,
      sla_hours: form.elements.sla_hours.value ? Number(form.elements.sla_hours.value) : null,
      default_assignee_id: form.elements.default_assignee_id.value ? Number(form.elements.default_assignee_id.value) : null,
      is_active: form.elements.is_active.value === "true",
    };
    if (form.dataset.editId) {
      await api.updateCategory(Number(form.dataset.editId), payload);
      toast("Категория сохранена");
    } else {
      await api.createCategory(payload);
      toast("Категория добавлена");
    }
    resetSettingsEditor("category-form", "Добавить категорию");
    await loadCatalogs();
    await loadSettingsView();
  });

  byId("department-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      name: form.elements.name.value,
      manager_id: form.elements.manager_id.value ? Number(form.elements.manager_id.value) : null,
      is_active: form.elements.is_active.value === "true",
    };
    if (form.dataset.editId) {
      await api.updateDepartment(Number(form.dataset.editId), payload);
      toast("Отдел сохранен");
    } else {
      await api.createDepartment(payload);
      toast("Отдел добавлен");
    }
    resetSettingsEditor("department-form", "Добавить отдел");
    await loadCatalogs();
    await loadSettingsView();
  });

  byId("category-form").querySelector(".cancel-settings-edit").addEventListener("click", () => {
    resetSettingsEditor("category-form", "Добавить категорию");
  });
  byId("department-form").querySelector(".cancel-settings-edit").addEventListener("click", () => {
    resetSettingsEditor("department-form", "Добавить отдел");
  });

  byId("sla-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await api.updateSettings(Object.fromEntries(data.entries()));
    toast("Настройки SLA сохранены");
  });

  byId("export-users").addEventListener("click", async () => {
    downloadBlob(await api.exportUsers(), "users.csv");
  });

  byId("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.email = payload.email || null;
    state.user = await api.updateMe(payload);
    byId("current-user").textContent = `${state.user.full_name || state.user.username} · ${roleName(state.user.role)}`;
    toast("Профиль сохранен");
  });

  byId("password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    await api.changePassword(payload);
    form.reset();
    toast("Пароль изменен");
  });

  byId("ticket-list").addEventListener("click", async (event) => {
    if (event.target.matches(".ticket-select")) {
      const id = Number(event.target.closest("[data-ticket-id]").dataset.ticketId);
      if (event.target.checked) state.selectedTicketIds.add(id);
      else state.selectedTicketIds.delete(id);
      return;
    }
    const item = event.target.closest("[data-ticket-id]");
    if (!item) {
      return;
    }
    await openTicketEdit(Number(item.dataset.ticketId));
  });
}

async function init() {
  switchLoginMethod("name");
  bindEvents();
  if (!api.token) {
    return;
  }
  try {
    await startSession();
  } catch {
    stopSession();
  }
}

document.addEventListener("DOMContentLoaded", init);
