function mountChart(id, config) {
  const element = document.getElementById(id);
  if (element) new Chart(element, config);
}

const palette = {
  excellent: "#1f6feb",
  good: "#1f8f4d",
  warning: "#f2c94c",
  danger: "#c92a2a",
  outOfPattern: "#ec4899",
  severe: "#8b1e1e",
  neutral: "#647386"
};

const categoryColors = {
  EXCELENTE: palette.excellent,
  BOM: palette.good,
  "ATEN\u00c7\u00c3O": palette.warning,
  "CR\u00cdTICO": palette.danger,
  "FORA DO PADR\u00c3O": palette.outOfPattern,
  "SEM DADOS": palette.neutral
};

const orderedCategories = [
  "EXCELENTE",
  "BOM",
  "ATEN\u00c7\u00c3O",
  "CR\u00cdTICO",
  "FORA DO PADR\u00c3O",
  "SEM DADOS"
];

function truncateLabel(value, maxLength = 28) {
  const text = String(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function criticalColor(rx) {
  if (rx === null || rx === undefined) return palette.neutral;
  if (rx <= -32) return palette.severe;
  if (rx <= -30) return palette.danger;
  return "#d97706";
}

function criticalDepth(rx) {
  if (rx === null || rx === undefined) return 0;
  return Math.max(0, Math.abs(rx) - 28);
}

const categoriaData = orderedCategories
  .filter((label) => Number(categorias[label] || 0) > 0)
  .map((label) => ({
    label,
    value: categorias[label],
    color: categoryColors[label] || palette.neutral
  }));

mountChart("categoriaChart", {
  type: "doughnut",
  data: {
    labels: categoriaData.map((item) => item.label),
    datasets: [{
      data: categoriaData.map((item) => item.value),
      backgroundColor: categoriaData.map((item) => item.color),
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

const criticosData = criticos
  .map((nome, index) => ({
    nome,
    login: criticosLogin[index] || "",
    rx: criticosRx[index],
    depth: criticalDepth(criticosRx[index])
  }))
  .sort((a, b) => b.depth - a.depth);

mountChart("criticosChart", {
  type: "bar",
  data: {
    labels: criticosData.map((item) => truncateLabel(item.nome)),
    datasets: [{
      label: "Abaixo do limite crítico",
      data: criticosData.map((item) => item.depth),
      backgroundColor: criticosData.map((item) => criticalColor(item.rx)),
      borderRadius: 6,
      barThickness: 10
    }]
  },
  options: {
    indexAxis: "y",
    maintainAspectRatio: false,
    layout: { padding: { right: 18 } },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => criticosData[items[0].dataIndex].nome,
          label: (context) => {
            const item = criticosData[context.dataIndex];
            const login = item.login ? ` • ${item.login}` : "";
            return `RX ${Number(item.rx).toFixed(2)} dBm${login}`;
          },
          afterLabel: (context) => {
            const item = criticosData[context.dataIndex];
            return `${item.depth.toFixed(2)} dB abaixo do limite crítico (-28 dBm)`;
          }
        }
      }
    },
    scales: {
      x: {
        beginAtZero: true,
        grid: { color: "#e7edf3" },
        title: { display: true, text: "dB abaixo de -28 dBm" },
        ticks: { precision: 0 }
      },
      y: {
        grid: { display: false },
        ticks: { autoSkip: false, color: "#4b5b6c", font: { size: 11 } }
      }
    }
  }
});
