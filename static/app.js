let latencyChartInstance = null;

// Initialize the Chart.js Canvas
function initChart() {
    const ctx = document.getElementById('latencyChart').getContext('2d');
    latencyChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Response Time (ms)',
                data: [],
                borderColor: 'rgba(75, 192, 192, 1)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderWidth: 2,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: { beginAtZero: true }
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
        document.getElementById('metric-avg-latency').innerText = data.average_latency_ms;
        document.getElementById('metric-error-count').innerText = data.error_count;
        
        const healthEl = document.getElementById('metric-system-health');
        const healthCard = document.getElementById('health-card');
        healthEl.innerText = data.system_health;

        // Visual indicator for degraded health
        if (data.system_health === "Degraded") {
            healthCard.classList.replace('bg-success', 'bg-warning');
        } else {
            healthCard.classList.replace('bg-warning', 'bg-success');
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

// Boot sequence
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    
    // Initial fetch
    fetchMetrics();
    fetchLogs();

    // Poll every 2 seconds
    setInterval(() => {
        fetchMetrics();
        fetchLogs();
    }, 2000);
});