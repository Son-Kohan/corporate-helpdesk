class HelpDeskAPI {
  constructor() {
    this.baseURL = "/api";
    this.token = localStorage.getItem("helpdesk_token") || sessionStorage.getItem("helpdesk_token");
  }

  setToken(token, remember = false) {
    this.token = token;
    localStorage.removeItem("helpdesk_token");
    sessionStorage.removeItem("helpdesk_token");
    if (token) {
      const storage = remember ? localStorage : sessionStorage;
      storage.setItem("helpdesk_token", token);
    }
  }

  async request(endpoint, options = {}) {
    const headers = {
      ...(options.headers || {}),
    };

    if (!(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.baseURL}${endpoint}`, {
      ...options,
      headers,
      body: options.body && !(options.body instanceof FormData)
        ? JSON.stringify(options.body)
        : options.body,
    });

    if (response.status === 204) {
      return null;
    }

    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await response.json() : await response.text();

    if (!response.ok) {
      const detail = typeof data === "string" ? data : data.detail;
      throw new Error(detail || "Ошибка запроса");
    }
    return data;
  }

  async requestBlob(endpoint, options = {}) {
    const headers = {
      ...(options.headers || {}),
    };
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      ...options,
      headers,
    });
    if (!response.ok) {
      throw new Error("Не удалось скачать файл");
    }
    return response.blob();
  }

  async login(payload) {
    const data = await this.request("/users/login", {
      method: "POST",
      body: payload,
    });
    this.setToken(data.access_token, payload.remember);
    return data;
  }

  register(payload) {
    return this.request("/users/register", {
      method: "POST",
      body: payload,
    });
  }

  me() {
    return this.request("/users/me");
  }

  users() {
    return this.request("/users/");
  }

  createUser(payload) {
    return this.request("/users/", {
      method: "POST",
      body: payload,
    });
  }

  updateUser(id, payload) {
    return this.request(`/users/${id}`, {
      method: "PATCH",
      body: payload,
    });
  }

  archiveUser(id, archived) {
    return this.request(`/users/${id}/archive`, { method: "POST", body: { archived } });
  }

  resetUserPassword(id, temporaryPassword) {
    return this.request(`/users/${id}/reset-password`, {
      method: "POST",
      body: { temporary_password: temporaryPassword },
    });
  }

  deleteUser(id) {
    return this.request(`/users/${id}`, { method: "DELETE" });
  }

  updateMe(payload) {
    return this.request("/users/me", {
      method: "PATCH",
      body: payload,
    });
  }

  changePassword(payload) {
    return this.request("/users/me/password", {
      method: "POST",
      body: payload,
    });
  }

  permissions() {
    return this.request("/roles/permissions");
  }

  roles() {
    return this.request("/roles/");
  }

  createRole(payload) {
    return this.request("/roles/", {
      method: "POST",
      body: payload,
    });
  }

  updateRole(code, payload) {
    return this.request(`/roles/${code}`, {
      method: "PUT",
      body: payload,
    });
  }

  tickets(params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        query.set(key, value);
      }
    });
    const suffix = query.toString() ? `?${query}` : "";
    return this.request(`/tickets/${suffix}`);
  }

  ticket(id) {
    return this.request(`/tickets/${id}`);
  }

  createTicket(payload) {
    return this.request("/tickets/", {
      method: "POST",
      body: payload,
    });
  }

  updateTicket(id, payload) {
    return this.request(`/tickets/${id}`, {
      method: "PUT",
      body: payload,
    });
  }

  deleteTicket(id) {
    return this.request(`/tickets/${id}`, {
      method: "DELETE",
    });
  }

  bulkUpdateTickets(payload) {
    return this.request("/tickets/actions/bulk", { method: "POST", body: payload });
  }

  changeTicketStatus(id, status, comment) {
    return this.request(`/tickets/${id}/status`, {
      method: "POST",
      body: { status, comment },
    });
  }

  attachments(ticketId) {
    return this.request(`/tickets/${ticketId}/attachments`);
  }

  uploadAttachment(ticketId, formData) {
    return this.request(`/tickets/${ticketId}/attachments`, {
      method: "POST",
      body: formData,
    });
  }

  deleteAttachment(ticketId, attachmentId) {
    return this.request(`/tickets/${ticketId}/attachments/${attachmentId}`, {
      method: "DELETE",
    });
  }

  downloadAttachment(attachmentId) {
    return this.requestBlob(`/tickets/attachments/${attachmentId}`);
  }

  history(ticketId) {
    return this.request(`/tickets/${ticketId}/history`);
  }

  dashboard() {
    return this.request("/reports/dashboard");
  }

  exportTickets() {
    return this.requestBlob("/reports/export.csv");
  }

  departments() { return this.request("/catalogs/departments"); }
  createDepartment(payload) { return this.request("/catalogs/departments", { method: "POST", body: payload }); }
  updateDepartment(id, payload) { return this.request(`/catalogs/departments/${id}`, { method: "PUT", body: payload }); }
  categories() { return this.request("/catalogs/categories"); }
  createCategory(payload) { return this.request("/catalogs/categories", { method: "POST", body: payload }); }
  updateCategory(id, payload) { return this.request(`/catalogs/categories/${id}`, { method: "PUT", body: payload }); }
  settings() { return this.request("/catalogs/settings"); }
  updateSettings(settings) { return this.request("/catalogs/settings", { method: "PUT", body: { settings } }); }
  notifications(unreadOnly = false) { return this.request(`/notifications/?unread_only=${unreadOnly}`); }
  readNotification(id) { return this.request(`/notifications/${id}/read`, { method: "PATCH" }); }
  readAllNotifications() { return this.request("/notifications/read-all", { method: "POST" }); }
  audit() { return this.request("/admin/audit"); }
  exportUsers() { return this.requestBlob("/admin/users.csv"); }
  backups() { return this.request("/admin/backups"); }
  createBackup() { return this.request("/admin/backups", { method: "POST" }); }
  downloadBackup(filename) { return this.requestBlob(`/admin/backups/${encodeURIComponent(filename)}/download`); }
  deleteBackup(filename) { return this.request(`/admin/backups/${encodeURIComponent(filename)}`, { method: "DELETE" }); }
  restoreBackup(filename) { return this.request(`/admin/backups/${encodeURIComponent(filename)}/restore`, { method: "POST" }); }
  uploadBackup(formData) { return this.request("/admin/backups/upload", { method: "POST", body: formData }); }
  updateStatus() { return this.request("/admin/update/status"); }
  checkUpdates() { return this.request("/admin/update/check", { method: "POST" }); }
  runUpdate() { return this.request("/admin/update/run", { method: "POST" }); }
  updateJob(jobId) { return this.request(`/admin/update/jobs/${encodeURIComponent(jobId)}`); }
  updateLogs(lines = 80) { return this.request(`/admin/update/logs?lines=${lines}`); }
}

window.helpdeskAPI = new HelpDeskAPI();
