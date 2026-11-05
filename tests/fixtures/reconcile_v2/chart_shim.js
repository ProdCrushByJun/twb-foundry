// Offline stand-in for Chart.js 4 (decisions/058): tests run without network, and the real library was not fetched
// into the repository. It has the public surface tbuilder/outline.js reads from a real Chart.js 4 instance:
// new Chart(canvas | ctx, {type, data: {labels, datasets: [{label, data}]}, options: {plugins: {title}}}),
// Chart.getChart(canvas), Chart.instances, chart.canvas / .config / .data / .options, chart.update(), destroy().
// Drawing is a plain bar / line sketch: like a real canvas chart, no number reaches the DOM.
(function () {
  let next = 0;
  const COLORS = ["#4e79a7", "#f28e2b", "#76b7b2", "#e15759"];
  class Chart {
    constructor(item, config) {
      this.canvas = item.canvas || item;
      this.ctx = this.canvas.getContext("2d");
      this.config = config;
      this.id = next++;
      Chart.instances[this.id] = this;
      this.update();
    }
    get data() { return this.config.data; }
    set data(d) { this.config.data = d; }
    get options() { return this.config.options || {}; }
    update() {
      const { width: W, height: H } = this.canvas, c = this.ctx, d = this.config.data;
      c.clearRect(0, 0, W, H);
      const all = d.datasets.flatMap((s) => s.data), max = Math.max(1, ...all), n = d.labels.length;
      d.datasets.forEach((s, j) => {
        c.fillStyle = c.strokeStyle = COLORS[j % COLORS.length];
        if (this.config.type === "line") {
          c.beginPath();
          s.data.forEach((v, i) => c.lineTo((i + 0.5) * W / n, H - v / max * (H - 10)));
          c.stroke();
        } else {
          const bw = W / n / (d.datasets.length + 1);
          s.data.forEach((v, i) => c.fillRect(i * W / n + j * bw, H - v / max * (H - 10), bw, v / max * (H - 10)));
        }
      });
    }
    destroy() { delete Chart.instances[this.id]; }
    static getChart(canvas) { return Object.values(Chart.instances).find((i) => i.canvas === canvas); }
  }
  Chart.instances = {};
  window.Chart = Chart;
})();
