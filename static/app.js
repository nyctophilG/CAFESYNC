// static/app.js — admin and viewer dashboard logic.

const IS_VIEWER = window.CURRENT_ROLE === "viewer";
const IS_ADMIN  = window.CURRENT_ROLE === "admin";

let latencyChartInstance = null;

async function authedFetch(url, options) {
    const response = await fetch(url, { credentials: "same-origin", ...(options || {}) });
    if (response.status === 401) {
        window.location.href = "/login";
        throw new Error("Session expired");
    }
    return response;
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

// --- Chart ---

function initChart() {
    const canvas = document.getElementById("latencyChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, "rgba(59, 130, 246, 0.5)");
    gradient.addColorStop(1, "rgba(59, 130, 246, 0.0)");

    Chart.defaults.color = "#888";
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";

    latencyChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                label: "Response Time (ms)",
                data: [],
                borderColor: "#3b82f6",
                backgroundColor: gradient,
                borderWidth: 2,
                pointBackgroundColor: "#1e1e1e",
                pointBorderColor: "#3b82f6",
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, grid: { color: "rgba(255, 255, 255, 0.05)" } },
                x: { grid: { display: false } }
            }
        }
    });
}

// --- Telemetry ---

async function fetchMetrics() {
    try {
        const response = await authedFetch("/telemetry/metrics");
        if (!response.ok) return; // Viewers may not have telemetry permission
        const data = await response.json();

        document.getElementById("metric-total-requests").innerText = data.total_requests;
        document.getElementById("metric-p95-latency").innerText = data.p95_latency_ms;
        document.getElementById("metric-avg-latency").innerText = data.average_latency_ms;
        document.getElementById("metric-error-count").innerText = data.error_count;

        const healthEl = document.getElementById("metric-system-health");
        const healthCard = document.getElementById("health-card");
        const isDegraded = data.system_health === "Degraded";

        healthEl.innerText = data.system_health;
        healthCard.classList.remove("metric-success", "metric-warning");
        healthCard.classList.add(isDegraded ? "metric-warning" : "metric-success");
        healthEl.classList.remove("text-success", "text-warning");
        healthEl.classList.add(isDegraded ? "text-warning" : "text-success");
    } catch (err) {
        console.error("Error fetching metrics:", err);
    }
}

async function fetchLogs() {
    try {
        const response = await authedFetch("/telemetry/logs?limit=20");
        if (!response.ok) return;
        const logs = await response.json();
        const chartLogs = [...logs].reverse();
        updateChart(chartLogs);
        updateLogTable(logs);
    } catch (err) {
        console.error("Error fetching logs:", err);
    }
}

function formatTime(date) {
    const pad = n => String(n).padStart(2, "0");
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function updateChart(logs) {
    if (!latencyChartInstance) return;
    latencyChartInstance.data.labels = logs.map(log => formatTime(new Date(log.timestamp)));
    latencyChartInstance.data.datasets[0].data = logs.map(log => log.response_time_ms);
    latencyChartInstance.update();
}

function updateLogTable(logs) {
    const tbody = document.getElementById("log-table-body");
    if (!tbody) return;
    tbody.innerHTML = "";
    logs.forEach(log => {
        const tr = document.createElement("tr");
        let statusBadge = "bg-success";
        if (log.status_code >= 400) statusBadge = "bg-warning text-dark";
        if (log.status_code >= 500) statusBadge = "bg-danger";
        tr.innerHTML = `
            <td>${new Date(log.timestamp).toLocaleString()}</td>
            <td><strong>${escapeHtml(log.method)}</strong></td>
            <td><code>${escapeHtml(log.endpoint)}</code></td>
            <td><span class="badge ${statusBadge}">${log.status_code}</span></td>
            <td>${log.response_time_ms.toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}

// --- Orders queue ---

async function fetchOrders() {
    try {
        const response = await authedFetch("/orders/");
        if (!response.ok) return;
        const orders = await response.json();
        const tbody = document.getElementById("queue-table-body");
        if (!tbody) return;
        tbody.innerHTML = "";
        const activeOrders = orders.filter(o => !o.is_completed).slice(0, 10);
        if (activeOrders.length === 0) {
            const colSpan = IS_ADMIN ? 5 : 4;
            tbody.innerHTML = `<tr><td colspan="${colSpan}" class="text-center text-muted py-4">No pending orders</td></tr>`;
            return;
        }
        activeOrders.forEach(order => {
            const tr = document.createElement("tr");
            const placerCell = order.placed_by_username
                ? `<span class="text-info">${escapeHtml(order.placed_by_username)}</span>`
                : `<span class="text-muted">—</span>`;
            const actionCell = IS_ADMIN
                ? `<td><button class="btn btn-sm btn-success" onclick="completeOrder(${order.id})">Serve</button></td>`
                : "";
            tr.innerHTML = `
                <td>#${order.id}</td>
                <td><strong>${escapeHtml(order.item_name)}</strong></td>
                <td>${placerCell}</td>
                <td><span class="badge bg-warning text-dark">Pending</span></td>
                ${actionCell}
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error fetching orders:", err);
    }
}

async function placeOrder(itemName) {
    if (!IS_ADMIN) return; // Viewer button is hidden, but be defensive
    try {
        await authedFetch("/orders/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_name: itemName, quantity: 1 })
        });
        fetchOrders(); fetchMetrics(); fetchLogs();
    } catch (err) {
        console.error("Error placing order:", err);
    }
}
window.placeOrder = placeOrder;

async function completeOrder(orderId) {
    if (!IS_ADMIN) return;
    try {
        await authedFetch(`/orders/${orderId}/complete`, { method: "PUT" });
        fetchOrders(); fetchMetrics(); fetchLogs();
    } catch (err) {
        console.error("Error completing order:", err);
    }
}
window.completeOrder = completeOrder;

async function simulatePeakHours() {
    if (!IS_ADMIN) return;
    const btn = document.getElementById("btn-stress-test");
    const indicator = document.getElementById("stress-indicator");
    if (!btn) return;

    btn.disabled = true;
    btn.classList.add("btn-danger");
    btn.classList.remove("btn-outline-danger");
    if (indicator) indicator.style.display = "block";

    const items = ["Espresso", "Latte", "Croissant", "Americano", "Mocha"];
    const promises = [];
    for (let i = 0; i < 50; i++) {
        const randomItem = items[Math.floor(Math.random() * items.length)];
        promises.push(
            authedFetch("/orders/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ item_name: randomItem, quantity: 1 })
            })
        );
    }
    try {
        await Promise.allSettled(promises);
        fetchOrders(); fetchMetrics(); fetchLogs();
    } catch (err) {
        console.error("Stress test error:", err);
    } finally {
        btn.disabled = false;
        btn.classList.remove("btn-danger");
        btn.classList.add("btn-outline-danger");
        if (indicator) indicator.style.display = "none";
    }
}
window.simulatePeakHours = simulatePeakHours;

// --- User management (admin only) ---

const ROLE_BADGES = {
    admin:   "bg-warning text-dark",
    barista: "bg-info text-dark",
    user:    "bg-secondary",
    viewer:  "bg-light text-dark"
};

async function fetchUsers() {
    if (!IS_ADMIN) return;
    try {
        const response = await authedFetch("/users/");
        if (!response.ok) return;
        const users = await response.json();
        renderUsers(users);
    } catch (err) {
        console.error("Error fetching users:", err);
    }
}

function renderUsers(users) {
    const tbody = document.getElementById("users-table-body");
    if (!tbody) return;
    tbody.innerHTML = "";
    users.forEach(user => {
        const tr = document.createElement("tr");
        const isSelf = user.username === window.CURRENT_USERNAME;
        const badgeClass = ROLE_BADGES[user.role] || "bg-secondary";

        const roleSelect = `
            <select class="form-select form-select-sm bg-dark text-light"
                    style="max-width: 140px; display: inline-block;"
                    ${isSelf ? "disabled" : ""}
                    onchange="changeUserRole(${user.id}, this.value, '${user.role}')">
                <option value="user"    ${user.role === "user"    ? "selected" : ""}>User</option>
                <option value="viewer"  ${user.role === "viewer"  ? "selected" : ""}>Viewer</option>
                <option value="barista" ${user.role === "barista" ? "selected" : ""}>Barista</option>
                <option value="admin"   ${user.role === "admin"   ? "selected" : ""}>Admin</option>
            </select>
        `;

        const deleteBtn = isSelf
            ? `<span class="text-muted small">— you —</span>`
            : `<button class="btn btn-sm btn-outline-danger"
                       onclick="deleteUser(${user.id}, '${escapeHtml(user.username)}')">
                  <i class="bi bi-trash"></i>
               </button>`;

        tr.innerHTML = `
            <td class="text-muted">#${user.id}</td>
            <td><strong>${escapeHtml(user.username)}</strong>${isSelf ? ' <span class="badge bg-primary ms-1">you</span>' : ""}</td>
            <td>
                <span class="badge ${badgeClass} text-uppercase me-2">${escapeHtml(user.role)}</span>
                ${roleSelect}
            </td>
            <td class="text-muted small">${new Date(user.created_at).toLocaleString()}</td>
            <td class="text-end pe-3">${deleteBtn}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function changeUserRole(userId, newRole, oldRole) {
    if (newRole === oldRole) return;
    try {
        const response = await authedFetch(`/users/${userId}/role`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role: newRole })
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: "Update failed" }));
            alert(`Could not update role: ${err.detail}`);
        }
        fetchUsers();
    } catch (err) {
        console.error("Error updating role:", err);
        fetchUsers();
    }
}
window.changeUserRole = changeUserRole;

async function deleteUser(userId, username) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
    try {
        const response = await authedFetch(`/users/${userId}`, { method: "DELETE" });
        if (!response.ok && response.status !== 204) {
            const err = await response.json().catch(() => ({ detail: "Delete failed" }));
            alert(`Could not delete user: ${err.detail}`);
        }
        fetchUsers();
    } catch (err) {
        console.error("Error deleting user:", err);
        fetchUsers();
    }
}
window.deleteUser = deleteUser;

// --- Boot ---

document.addEventListener("DOMContentLoaded", () => {
    initChart();
    fetchMetrics();
    fetchLogs();
    fetchOrders();
    fetchUsers();

    setInterval(() => {
        fetchMetrics();
        fetchLogs();
        fetchOrders();
    }, 2000);
    setInterval(fetchUsers, 10000);
});
