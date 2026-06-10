function mountChart(id, config) {
  const element = document.getElementById(id);
  if (element) new Chart(element, config);
}

function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const palette = {
  excellent: themeColor("--chart-excellent"),
  good: themeColor("--chart-good"),
  warning: themeColor("--chart-warning"),
  danger: themeColor("--chart-danger"),
  outOfPattern: themeColor("--chart-outlier"),
  severe: themeColor("--chart-severe"),
  neutral: themeColor("--chart-muted"),
  grid: themeColor("--chart-grid"),
  text: themeColor("--chart-text"),
  muted: themeColor("--chart-muted"),
  panel: themeColor("--chart-surface")
};

const categoryColors = {
  EXCELENTE: palette.excellent,
  BOM: palette.good,
  ATENCAO: palette.warning,
  CRITICO: palette.danger,
  "FORA DO PADRAO": palette.outOfPattern,
  "SEM DADOS": palette.neutral
};

const orderedCategories = [
  "EXCELENTE",
  "BOM",
  "ATENCAO",
  "CRITICO",
  "FORA DO PADRAO",
  "SEM DADOS"
];

const categoryLabels = {
  EXCELENTE: "EXCELENTE",
  BOM: "BOM",
  ATENCAO: "ATENCAO",
  CRITICO: "CRITICO",
  "FORA DO PADRAO": "FORA DO PADRAO",
  "SEM DADOS": "SEM DADOS"
};

function truncateLabel(value, maxLength = 28) {
  const text = String(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

function criticalColor(rx) {
  if (rx === null || rx === undefined) return palette.neutral;
  if (rx <= -32) return palette.severe;
  if (rx <= -30) return palette.danger;
  return palette.warning;
}

function criticalDepth(rx) {
  if (rx === null || rx === undefined) return 0;
  return Math.max(0, Math.abs(rx) - 28);
}

function baseTooltip() {
  return {
    backgroundColor: palette.panel,
    borderColor: "rgba(148, 163, 184, 0.18)",
    borderWidth: 1,
    padding: 12,
    titleColor: palette.text,
    bodyColor: palette.muted,
    displayColors: false
  };
}

const categoriaData = orderedCategories
  .filter((label) => Number(categorias[label] || 0) > 0)
  .map((label) => ({
    label: categoryLabels[label] || label,
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
      borderColor: palette.panel,
      borderWidth: 4,
      hoverOffset: 8
    }]
  },
  options: {
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: "bottom",
        labels: {
          boxWidth: 12,
          usePointStyle: true,
          color: palette.text,
          padding: 18
        }
      },
      tooltip: {
        ...baseTooltip()
      }
    },
    cutout: "72%"
  }
});

const criticosData = criticos
  .map((nome, index) => ({
    nome,
    clienteId: criticosIds[index] || "",
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
      label: "Abaixo do limite critico",
      data: criticosData.map((item) => item.depth),
      backgroundColor: criticosData.map((item) => criticalColor(item.rx)),
      borderRadius: 999,
      borderSkipped: false,
      barThickness: 12
    }]
  },
  options: {
    indexAxis: "y",
    maintainAspectRatio: false,
    layout: { padding: { right: 18 } },
    onHover: (event, elements) => {
      event.native.target.style.cursor = elements.length ? "pointer" : "default";
    },
    onClick: (_, elements) => {
      if (!elements.length) return;
      const item = criticosData[elements[0].index];
      if (!item?.clienteId) return;
      const query = item.login ? `?login=${encodeURIComponent(item.login)}` : "";
      window.location.href = `/cliente/${encodeURIComponent(item.clienteId)}${query}`;
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        ...baseTooltip(),
        callbacks: {
          title: (items) => criticosData[items[0].dataIndex].nome,
          label: (context) => {
            const item = criticosData[context.dataIndex];
            const login = item.login ? ` | ${item.login}` : "";
            return `RX ${Number(item.rx).toFixed(2)} dBm${login}`;
          },
          afterLabel: (context) => {
            const item = criticosData[context.dataIndex];
            return `${item.depth.toFixed(2)} dB abaixo do limite critico (-28 dBm)`;
          }
        }
      }
    },
    scales: {
      x: {
        beginAtZero: true,
        grid: { color: palette.grid },
        title: { display: true, text: "dB abaixo de -28 dBm", color: palette.muted },
        ticks: { precision: 0, color: palette.muted }
      },
      y: {
        grid: { display: false },
        ticks: {
          autoSkip: false,
          color: palette.text,
          font: { size: 11 }
        }
      }
    }
  }
});
