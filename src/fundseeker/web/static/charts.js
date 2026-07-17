/** Common Chart.js helpers for FundSeeker similarity pages. */
(function (global) {
  "use strict";

  const COLORS = [
    "#ef4444", "#f97316", "#eab308", "#22c55e",
    "#3b82f6", "#8b5cf6", "#ec4899", "#06b6d4",
    "#84cc16", "#14b8a6", "#f43f5e", "#a855f7",
  ];

  const defaults = {
    responsive: true,
    maintainAspectRatio: false,
  };

  function colorAt(i, alpha) {
    const base = COLORS[i % COLORS.length];
    return alpha ? base + alpha : base;
  }

  function makeBarChart(ctx, labels, data, options) {
    options = options || {};
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: options.datasetLabel || "数值",
          data: data,
          backgroundColor: data.map((_, i) => colorAt(i, "aa")),
          borderColor: data.map((_, i) => colorAt(i)),
          borderWidth: 1,
        }],
      },
      options: Object.assign({}, defaults, options.chartOptions || {}),
    });
  }

  function makeDoughnutChart(ctx, labels, data, options) {
    options = options || {};
    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: data.map((_, i) => colorAt(i, "cc")),
          borderColor: "#fff",
          borderWidth: 1,
        }],
      },
      options: Object.assign({}, defaults, {
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } },
        },
      }, options.chartOptions || {}),
    });
  }

  function makeLineChart(ctx, labels, datasets, options) {
    options = options || {};
    return new Chart(ctx, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: Object.assign({}, defaults, {
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "bottom",
            labels: { boxWidth: 12, font: { size: 10 }, usePointStyle: true },
          },
        },
        scales: {
          x: { ticks: { font: { size: 9 }, maxTicksLimit: 10 } },
          y: { ticks: { font: { size: 10 } } },
        },
      }, options.chartOptions || {}),
    });
  }

  global.FundSeekerCharts = {
    COLORS: COLORS,
    colorAt: colorAt,
    makeBarChart: makeBarChart,
    makeDoughnutChart: makeDoughnutChart,
    makeLineChart: makeLineChart,
  };
})(window);
