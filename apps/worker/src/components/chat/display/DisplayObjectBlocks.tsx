import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { DisplayBlock } from "@wlilley93/boltrig-web-sdk";

export function DisplayObjectBlocks({ blocks }: { blocks: DisplayBlock[] }) {
  if (blocks.length === 0) return null;
  return <div className="display-object-blocks">
    {blocks.map((block, index) => <DisplayBlockView block={block} key={`${block.type}:${index}`} />)}
  </div>;
}

function DisplayBlockView({ block }: { block: DisplayBlock }) {
  if (TEXT_BLOCK_TYPES.has(block.type)) {
    return <TextBlock block={block as TextualBlock} />;
  }
  if (DATA_BLOCK_TYPES.has(block.type)) {
    return <DataBlock block={block as DataBlockType} />;
  }
  return <MediaBlock block={block as MediaBlockType} />;
}

type TextualBlock = Extract<DisplayBlock, { type: "text" | "markdown" | "code" | "notice" | "divider" }>;
type DataBlockType = Extract<DisplayBlock, {
  type: "key_value" | "metrics" | "table" | "progress" | "steps" | "timeline" | "chart";
}>;
type MediaBlockType = Extract<DisplayBlock, { type: "image" | "gallery" | "diff" | "source" | "map" }>;

const TEXT_BLOCK_TYPES = new Set<DisplayBlock["type"]>(["text", "markdown", "code", "notice", "divider"]);
const DATA_BLOCK_TYPES = new Set<DisplayBlock["type"]>([
  "key_value", "metrics", "table", "progress", "steps", "timeline", "chart",
]);

function TextBlock({ block }: { block: TextualBlock }) {
  switch (block.type) {
    case "text":
      return <p className="display-object-text">{block.text}</p>;
    case "markdown":
      return <div className="display-object-markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.text}</ReactMarkdown>
      </div>;
    case "code":
      return <pre className="display-object-code"><code>{block.code}</code></pre>;
    case "notice":
      return <p className="display-object-notice" data-tone={block.tone ?? "neutral"}>{block.text}</p>;
    case "divider":
      return <hr className="display-object-divider" />;
  }
}

function DataBlock({ block }: { block: DataBlockType }) {
  switch (block.type) {
    case "key_value":
      return <KeyValues items={block.items} />;
    case "metrics":
      return <Metrics items={block.items} />;
    case "table":
      return <Table columns={block.columns} rows={block.rows} />;
    case "progress":
      return <Progress value={block.value} max={block.max} label={block.label} />;
    case "steps":
      return <Steps items={block.items} />;
    case "timeline":
      return <Timeline items={block.items} />;
    case "chart":
      return <Chart series={block.series} />;
  }
}

function MediaBlock({ block }: { block: MediaBlockType }) {
  switch (block.type) {
    case "image":
      return <figure className="display-object-image"><img alt={block.alt} src={block.url} />
        {block.caption && <figcaption>{block.caption}</figcaption>}
      </figure>;
    case "gallery":
      return <div className="display-object-gallery">{block.items.map((item) => (
        <figure key={item.url}><img alt={item.alt} src={item.url} />
          {item.caption && <figcaption>{item.caption}</figcaption>}
        </figure>
      ))}</div>;
    case "diff":
      return <div className="display-object-diff">
        {block.label && <strong>{block.label}</strong>}
        <div><pre data-side="before">{block.before}</pre><pre data-side="after">{block.after}</pre></div>
      </div>;
    case "source":
      return block.url
        ? <a className="display-object-source" href={block.url} rel="noreferrer" target="_blank">{block.label} ↗</a>
        : <span className="display-object-source">{block.label}</span>;
    case "map":
      return <MapBlock {...block} />;
  }
}

function KeyValues({ items }: { items: Array<{ label: string; value: string }> }) {
  return <dl className="display-object-kv">{items.map((item, index) => (
    <div key={`${item.label}:${index}`}><dt>{item.label}</dt><dd>{item.value}</dd></div>
  ))}</dl>;
}

function Metrics({ items }: { items: Array<{ label: string; value: string; change?: string }> }) {
  return <div className="display-object-metrics">{items.map((item, index) => (
    <div key={`${item.label}:${index}`}><span>{item.label}</span><strong>{item.value}</strong>
      {item.change && <small>{item.change}</small>}
    </div>
  ))}</div>;
}

function Table({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return <div className="display-object-table-scroll"><table className="display-object-table">
    <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
    <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>
      {columns.map((_, columnIndex) => <td key={columnIndex}>{row[columnIndex] ?? ""}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

function Progress({ value, max = 100, label }: { value: number; max?: number; label?: string }) {
  const bounded = Math.max(0, Math.min(max > 0 ? max : 100, value));
  return <div className="display-object-progress">
    <div><span>{label ?? "Progress"}</span><span>{Math.round(bounded)} / {max}</span></div>
    <progress max={max > 0 ? max : 100} value={bounded} />
  </div>;
}

function Steps({ items }: { items: Array<{ label: string; status?: string }> }) {
  return <ol className="display-object-steps">{items.map((item, index) => (
    <li key={`${item.label}:${index}`}><span aria-hidden />
      <span>{item.label}</span>{item.status && <small>{item.status}</small>}
    </li>
  ))}</ol>;
}

function Timeline({ items }: {
  items: Array<{ label: string; detail?: string; time?: string; status?: string }>;
}) {
  return <ol className="display-object-timeline">{items.map((item, index) => (
    <li key={`${item.label}:${index}`}><span aria-hidden /><div>
      <strong>{item.label}</strong>{item.detail && <p>{item.detail}</p>}
      <small>{[item.time, item.status].filter(Boolean).join(" · ")}</small>
    </div></li>
  ))}</ol>;
}

function Chart({ series }: { series: Array<{ label: string; value: number }> }) {
  const max = Math.max(...series.map((item) => Math.abs(item.value)), 1);
  return <div aria-label="Data chart" className="display-object-chart" role="img">
    {series.map((item) => <div key={item.label}>
      <span>{item.label}</span><i style={{ width: `${Math.abs(item.value) / max * 100}%` }} />
      <strong>{item.value.toLocaleString()}</strong>
    </div>)}
  </div>;
}

function MapBlock({ latitude, longitude, label, zoom }: {
  latitude: number; longitude: number; label: string; zoom?: number;
}) {
  const url = `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=${zoom ?? 14}/${latitude}/${longitude}`;
  return <a className="display-object-map" href={url} rel="noreferrer" target="_blank">
    <span aria-hidden className="display-object-map-pin">●</span>
    <span><strong>{label}</strong><small>{latitude.toFixed(5)}, {longitude.toFixed(5)}</small></span>
    <span>Open map ↗</span>
  </a>;
}
