let latencyChartInstance = null;

// Initialize the Chart.js Canvas
function initChart() {
    const ctx = document.getElementById('latencyChart').getContext('2d');
    
    // Create a sleek blue-to-transparent gradient
    let gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.5)'); // Tailwind Blue
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

    // Global Chart Defaults for Dark Mode
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
                tension: 0.4 // Makes the line smoothly curved
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
                y: { 
                    beginAtZero: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                },
                x: { 
                    grid: { display: false }
                }
            }
        }
    });
}

// Fetch aggregate metrics and update the top cards
async function fetchMetrics() {
    try {
        const response = await fetch('/telemetry/metrics');
        const data = await response.json();

        document.getElementById('metric-total-requests').innerText = data.total_requests;
        document.getElementById('metric-p95-latency').innerText = data.p95_latency_ms; // NEW
        document.getElementById('metric-avg-latency').innerText = data.average_latency_ms;
        document.getElementById('metric-error-count').innerText = data.error_count;
        
        const healthEl = document.getElementById('metric-system-health');
        const healthCard = document.getElementById('health-card');
        healthEl.innerText = data.system_health;

        if (data.system_health === "Degraded") {
            healthCard.classList.replace('metric-success', 'metric-warning');
            healthEl.classList.replace('text-success', 'text-warning');
        } else {
            healthCard.classList.replace('metric-warning', 'metric-success');
            healthEl.classList.replace('text-warning', 'text-success');
        }
    } catch (error) {
        console.error("Error fetching metrics:", error);
    }
}

// Fetch individual logs to populate the table and the chart
async function fetchLogs() {
    try {
        const response = await fetch('/telemetry/logs?limit=20');
        const logs = await response.json();
        
        // Reverse logs to show oldest to newest on the chart
        const chartLogs = [...logs].reverse(); 

        updateChart(chartLogs);
        updateTable(logs);

    } catch (error) {
        console.error("Error fetching logs:", error);
    }
}

function updateChart(logs) {
    if (!latencyChartInstance) return;

    const labels = logs.map(log => {
        const d = new Date(log.timestamp);
        return `${d.getHours()}:${d.getMinutes()}:${d.getSeconds()}`;
    });
    
    const dataPoints = logs.map(log => log.response_time_ms);

    latencyChartInstance.data.labels = labels;
    latencyChartInstance.data.datasets[0].data = dataPoints;
    latencyChartInstance.update();
}

function updateTable(logs) {
    const tbody = document.getElementById('log-table-body');
    tbody.innerHTML = ''; // Clear existing rows

    logs.forEach(log => {
        const tr = document.createElement('tr');
        
        // Color code status codes
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

// --- CafeSync Business Logic Simulators ---

async function placeOrder(itemName) {
    try {
        await fetch('/orders/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_name: itemName, quantity: 1 })
        });
        // Force an immediate refresh of both UI panels
        fetchOrders();
        fetchMetrics();
        fetchLogs();
    } catch (error) {
        console.error("Error placing order:", error);
    }
}

async function fetchOrders() {
    try {
        const response = await fetch('/orders/');
        const orders = await response.json();
        
        const tbody = document.getElementById('queue-table-body');
        tbody.innerHTML = ''; 

        // Show only the 5 most recent active orders
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
        await fetch(`/orders/${orderId}/complete`, { method: 'PUT' });
        fetchOrders();
        fetchMetrics();
        fetchLogs();
    } catch (error) {
        console.error("Error completing order:", error);
    }
}

async function simulatePeakHours() {
    const btn = document.getElementById('btn-stress-test');
    const indicator = document.getElementById('stress-indicator');
    
    // UI State: Disable button to prevent overlapping tests
    btn.disabled = true;
    btn.classList.add('btn-danger');
    btn.classList.remove('btn-outline-danger');
    indicator.style.display = 'block';

    const items = ['Espresso', 'Latte', 'Croissant', 'Americano', 'Mocha'];
    const promises = [];
    
    // Fire 50 concurrent requests
    for (let i = 0; i < 50; i++) {
        const randomItem = items[Math.floor(Math.random() * items.length)];
        promises.push(
            fetch('/orders/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_name: randomItem, quantity: 1 })
            })
        );
    }

    try {
        // Wait for all 50 requests to resolve
        await Promise.allSettled(promises);
        
        // Force immediate refresh of all metrics
        fetchOrders();
        fetchMetrics();
        fetchLogs();
    } catch (error) {
        console.error("Stress test encountered an error:", error);
    } finally {
        // Restore UI State
        btn.disabled = false;
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-outline-danger');
        indicator.style.display = 'none';
    }
}

// Boot sequence
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    
    // Initial fetch
    fetchMetrics();
    fetchLogs();
    fetchOrders();

    // Poll every 2 seconds
    setInterval(() => {
        fetchMetrics();
        fetchLogs();
        fetchOrders();
    }, 2000);
});