// static/menu_app.js
// Renders the menu from window.CAFESYNC_MENU into the page, handles
// "Place Order" clicks, and shows a toast on success.

const CAN_ORDER = window.CURRENT_ROLE !== "viewer";

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

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

function renderTabs() {
    const tabsEl = document.getElementById("menu-tabs");
    const contentEl = document.getElementById("menu-content");
    if (!tabsEl || !contentEl) return;

    tabsEl.innerHTML = "";
    contentEl.innerHTML = "";

    window.CAFESYNC_MENU.forEach((cat, idx) => {
        // Tab button
        const li = document.createElement("li");
        li.className = "nav-item";
        li.innerHTML = `
            <button class="nav-link ${idx === 0 ? "active" : ""}"
                    id="tab-${cat.id}"
                    data-bs-toggle="pill"
                    data-bs-target="#pane-${cat.id}"
                    type="button" role="tab">
                <i class="bi ${escapeHtml(cat.icon || "bi-circle")} me-1"></i>${escapeHtml(cat.label)}
            </button>
        `;
        tabsEl.appendChild(li);

        // Tab content
        const pane = document.createElement("div");
        pane.className = `tab-pane fade ${idx === 0 ? "show active" : ""}`;
        pane.id = `pane-${cat.id}`;
        pane.setAttribute("role", "tabpanel");

        const grid = document.createElement("div");
        grid.className = "row g-3";
        cat.items.forEach(item => {
            const col = document.createElement("div");
            col.className = "col-12 col-sm-6 col-lg-4";
            col.innerHTML = `
                <div class="menu-card p-3">
                    <div class="d-flex align-items-start gap-3 mb-2">
                        <i class="bi ${escapeHtml(item.icon || cat.icon || "bi-cup")} item-icon"></i>
                        <div class="flex-grow-1">
                            <h5>${escapeHtml(item.name)}</h5>
                            <div class="desc">${escapeHtml(item.description || "")}</div>
                        </div>
                    </div>
                    ${CAN_ORDER
                        ? `<button class="btn btn-primary btn-sm w-100 mt-2"
                                   data-item="${escapeHtml(item.name)}">
                              <i class="bi bi-plus-circle me-1"></i>Place Order
                           </button>`
                        : ""}
                </div>
            `;
            grid.appendChild(col);
        });
        pane.appendChild(grid);
        contentEl.appendChild(pane);
    });

    // Wire up "Place Order" buttons. Event delegation would be cleaner but
    // attaching directly is simpler given the small button count.
    document.querySelectorAll("[data-item]").forEach(btn => {
        btn.addEventListener("click", () => placeOrder(btn.dataset.item, btn));
    });
}

async function placeOrder(itemName, button) {
    if (!button) return;
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Placing…`;

    try {
        const res = await authedFetch("/orders/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_name: itemName, quantity: 1 }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: "Order failed" }));
            showToast(`Could not place order: ${err.detail}`, "danger");
            return;
        }
        const order = await res.json();
        showToast(`Order #${order.id} placed: ${order.item_name}`, "success");
    } catch (err) {
        if (String(err.message).includes("Session expired")) return;
        showToast("Network error placing order.", "danger");
    } finally {
        button.disabled = false;
        button.innerHTML = original;
    }
}

function showToast(message, kind) {
    // Minimal toast — Bootstrap's toast component without instantiating each.
    const colorClass = kind === "danger" ? "bg-danger" : "bg-success";
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast align-items-center text-white ${colorClass} border-0 show`;
    toast.role = "alert";
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${escapeHtml(message)}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto"
                    onclick="this.parentElement.parentElement.remove()"></button>
        </div>
    `;
    container.appendChild(toast);
    // Auto-dismiss
    setTimeout(() => {
        if (toast.parentElement) toast.remove();
    }, 3000);
}

document.addEventListener("DOMContentLoaded", () => {
    if (!window.CAFESYNC_MENU) {
        console.error("CAFESYNC_MENU is not defined. Check that menu.js loads before menu_app.js.");
        return;
    }
    renderTabs();
});
