let latencyChartInstance = null;

// Wrapper around fetch that redirects to /login on 401 and shows a friendly
// error on 403. Without this, an expired session or a permission denial
// would silently leave the dashboard frozen.
async function authedFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('Session expired');
    }
    return response;
}

// --- Chart ---

function initChart() {
    const ctx = document.getElementById('latencyChart').getContext('2d');
    let gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.5)');
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

    Chart.defaults.color = '#888';
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";

    latencyChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Response Time (ms)',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: gradient,
                borderWidth: 2,
                pointBackgroundColor: '#1e1e1e',
                pointBorderColor: '#3b82f6',
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
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    borderColor: '#333',
                    borderWidth: 1
                }
            },
            scales: {
                y: { beginAtZero: true, grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                x: { grid: { display: false } }
            }
        }
    });
}

// --- Telemetry ---

async function fetchMetrics() {
    try {
        const response = await authedFetch('/telemetry/metrics');
        const data = await response.json();

        document.getElementById('metric-total-requests').innerText = data.total_requests;
        document.getElementById('metric-p95-latency').innerText = data.p95_latency_ms;
        document.getElementById('metric-avg-latency').innerText = data.average_latency_ms;
        document.getElementById('metric-error-count').innerText = data.error_count;

        const healthEl = document.getElementById('metric-system-health');
        const healthCard = document.getElementById('health-card');
        const isDegraded = data.system_health === "Degraded";

        healthEl.innerText = data.system_health;

        healthCard.classList.remove('metric-success', 'metric-warning');
        healthCard.classList.add(isDegraded ? 'metric-warning' : 'metric-success');

        healthEl.classList.remove('text-success', 'text-warning');
        healthEl.classList.add(isDegraded ? 'text-warning' : 'text-success');
    } catch (error) {
        console.error("Error fetching metrics:", error);
    }
}

async function fetchLogs() {
    try {
        const response = await authedFetch('/telemetry/logs?limit=20');
        const logs = await response.json();
        const chartLogs = [...logs].reverse();
        updateChart(chartLogs);
        updateTable(logs);
    } catch (error) {
        console.error("Error fetching logs:", error);
    }
}

function formatTime(date) {
    const pad = n => String(n).padStart(2, '0');
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function updateChart(logs) {
    if (!latencyChartInstance) return;
    const labels = logs.map(log => formatTime(new Date(log.timestamp)));
    const dataPoints = logs.map(log => log.response_time_ms);
    latencyChartInstance.data.labels = labels;
    latencyChartInstance.data.datasets[0].data = dataPoints;
    latencyChartInstance.update();
}

function updateTable(logs) {
    const tbody = document.getElementById('log-table-body');
    tbody.innerHTML = '';
    logs.forEach(log => {
        const tr = document.createElement('tr');
        let statusBadge = 'bg-success';
        if (log.status_code >= 400) statusBadge = 'bg-warning text-dark';
        if (log.status_code >= 500) statusBadge = 'bg-danger';
        tr.innerHTML = `
            <td>${new Date(log.timestamp).toLocaleString()}</td>
            <td><strong>${log.method}</strong></td>
            <td><code>${log.endpoint}</code></td>
            <td><span class="badge ${statusBadge}">${log.status_code}</span></td>
            <td>${log.response_time_ms.toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}

// --- Orders ---

async function placeOrder(itemName) {
    try {
        await authedFetch('/orders/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_name: itemName, quantity: 1 })
        });
        fetchOrders(); fetchMetrics(); fetchLogs();
    } catch (error) {
        console.error("Error placing order:", error);
    }
}

async function fetchOrders() {
    try {
        const response = await authedFetch('/orders/');
        const orders = await response.json();
        const tbody = document.getElementById('queue-table-body');
        tbody.innerHTML = '';
        const activeOrders = orders.filter(o => !o.is_completed).slice(0, 5);
        activeOrders.forEach(order => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>#${order.id}</td>
                <td><strong>${order.item_name}</strong></td>
                <td><span class="badge bg-warning text-dark">Pending</span></td>
                <td><button class="btn btn-sm btn-success" onclick="completeOrder(${order.id})">Serve</button></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (error) {
        console.error("Error fetching orders:", error);
    }
}

async function completeOrder(orderId) {
    try {
        await authedFetch(`/orders/${orderId}/complete`, { method: 'PUT' });
        fetchOrders(); fetchMetrics(); fetchLogs();
    } catch (error) {
        console.error("Error completing order:", error);
    }
}

async function simulatePeakHours() {
    const btn = document.getElementById('btn-stress-test');
    const indicator = document.getElementById('stress-indicator');
    btn.disabled = true;
    btn.classList.add('btn-danger');
    btn.classList.remove('btn-outline-danger');
    indicator.style.display = 'block';

    const items = ['Espresso', 'Latte', 'Croissant', 'Americano', 'Mocha'];
    const promises = [];
    for (let i = 0; i < 50; i++) {
        const randomItem = items[Math.floor(Math.random() * items.length)];
        promises.push(
            authedFetch('/orders/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_name: randomItem, quantity: 1 })
            })
        );
    }

    try {
        await Promise.allSettled(promises);
        fetchOrders(); fetchMetrics(); fetchLogs();
    } catch (error) {
        console.error("Stress test encountered an error:", error);
    } finally {
        btn.disabled = false;
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-outline-danger');
        indicator.style.display = 'none';
    }
}

// --- User Management ---

const ROLE_BADGES = {
    admin:   'bg-warning text-dark',
    barista: 'bg-info text-dark',
    customer: 'bg-secondary'
};

async function fetchUsers() {
    try {
        const response = await authedFetch('/users/');
        if (!response.ok) {
            // 403 if the current user isn't admin — render nothing instead of crashing.
            return;
        }
        const users = await response.json();
        renderUsers(users);
    } catch (error) {
        console.error("Error fetching users:", error);
    }
}

function renderUsers(users) {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    users.forEach(user => {
        const tr = document.createElement('tr');
        const isSelf = user.username === window.CURRENT_USERNAME;
        const badgeClass = ROLE_BADGES[user.role] || 'bg-secondary';

        // Role <select>: disabled for self (can't change own role).
        const roleSelect = `
            <select class="form-select form-select-sm bg-dark text-light"
                    style="max-width: 140px; display: inline-block;"
                    ${isSelf ? 'disabled' : ''}
                    onchange="changeUserRole(${user.id}, this.value, '${user.role}')">
                <option value="customer" ${user.role === 'customer' ? 'selected' : ''}>Customer</option>
                <option value="barista"  ${user.role === 'barista'  ? 'selected' : ''}>Barista</option>
                <option value="admin"    ${user.role === 'admin'    ? 'selected' : ''}>Admin</option>
            </select>
        `;

        // Delete button: hidden for self.
        const deleteBtn = isSelf
            ? `<span class="text-muted small">— you —</span>`
            : `<button class="btn btn-sm btn-outline-danger"
                       onclick="deleteUser(${user.id}, '${user.username}')">
                  <i class="bi bi-trash"></i>
               </button>`;

        tr.innerHTML = `
            <td class="text-muted">#${user.id}</td>
            <td><strong>${user.username}</strong>${isSelf ? ' <span class="badge bg-primary ms-1">you</span>' : ''}</td>
            <td>
                <span class="badge ${badgeClass} text-uppercase me-2">${user.role}</span>
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
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole })
        });
        if (!response.ok) {
            // Surface the server's error message (e.g. "cannot demote last admin").
            const err = await response.json().catch(() => ({ detail: 'Update failed' }));
            alert(`Could not update role: ${err.detail}`);
        }
        fetchUsers();
    } catch (error) {
        console.error("Error updating role:", error);
        fetchUsers();
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
    try {
        const response = await authedFetch(`/users/${userId}`, { method: 'DELETE' });
        if (!response.ok && response.status !== 204) {
            const err = await response.json().catch(() => ({ detail: 'Delete failed' }));
            alert(`Could not delete user: ${err.detail}`);
        }
        fetchUsers();
    } catch (error) {
        console.error("Error deleting user:", error);
        fetchUsers();
    }
}

// --- Boot ---

document.addEventListener('DOMContentLoaded', () => {
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

    // User list refreshes on a slower cadence — it changes much less often.
    setInterval(fetchUsers, 10000);
});
