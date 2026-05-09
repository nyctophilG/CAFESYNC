// Barista dashboard — minimal JS, only the orders panel.
// Stripped down from app.js since baristas have no telemetry or user-mgmt access.

async function authedFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('Session expired');
    }
    return response;
}

async function placeOrder(itemName) {
    try {
        await authedFetch('/orders/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_name: itemName, quantity: 1 })
        });
        fetchOrders();
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
        const activeOrders = orders.filter(o => !o.is_completed).slice(0, 10);
        if (activeOrders.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted py-4">No pending orders</td></tr>`;
            return;
        }
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
        fetchOrders();
    } catch (error) {
        console.error("Error completing order:", error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    fetchOrders();
    setInterval(fetchOrders, 3000);
});
