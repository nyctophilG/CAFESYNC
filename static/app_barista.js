// static/app_barista.js — barista station logic.
// Strictly: see queue + click "Serve". Does NOT place orders.

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
}

const MUTATING_METHODS = new Set(["POST", "PUT", "DELETE", "PATCH"]);

async function authedFetch(url, options) {
    const opts = { credentials: "same-origin", ...(options || {}) };
    const method = (opts.method || "GET").toUpperCase();
    if (MUTATING_METHODS.has(method)) {
        opts.headers = { ...(opts.headers || {}), "X-CSRF-Token": getCsrfToken() };
    }
    const response = await fetch(url, opts);
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

async function fetchOrders() {
    try {
        const response = await authedFetch("/orders/");
        if (!response.ok) return;
        const orders = await response.json();
        const tbody = document.getElementById("queue-table-body");
        if (!tbody) return;
        tbody.innerHTML = "";

        const activeOrders = orders.filter(o => !o.is_completed).slice(0, 20);
        if (activeOrders.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">No pending orders</td></tr>`;
            return;
        }
        activeOrders.forEach(order => {
            const tr = document.createElement("tr");
            const placerCell = order.placed_by_username
                ? `<span class="text-info">${escapeHtml(order.placed_by_username)}</span>`
                : `<span class="text-muted">—</span>`;
            tr.innerHTML = `
                <td>#${order.id}</td>
                <td><strong>${escapeHtml(order.item_name)}</strong></td>
                <td>${placerCell}</td>
                <td><span class="badge bg-warning text-dark">Pending</span></td>
                <td class="text-end pe-3">
                    <button class="btn btn-sm btn-success" onclick="completeOrder(${order.id})">
                        <i class="bi bi-check-circle me-1"></i>Serve
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error fetching orders:", err);
    }
}

async function completeOrder(orderId) {
    try {
        await authedFetch(`/orders/${orderId}/complete`, { method: "PUT" });
        fetchOrders();
    } catch (err) {
        console.error("Error completing order:", err);
    }
}
window.completeOrder = completeOrder;

document.addEventListener("DOMContentLoaded", () => {
    fetchOrders();
    setInterval(fetchOrders, 2000);
});
