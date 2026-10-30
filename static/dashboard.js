// Draws the dashboard charts from window.CHARTS (rendered by Flask).
(function () {
  const C = window.CHARTS;
  if (!C || !window.Chart) return;
  Chart.defaults.font.family = '"Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';
  Chart.defaults.color = '#64708A';
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  const grid = { color: '#EEF1F6' };
  const base = { responsive: true, maintainAspectRatio: false };

  new Chart(document.getElementById('weekly'), {
    type: 'line',
    data: {
      labels: C.weekly.labels,
      datasets: [
        { label: 'Opened', data: C.weekly.created, borderColor: '#2F6FED', backgroundColor: 'rgba(47,111,237,.10)', fill: true, tension: .35, pointRadius: 3 },
        { label: 'Resolved', data: C.weekly.resolved, borderColor: '#1E8E5A', backgroundColor: 'transparent', tension: .35, pointRadius: 3 }
      ]
    },
    options: { ...base, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', align: 'end' } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid }, x: { grid: { display: false } } } }
  });

  new Chart(document.getElementById('priority'), {
    type: 'bar',
    data: { labels: C.priority.labels, datasets: [{ data: C.priority.data, backgroundColor: ['#9AA5BA', '#E4B100', '#E8730C', '#D93A3A'], borderRadius: 6, maxBarThickness: 46 }] },
    options: { ...base, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid }, x: { grid: { display: false } } } }
  });

  new Chart(document.getElementById('category'), {
    type: 'bar',
    data: { labels: C.category.labels, datasets: [{ data: C.category.data, backgroundColor: '#2F6FED', borderRadius: 6, maxBarThickness: 26 }] },
    options: { ...base, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 }, grid }, y: { grid: { display: false } } } }
  });

  new Chart(document.getElementById('status'), {
    type: 'doughnut',
    data: { labels: C.status.labels, datasets: [{ data: C.status.data, backgroundColor: ['#2F6FED', '#6B4FD3', '#E39B1F', '#1E8E5A', '#AAB3C5'], borderWidth: 2, borderColor: '#fff' }] },
    options: { ...base, cutout: '62%', plugins: { legend: { position: 'right' } } }
  });
})();
