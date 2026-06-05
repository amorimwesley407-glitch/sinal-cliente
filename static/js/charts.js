function mountChart(id, config) {
  const element = document.getElementById(id);
  if (element) new Chart(element, config);
}

const palette = {
  excellent: "#1f6feb",
  good: "#1f8f4d",
  warning: "#b7791f",
  danger: "#c92a2a",
  neutral: "#647386"
};

mountChart("categoriaChart", {
  type: "doughnut",
  data: {
    labels: Object.keys(categorias),
    datasets: [{
      data: Object.values(categorias),
      backgroundColor: [palette.neutral, palette.danger, palette.warning, palette.good, palette.excellent],
      borderWidth: 0
    }]
  },
  options: {
    maintainAspectRatio: false,
    plugins: {
      legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } }
    },
    cutout: "68%"
  }
});

mountChart("criticosChart", {
  type: "bar",
  data: {
    labels: criticos,
    datasets: [{ label: "RX", data: criticosRx, backgroundColor: palette.danger, borderRadius: 4 }]
  },
  options: {
    indexAxis: "y",
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: "#e7edf3" } },
      y: { grid: { display: false }, ticks: { autoSkip: false } }
    }
  }
});
