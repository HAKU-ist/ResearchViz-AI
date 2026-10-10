"use client";

import Image from "next/image";
import { FormEvent, KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, memo, useCallback, useEffect, useRef, useState } from "react";

const API_V1 = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const API_V2 = API_V1.replace(/\/api\/v1\/?$/, "/api/v2");

type Column = { name: string; semantic_type: string; physical_type: string; null_ratio: number };
type ExperimentSchema = {
  experiment_type: string;
  datasets: string[];
  summary?: string;
  row_meaning?: string;
  column_meanings?: { column: string; meaning: string; role: string; confidence: number }[];
  methods: { column: string | null; values: string[]; confidence: number };
  metrics: { name: string; column: string; direction: string; confidence: number }[];
  variables: { name: string; column: string; role: string; ordered: boolean; confidence: number }[];
  repeat_column: string | null;
  warnings: string[];
};
type Experiment = {
  id: string; name: string; description: string; filename: string; status: string;
  profile: { row_count: number; column_count: number; columns: Column[]; warnings: string[] };
  schema: ExperimentSchema;
  experiment_schema: ExperimentSchema;
};
type KnowledgeItem = {
  id: string; name: string; description: string; filename: string; status: string;
  indexed: number;
  datasets: string[]; methods: string[];
  dataset_variant_count: number; method_variant_count: number; observation_count: number;
};
type KnowledgeDetail = { experiment: Omit<Experiment, "experiment_schema"> & { experiment_schema?: ExperimentSchema } };
type CanvasObject = {
  id: string; kind: "plot" | "text" | "legend" | "series";
  x: number; y: number; width: number; height: number; base_width: number; base_height: number;
  rotation: number; visible: boolean; locked: boolean;
};
type ChartStyle = {
  figure_width: number; figure_height: number; font_size: number; title_size: number;
  line_width: number; marker: string; palette: string[]; background_color: string;
  grid: boolean; legend_position: string; legend_x?: number | null; legend_y?: number | null; x_tick_rotation: number; bar_width: number;
  canvas_objects: CanvasObject[];
};
type ChartSpec = { chart_type: string; x: string; y: string; group: string | null; title: string; x_label: string; y_label: string; dpi: number; style?: ChartStyle };
type Visualization = {
  id: string; status: string; spec: { chart: ChartSpec; rationale: string; assumptions: string[] };
  sources?: { id: string; name: string; filename: string }[];
  source_selection?: { experiment_ids: string[]; rationale: string };
  source_tool_trace?: { round: number; tool: string; result_count?: number }[];
  agent_trace?: { round: number; tool: string; result_count?: number; result_status?: string; valid?: boolean; error?: string }[];
  token_usage?: { input_tokens: number; output_tokens: number; total_tokens: number; api_calls: number; by_endpoint: Record<string, number> };
  svg_path?: string;
};

const DEFAULT_STYLE: ChartStyle = {
  figure_width: 7.2, figure_height: 4.8, font_size: 11, title_size: 14,
  line_width: 2, marker: "o", palette: ["#126149", "#d28b36", "#5378a5", "#a65353", "#7b62a3"],
  background_color: "#ffffff", grid: true, legend_position: "best", x_tick_rotation: 0, bar_width: 0.82,
  canvas_objects: [],
};

const EditableSvg = memo(function EditableSvg({ markup }: { markup: string }) {
  return <div className="svg-surface" dangerouslySetInnerHTML={{ __html: markup }} />;
});

function canvasDraft(chart: ChartSpec) {
  return { ...DEFAULT_STYLE, ...(chart.style ?? {}), title: chart.title, x_label: chart.x_label, y_label: chart.y_label, dpi: chart.dpi };
}

function methodDisplay(experiment: Experiment) {
  const schema = experiment.experiment_schema;
  if (schema.methods.column) return schema.methods.column;
  if (schema.methods.values.length) return `宽表 · ${schema.methods.values.length} 个方法`;
  return "未检测到";
}

function repeatDisplay(experiment: Experiment) {
  return experiment.experiment_schema.repeat_column ?? "无重复实验列";
}

function confidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

const roleLabels: Record<string, string> = {
  metric: "结果指标",
  independent_variable: "实验条件",
  control_variable: "控制变量",
  method: "方法字段",
  dataset: "数据集字段",
  repeat: "重复实验",
  identifier: "标识字段",
  metadata: "元数据",
  unknown: "含义待确认",
};

async function errorMessage(response: Response) {
  try { const body = await response.json(); return body.detail ?? "请求失败"; }
  catch { return `请求失败 (${response.status})`; }
}

export default function Home() {
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeBusy, setKnowledgeBusy] = useState(true);
  const [visualization, setVisualization] = useState<Visualization | null>(null);
  const [busy, setBusy] = useState<"upload" | "select" | "visualize" | "style" | "demo" | null>(null);
  const [error, setError] = useState("");
  const [request, setRequest] = useState("生成不同方法 accuracy 随 budget 变化曲线");
  const [styleDraft, setStyleDraft] = useState<(ChartStyle & { title: string; x_label: string; y_label: string; dpi: number }) | null>(null);
  const [renderRevision, setRenderRevision] = useState(0);
  const [svgMarkup, setSvgMarkup] = useState("");
  const [svgEditor, setSvgEditor] = useState<{ field: "title" | "x_label" | "y_label"; x: number; y: number } | null>(null);
  const [seriesEditor, setSeriesEditor] = useState<{ index: number; x: number; y: number } | null>(null);
  const [canvasObjects, setCanvasObjects] = useState<CanvasObject[]>([]);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [undoStack, setUndoStack] = useState<CanvasObject[][]>([]);
  const [redoStack, setRedoStack] = useState<CanvasObject[][]>([]);
  const canvasPaperRef = useRef<HTMLDivElement>(null);
  const imageUrl = visualization ? `${API_V1}/visualizations/${visualization.id}/image?v=${renderRevision}` : "";
  const chart = visualization?.spec.chart;
  const selectedCanvasObject = canvasObjects.find(item => item.id === selectedObjectId) ?? null;

  const loadKnowledge = useCallback(async (query = "") => {
    setKnowledgeBusy(true);
    try {
      const suffix = query.trim() ? `?query=${encodeURIComponent(query.trim())}` : "";
      const response = await fetch(`${API_V2}/knowledge${suffix}`);
      if (!response.ok) throw new Error(await errorMessage(response));
      setKnowledgeItems(await response.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "知识库加载失败");
    } finally {
      setKnowledgeBusy(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${API_V2}/knowledge`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(await errorMessage(response));
        return response.json();
      })
      .then(items => setKnowledgeItems(items))
      .catch(cause => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "知识库加载失败");
      })
      .finally(() => setKnowledgeBusy(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!visualization) return;
    const controller = new AbortController();
    void fetch(`${API_V1}/visualizations/${visualization.id}/svg?v=${renderRevision}`, { signal: controller.signal })
      .then(response => response.ok ? response.text() : Promise.reject(new Error("SVG 不存在")))
      .then(setSvgMarkup)
      .catch(cause => { if (!(cause instanceof DOMException && cause.name === "AbortError")) setSvgMarkup(""); });
    return () => controller.abort();
  }, [visualization, renderRevision]);

  useEffect(() => {
    if (!svgMarkup || !canvasPaperRef.current) return;
    const frame = requestAnimationFrame(() => {
      const canvas = canvasPaperRef.current;
      if (!canvas) return;
      const bounds = canvas.getBoundingClientRect();
      const plotRoot = canvas.querySelector("#plot-area");
      const figureRoot = plotRoot?.parentElement;
      if (plotRoot && figureRoot) {
        ["chart-title", "x-axis-label", "y-axis-label", "chart-legend"].forEach(id => {
          const object = canvas.querySelector(`#${id}`);
          if (object && plotRoot.contains(object)) figureRoot.appendChild(object);
        });
      }
      const definitions: { id: string; kind: CanvasObject["kind"] }[] = [
        { id: "plot-area", kind: "plot" }, { id: "chart-title", kind: "text" },
        { id: "x-axis-label", kind: "text" }, { id: "y-axis-label", kind: "text" },
        { id: "chart-legend", kind: "legend" },
      ];
      const measured = definitions.flatMap(({ id, kind }) => {
        const root = canvas.querySelector(`#${id}`);
        if (!root) return [];
        const target = id === "plot-area" ? root.querySelector(':scope > g[id^="patch_"]') ?? root : root;
        const rect = target.getBoundingClientRect();
        const width = Math.max(.02, rect.width / bounds.width);
        const height = Math.max(.02, rect.height / bounds.height);
        const item: CanvasObject = { id, kind, x: (rect.left - bounds.left) / bounds.width, y: (rect.top - bounds.top) / bounds.height,
          width, height, base_width: width, base_height: height, rotation: 0, visible: true, locked: false };
        root.setAttribute("data-canvas-base", JSON.stringify({ x: item.x, y: item.y, width, height }));
        return [item];
      });
      setCanvasObjects(measured);
      setStyleDraft(current => current ? { ...current, canvas_objects: measured } : current);
      setSelectedObjectId(null); setUndoStack([]); setRedoStack([]);
    });
    return () => cancelAnimationFrame(frame);
  }, [svgMarkup]);

  async function searchKnowledge(event: FormEvent) {
    event.preventDefault(); setError("");
    await loadKnowledge(knowledgeQuery);
  }

  async function selectKnowledge(id: string) {
    setBusy("select"); setError(""); setVisualization(null);
    try {
      const response = await fetch(`${API_V2}/knowledge/${id}`);
      if (!response.ok) throw new Error(await errorMessage(response));
      const detail: KnowledgeDetail = await response.json();
      const source = detail.experiment;
      setExperiment({ ...source, experiment_schema: source.experiment_schema ?? source.schema });
    } catch (e) { setError(e instanceof Error ? e.message : "知识项加载失败"); }
    finally { setBusy(null); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("upload"); setError(""); setVisualization(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const response = await fetch(`${API_V2}/knowledge`, { method: "POST", body: form });
      if (!response.ok) throw new Error(await errorMessage(response));
      setExperiment(await response.json());
      formElement.reset();
      await loadKnowledge();
    } catch (e) { setError(e instanceof Error ? e.message : "上传失败"); }
    finally { setBusy(null); }
  }

  async function visualize(event: FormEvent) {
    event.preventDefault();
    setBusy("visualize"); setError("");
    try {
      const response = await fetch(`${API_V2}/visualizations`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const generated: Visualization = await response.json();
      setVisualization(generated);
      setStyleDraft(canvasDraft(generated.spec.chart));
      setRenderRevision(0);
    } catch (e) { setError(e instanceof Error ? e.message : "生成失败"); }
    finally { setBusy(null); }
  }

  async function loadCanvasDemo() {
    setBusy("demo"); setError("");
    try {
      const response = await fetch(`${API_V2}/visualizations/demo`, { method: "POST" });
      if (!response.ok) throw new Error(await errorMessage(response));
      const generated: Visualization = await response.json();
      setVisualization(generated);
      setStyleDraft(canvasDraft(generated.spec.chart));
      setRenderRevision(0);
    } catch (e) { setError(e instanceof Error ? e.message : "零 Token 示例生成失败"); }
    finally { setBusy(null); }
  }

  function syncCanvasObjects(objects: CanvasObject[]) {
    setCanvasObjects(objects);
    setStyleDraft(current => current ? { ...current, canvas_objects: objects } : current);
  }

  function applyCanvasObjectTransforms(objects: CanvasObject[]) {
    const canvas = canvasPaperRef.current;
    if (!canvas) return;
    const bounds = canvas.getBoundingClientRect();
    objects.forEach(item => {
      const element = canvas.querySelector(`#${item.id}`) as HTMLElement | SVGElement | null;
      if (!element) return;
      element.style.display = item.visible ? "" : "none";
      const stored = element.getAttribute("data-canvas-base");
      let base = stored ? JSON.parse(stored) as { x: number; y: number; width: number; height: number } : null;
      if (!base) {
        const rect = element.getBoundingClientRect();
        base = { x: (rect.left - bounds.left) / bounds.width, y: (rect.top - bounds.top) / bounds.height,
          width: item.base_width, height: item.base_height };
        element.setAttribute("data-canvas-base", JSON.stringify(base));
      }
      const translateX = (item.x - base.x) * bounds.width;
      const translateY = (item.y - base.y) * bounds.height;
      element.style.transformBox = "fill-box";
      element.style.transformOrigin = "center";
      element.style.transform = `translate(${translateX}px, ${translateY}px) rotate(${item.rotation}deg) scale(${item.width / base.width}, ${item.height / base.height})`;
    });
  }

  useEffect(() => {
    applyCanvasObjectTransforms(canvasObjects);
  }, [canvasObjects]);

  function pushHistory(snapshot = canvasObjects) {
    setUndoStack(stack => [...stack.slice(-29), snapshot.map(item => ({ ...item }))]);
    setRedoStack([]);
  }

  function restoreObjects(objects: CanvasObject[]) {
    syncCanvasObjects(objects.map(item => ({ ...item })));
  }

  function undoCanvas() {
    const previous = undoStack.at(-1); if (!previous) return;
    setRedoStack(stack => [...stack, canvasObjects.map(item => ({ ...item }))]);
    setUndoStack(stack => stack.slice(0, -1)); restoreObjects(previous);
  }

  function redoCanvas() {
    const next = redoStack.at(-1); if (!next) return;
    setUndoStack(stack => [...stack, canvasObjects.map(item => ({ ...item }))]);
    setRedoStack(stack => stack.slice(0, -1)); restoreObjects(next);
  }

  function beginObjectTransform(event: ReactPointerEvent, mode: "move" | "resize" | "rotate", handle = "se", objectId = selectedObjectId) {
    if (!objectId || !canvasPaperRef.current) return;
    const selected = canvasObjects.find(item => item.id === objectId);
    if (!selected || selected.locked) return;
    event.preventDefault(); event.stopPropagation(); pushHistory();
    const bounds = canvasPaperRef.current.getBoundingClientRect();
    const start = { x: event.clientX, y: event.clientY, object: { ...selected } };
    const center = { x: bounds.left + (selected.x + selected.width / 2) * bounds.width, y: bounds.top + (selected.y + selected.height / 2) * bounds.height };
    const startAngle = Math.atan2(event.clientY - center.y, event.clientX - center.x) * 180 / Math.PI;
    const move = (pointer: PointerEvent) => {
      const dx = (pointer.clientX - start.x) / bounds.width;
      const dy = (pointer.clientY - start.y) / bounds.height;
      const changed = { ...start.object };
      if (mode === "move") { changed.x += dx; changed.y += dy; }
      if (mode === "rotate") {
        const angle = Math.atan2(pointer.clientY - center.y, pointer.clientX - center.x) * 180 / Math.PI;
        changed.rotation = Math.max(-180, Math.min(180, start.object.rotation + angle - startAngle));
      }
      if (mode === "resize") {
        const min = .018;
        if (handle.includes("e")) changed.width = Math.max(min, start.object.width + dx);
        if (handle.includes("s")) changed.height = Math.max(min, start.object.height + dy);
        if (handle.includes("w")) { const width = Math.max(min, start.object.width - dx); changed.x = start.object.x + start.object.width - width; changed.width = width; }
        if (handle.includes("n")) { const height = Math.max(min, start.object.height - dy); changed.y = start.object.y + start.object.height - height; changed.height = height; }
      }
      syncCanvasObjects(canvasObjects.map(item => item.id === objectId ? changed : item));
    };
    const stop = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", stop);
  }

  function handleSvgClick(event: ReactMouseEvent<HTMLDivElement>) {
    if (!styleDraft || !canvasPaperRef.current) return;
    const target = event.target as Element;
    const rect = canvasPaperRef.current.getBoundingClientRect();
    const position = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    const series = target.closest('[id^="series-"], [id^="legend-series-"]');
    if (series) {
      const index = Number(series.id.replace("legend-series-", "").replace("series-", "")) || 0;
      setSeriesEditor({ index, ...position }); setSvgEditor(null); setSelectedObjectId(null); return;
    }
    const legacyLegend = target.closest("#chart-legend > g");
    if (legacyLegend?.querySelector("path")) {
      const handles = [...canvasPaperRef.current.querySelectorAll("#chart-legend > g")].filter(group => group.querySelector("path"));
      const index = handles.indexOf(legacyLegend);
      if (index >= 0) { setSeriesEditor({ index, ...position }); setSvgEditor(null); setSelectedObjectId(null); return; }
    }
    for (const item of [...canvasObjects].sort(item => item.id === "plot-area" ? 1 : -1)) {
      if (target.closest(`#${item.id}`)) {
        setSelectedObjectId(item.id); setSeriesEditor(null); return;
      }
    }
    setSelectedObjectId(null); setSeriesEditor(null); setSvgEditor(null);
  }

  function handleSvgDoubleClick(event: ReactMouseEvent<HTMLDivElement>) {
    if (!canvasPaperRef.current) return;
    const target = event.target as Element;
    const rect = canvasPaperRef.current.getBoundingClientRect();
    const fields: [string, "title" | "x_label" | "y_label"][] = [["chart-title", "title"], ["x-axis-label", "x_label"], ["y-axis-label", "y_label"]];
    for (const [id, field] of fields) if (target.closest(`#${id}`)) {
      setSvgEditor({ field, x: event.clientX - rect.left, y: event.clientY - rect.top }); return;
    }
  }

  function updateSvgText(field: "title" | "x_label" | "y_label", value: string) {
    if (!styleDraft || !canvasPaperRef.current) return;
    setStyleDraft({ ...styleDraft, [field]: value });
    const id = { title: "chart-title", x_label: "x-axis-label", y_label: "y-axis-label" }[field];
    const text = canvasPaperRef.current.querySelector(`#${id} text`);
    if (text) text.textContent = value;
  }

  function updateSeriesColor(index: number, color: string) {
    if (!styleDraft || !canvasPaperRef.current) return;
    const palette = [...styleDraft.palette];
    while (palette.length <= index) palette.push("#126149");
    palette[index] = color;
    setStyleDraft({ ...styleDraft, palette });
    const explicit = [...canvasPaperRef.current.querySelectorAll(`#series-${index}, #legend-series-${index}`)];
    const legacyLegend = [...canvasPaperRef.current.querySelectorAll("#chart-legend > g")].filter(group => group.querySelector("path"))[index];
    const targets = legacyLegend ? [...explicit, legacyLegend] : explicit;
    targets.forEach(series => {
      [series, ...series.querySelectorAll("*")].forEach(element => {
        const svg = element as SVGElement;
        const inline = element.getAttribute("style") ?? "";
        const stroke = element.getAttribute("stroke");
        const fill = element.getAttribute("fill");
        if ((/stroke\s*:/.test(inline) && !/stroke\s*:\s*none/.test(inline)) || (stroke && stroke !== "none")) {
          svg.style.stroke = color; element.setAttribute("stroke", color);
        }
        if ((/fill\s*:/.test(inline) && !/fill\s*:\s*none/.test(inline)) || (fill && fill !== "none")) {
          svg.style.fill = color; element.setAttribute("fill", color);
        }
      });
    });
  }

  function handleSvgPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const target = event.target as Element;
    if (target.closest(".canvas-selection") || target.closest('[id^="series-"], [id^="legend-series-"]')) return;
    const hit = [...canvasObjects].sort(item => item.id === "plot-area" ? 1 : -1).find(item => target.closest(`#${item.id}`));
    if (hit) { setSelectedObjectId(hit.id); beginObjectTransform(event, "move", "se", hit.id); }
  }

  function changeCanvasObject(id: string, change: Partial<CanvasObject>) {
    pushHistory(); syncCanvasObjects(canvasObjects.map(item => item.id === id ? { ...item, ...change } : item));
  }

  function alignSelected(axis: "horizontal" | "vertical") {
    const item = canvasObjects.find(object => object.id === selectedObjectId); if (!item) return;
    changeCanvasObject(item.id, axis === "horizontal" ? { x: .5 - item.width / 2 } : { y: .5 - item.height / 2 });
  }

  function handleCanvasKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const item = canvasObjects.find(object => object.id === selectedObjectId); if (!item || item.locked) return;
    const direction: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (!direction[event.key]) return; event.preventDefault(); pushHistory();
    const [x, y] = direction[event.key]; const step = event.shiftKey ? .015 : .003;
    syncCanvasObjects(canvasObjects.map(object => object.id === item.id ? { ...object, x: object.x + x * step, y: object.y + y * step } : object));
  }

  function startCanvasResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!styleDraft || !canvasPaperRef.current) return;
    event.preventDefault();
    const startX = event.clientX, startY = event.clientY;
    const startWidth = styleDraft.figure_width, startHeight = styleDraft.figure_height;
    const move = (pointer: PointerEvent) => setStyleDraft(current => current ? {
      ...current,
      figure_width: Math.max(4, Math.min(20, Math.round((startWidth + (pointer.clientX - startX) / 70) * 10) / 10)),
      figure_height: Math.max(3, Math.min(15, Math.round((startHeight + (pointer.clientY - startY) / 70) * 10) / 10)),
    } : current);
    const stop = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", stop);
  }

  async function applyCanvasStyle() {
    if (!visualization || !styleDraft) return;
    setBusy("style"); setError("");
    const { title, x_label, y_label, dpi, ...style } = styleDraft;
    try {
      const response = await fetch(`${API_V2}/visualizations/${visualization.id}/style`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, x_label, y_label, dpi, style }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const updated = await response.json();
      setVisualization(current => current ? { ...current, ...updated } : updated);
      setStyleDraft(canvasDraft(updated.spec.chart));
      setRenderRevision(value => value + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "画布重新渲染失败"); }
    finally { setBusy(null); }
  }

  return (
    <main>
      <header className="topbar">
        <div className="brand"><span className="mark">R</span><span>ResearchViz AI</span></div>
        <div className="status"><span className="dot" /> Version 2 · Knowledge Base</div>
      </header>

      <section className="hero">
        <p className="eyebrow">MACHINE LEARNING EXPERIMENT STUDIO</p>
        <h1>Turn raw results into<br/><em>publication-ready figures.</em></h1>
        <p className="lead">直接描述你想看的结果，Agent 会自主检索并组合知识库中的实验数据；也可以导入新的 CSV，持续扩充知识库。</p>
      </section>

      <section className="workspace">
        <aside className="panel knowledge-panel">
          <div className="step"><span>01</span> Knowledge base</div>
          <form onSubmit={searchKnowledge} className="knowledge-search">
            <input value={knowledgeQuery} onChange={event => setKnowledgeQuery(event.target.value)} placeholder="搜索数据集、方法或指标" />
            <button disabled={knowledgeBusy} aria-label="搜索知识库">⌕</button>
          </form>

          <div className="knowledge-list" aria-live="polite">
            {knowledgeBusy ? <p className="knowledge-state">正在读取知识库…</p> : knowledgeItems.length === 0 ? (
              <p className="knowledge-state">没有找到知识项，可以在下方导入 CSV。</p>
            ) : knowledgeItems.map(item => (
              <button
                type="button"
                className={`knowledge-card ${experiment?.id === item.id ? "selected" : ""}`}
                key={item.id}
                onClick={() => void selectKnowledge(item.id)}
                disabled={!!busy}
              >
                <span className="knowledge-card-head"><b>{item.name}</b><small>{item.indexed ? "已索引" : "待索引"}</small></span>
                <span className="knowledge-description">{item.description}</span>
                <span className="knowledge-datasets">
                  <small>DATASET</small>
                  <span>{item.datasets.length ? item.datasets.map(dataset => <em key={dataset}>{dataset}</em>) : <em>Unknown</em>}</span>
                </span>
                <span className="knowledge-methods">
                  <small>METHODS · {item.methods.length}</small>
                  <span className="knowledge-method-list">
                    {item.methods.length ? item.methods.slice(0, 6).map(method => <span className="knowledge-method" key={method}><i />{method}</span>) : <span className="knowledge-method muted">未识别到方法</span>}
                    {item.methods.length > 6 && <span className="knowledge-method more">另有 {item.methods.length - 6} 种设置</span>}
                  </span>
                </span>
                <span className="knowledge-stats">
                  <small>{item.dataset_variant_count} 数据设置</small>
                  <small>{item.observation_count} 观测</small>
                </span>
              </button>
            ))}
          </div>

          <details className="knowledge-import">
            <summary>导入新的实验 CSV</summary>
            <form onSubmit={upload}>
              <label>实验名称<input name="name" required placeholder="CIFAR10 Active Learning" /></label>
              <label>实验描述<textarea name="description" required rows={4} placeholder="这是 CIFAR10 主动学习实验，比较不同 query strategy..." /></label>
              <label className="dropzone">
                <span className="upload-icon">↑</span>
                <b>选择 CSV 文件</b><small>最大 100 MB · UTF-8 / GB18030</small>
                <input name="file" type="file" accept=".csv,text/csv" required />
              </label>
              <button disabled={!!busy}>{busy === "upload" ? "正在导入知识库…" : "导入知识库"}<span>→</span></button>
            </form>
          </details>
          {error && <div className="error">{error}</div>}
        </aside>

        <div className="main-column">
          <section className={`panel schema-panel ${!experiment ? "empty" : ""}`}>
            <div className="step"><span>02</span> Knowledge inspector</div>
            {!experiment ? <div className="empty-state"><div className="schema-glyph">{`{ }`}</div><p>这里可以查看单个知识项的模型理解，但不会限制 Agent 的自动选源范围。</p></div> : <>
              <div className="summary-head"><div><h2>{experiment.name}</h2><p>{experiment.filename} · 模型实验理解结果</p></div><span className="ready">Understood</span></div>
              <p className="success-note">实验理解完成。以下内容来自 Experiment Understanding Skill 的模型输出。</p>
              {experiment.experiment_schema.summary && <p className="natural-summary">{experiment.experiment_schema.summary}</p>}
              <div className="chips">
                <div><small>EXPERIMENT</small><b>{experiment.experiment_schema.experiment_type}</b></div>
                <div><small>DATASET</small><b>{experiment.experiment_schema.datasets.join(", ") || "Unknown"}</b></div>
                <div><small>METHOD</small><b>{methodDisplay(experiment)}</b></div>
                <div><small>REPEAT</small><b>{repeatDisplay(experiment)}</b></div>
              </div>

              <div className="understanding-grid">
                <details className="understanding-disclosure" open>
                  <summary>
                    <span className="disclosure-icon">↳</span>
                    <span className="disclosure-heading"><b>每一行代表什么</b><small>ROW SEMANTICS</small></span>
                    <span className="disclosure-action"><i /> <em>展开 / 收起</em></span>
                  </summary>
                  <div className="disclosure-content row-content">
                    <p className="meaning-copy">{experiment.experiment_schema.row_meaning || "模型暂未提供行级语义说明。"}</p>
                  </div>
                </details>

                <details className="understanding-disclosure">
                  <summary>
                    <span className="disclosure-icon">#</span>
                    <span className="disclosure-heading"><b>每一列代表什么</b><small>COLUMN SEMANTICS</small></span>
                    <span className="disclosure-action"><strong>{experiment.profile.column_count} 列</strong><i /> <em>展开 / 收起</em></span>
                  </summary>
                  <div className="disclosure-content">
                    {(experiment.experiment_schema.column_meanings?.length ?? 0) > 0 ? <div className="column-meaning-list">
                      {experiment.experiment_schema.column_meanings!.map((item, index) => <article className="column-meaning" key={item.column}>
                        <span className="column-index">{String(index + 1).padStart(2, "0")}</span>
                        <div className="column-body">
                          <div className="column-heading"><code>{item.column}</code><span>{roleLabels[item.role] ?? item.role}</span><small>{confidence(item.confidence)}</small></div>
                          <p>{item.meaning}</p>
                        </div>
                      </article>)}
                    </div> : <p className="muted-copy">当前记录来自旧版 Schema，请重新上传 CSV 生成逐列自然语言说明。</p>}
                  </div>
                </details>

                <section className="understanding-block">
                  <div className="understanding-title"><span>识别到的方法</span><small>CONFIDENCE {confidence(experiment.experiment_schema.methods.confidence)}</small></div>
                  {experiment.experiment_schema.methods.values.length > 0 ? <div className="value-list">{experiment.experiment_schema.methods.values.map(value => <code key={value}>{value}</code>)}</div> : <p className="muted-copy">模型未识别到明确的方法取值。</p>}
                </section>
              </div>

              {experiment.experiment_schema.warnings.length > 0 && <div className="schema-warnings"><b>模型提示</b>{experiment.experiment_schema.warnings.map(warning => <p key={warning}>{warning}</p>)}</div>}
            </>}
          </section>

          <section className="panel agent-panel">
            <div className="step"><span>03</span> Visualization agent · Auto source selection</div>
            <p className="agent-hint">无需选择表格。Agent 会根据需求检索数据集、方法、指标和实验设置，并自动合并匹配的知识项。</p>
            <button type="button" className="demo-button" onClick={() => void loadCanvasDemo()} disabled={!!busy}><span>不调用模型，直接测试画布</span><small>{busy === "demo" ? "正在生成…" : "0 TOKEN"}</small></button>
            <form onSubmit={visualize} className="prompt-form"><textarea value={request} onChange={e => setRequest(e.target.value)} rows={2} /><button disabled={!!busy}>{busy === "visualize" ? "Agent 正在生成…" : "生成图表"}<span>✦</span></button></form>
            {visualization && <div className="result">
              <div className="figure-card"><div className="figure-top"><span>{chart?.title}</span><span className="ready">Generated</span></div>
                <Image src={imageUrl} alt={chart?.title ?? "Generated visualization"} width={1440} height={960} unoptimized />
              </div>
              <div className="result-meta"><div><small>AGENT DECISION</small><p>{visualization.spec.rationale}</p></div>
                {visualization.sources && <div><small>AUTO-SELECTED SOURCES · {visualization.sources.length}</small><div className="source-list">{visualization.sources.map(source => <span key={source.id}>{source.name}<small>{source.filename}</small></span>)}</div><p>{visualization.source_selection?.rationale}</p></div>}
                {visualization.agent_trace && visualization.agent_trace.length > 0 && <details className="agent-trace">
                  <summary>查看 ReAct 工具轨迹 <span>{visualization.agent_trace.length} actions</span></summary>
                  <div>{visualization.agent_trace.map((step, index) => <article key={`${step.round}-${step.tool}-${index}`}>
                    <b>{step.round}</b><code>{step.tool}</code>
                    <small className={step.valid === true || step.result_status === "VALIDATED" ? "trace-ok" : ""}>{step.result_status ?? (step.result_count !== undefined ? `${step.result_count} results` : "completed")}</small>
                  </article>)}</div>
                </details>}
                {visualization.token_usage && <div className="token-usage">
                  <small>MODEL USAGE</small>
                  <div><span><b>{visualization.token_usage.total_tokens.toLocaleString()}</b><em>Total tokens</em></span><span><b>{visualization.token_usage.input_tokens.toLocaleString()}</b><em>Input</em></span><span><b>{visualization.token_usage.output_tokens.toLocaleString()}</b><em>Output</em></span><span><b>{visualization.token_usage.api_calls}</b><em>API calls</em></span></div>
                </div>}
                <div className="spec-line"><code>{chart?.chart_type}</code><span>x: {chart?.x}</span><span>y: {chart?.y}</span>{chart?.group && <span>group: {chart.group}</span>}</div>
                <div className="downloads"><a href={`${API_V1}/visualizations/${visualization.id}/image`} download>下载 PNG</a><a href={`${API_V1}/visualizations/${visualization.id}/code`} download>下载 Python</a></div>
              </div>
            </div>}
          </section>

          {visualization && styleDraft && <section className="panel canvas-panel">
            <div className="step"><span>04</span> Figure canvas · Style editor</div>
            <div className="canvas-layout">
              <div className="canvas-stage">
                <div className="canvas-toolbar"><span>LIVE ARTIFACT</span><div className="canvas-tool-actions">
                  <button type="button" onClick={undoCanvas} disabled={!undoStack.length} title="撤销">↶</button>
                  <button type="button" onClick={redoCanvas} disabled={!redoStack.length} title="重做">↷</button>
                  <button type="button" onClick={() => alignSelected("horizontal")} disabled={!selectedCanvasObject} title="水平居中">↔</button>
                  <button type="button" onClick={() => alignSelected("vertical")} disabled={!selectedCanvasObject} title="垂直居中">↕</button>
                  <button type="button" className="save-canvas-button" onClick={() => void applyCanvasStyle()} disabled={!!busy}>{busy === "style" ? "保存中" : "应用保存"}</button>
                </div><small>{styleDraft.figure_width} × {styleDraft.figure_height} in · {styleDraft.dpi} DPI</small></div>
                <div ref={canvasPaperRef} tabIndex={0} className="canvas-paper direct-canvas svg-canvas" style={{ backgroundColor: styleDraft.background_color, aspectRatio: `${styleDraft.figure_width} / ${styleDraft.figure_height}` }} onClick={handleSvgClick} onDoubleClick={handleSvgDoubleClick} onPointerDown={handleSvgPointerDown} onKeyDown={handleCanvasKey}>
                  {svgMarkup ? <EditableSvg markup={svgMarkup} /> : <div className="svg-loading">正在准备可编辑 SVG…</div>}
                  {selectedCanvasObject && selectedCanvasObject.visible && <div className={`canvas-selection ${selectedCanvasObject.locked ? "is-locked" : ""}`} style={{ left: `${selectedCanvasObject.x * 100}%`, top: `${selectedCanvasObject.y * 100}%`, width: `${selectedCanvasObject.width * 100}%`, height: `${selectedCanvasObject.height * 100}%`, transform: `rotate(${selectedCanvasObject.rotation}deg)` }} onPointerDown={event => beginObjectTransform(event, "move")}>
                    <span className="selection-label">{selectedCanvasObject.id}</span>
                    {!selectedCanvasObject.locked && <>
                      {["nw", "n", "ne", "e", "se", "s", "sw", "w"].map(handle => <button type="button" key={handle} className={`selection-handle handle-${handle}`} aria-label={`${handle} 缩放`} onPointerDown={event => beginObjectTransform(event, "resize", handle)} />)}
                      <button type="button" className="rotation-handle" aria-label="旋转" onPointerDown={event => beginObjectTransform(event, "rotate")}>↻</button>
                    </>}
                  </div>}
                  {svgEditor && <div className="svg-popover text-popover" style={{ left: svgEditor.x, top: svgEditor.y }} onClick={event => event.stopPropagation()}>
                    <small>直接编辑</small><input autoFocus value={styleDraft[svgEditor.field]} onChange={event => updateSvgText(svgEditor.field, event.target.value)} onBlur={() => setSvgEditor(null)} onKeyDown={event => { if (event.key === "Enter") setSvgEditor(null); }} />
                  </div>}
                  {seriesEditor && <div className="svg-popover series-popover" style={{ left: seriesEditor.x, top: seriesEditor.y }} onClick={event => event.stopPropagation()}>
                    <small>Series {seriesEditor.index + 1}</small><input type="color" value={styleDraft.palette[seriesEditor.index] ?? "#126149"} onChange={event => updateSeriesColor(seriesEditor.index, event.target.value)} />
                  </div>}
                  <button type="button" className="canvas-resize-handle" aria-label="拖动调整画布尺寸" onPointerDown={startCanvasResize}>↘</button>
                </div>
                <p>像 PPT 一样选中并拖拽对象；边框控制缩放，顶部手柄控制旋转，双击文字直接编辑。方向键可微调，Shift + 方向键可快速移动。</p>
              </div>

            </div>
          </section>}
        </div>
      </section>
      <footer>ResearchViz AI <span>·</span> Reproducible by design <span>·</span> Matplotlib + FastAPI + Next.js</footer>
    </main>
  );
}
