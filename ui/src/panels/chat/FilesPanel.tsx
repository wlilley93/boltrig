import type { ChatAttachment, ChatMessage } from "@/api/types";
import { fileExtClass, formatBytes, whenText } from "@/panels/chat/formatting";
import { Icon } from "@/panels/chat/icons";

interface FilesPanelProps {
  attachments: ChatAttachment[];
  messages: ChatMessage[];
  onClose: () => void;
}

interface FileRowData {
  name: string;
  size: number;
  meta: string;
  type: string;
}

interface FileRowProps {
  file: FileRowData;
  dim?: boolean;
  downloadable?: boolean;
}

function FileRow({ file, dim, downloadable = true }: FileRowProps): JSX.Element {
  return (
    <div className={`file-row ${fileExtClass(file.name)} ${dim ? "file-row--dim" : ""}`}>
      <span className="file-row__icon"><Icon name="file" size={15} /></span>
      <span className="file-row__copy">
        <strong>{file.name}</strong>
        <small>{file.meta}</small>
      </span>
      {downloadable && (
        <button className="icon-btn" type="button" aria-label={`Download ${file.name}`}>
          <Icon name="download" size={14} />
        </button>
      )}
    </div>
  );
}

// Placeholder-tier seed rows for the Pinned and Recent sections (brief sec
// 13.2). There is no pinned/recent persistence backend yet, so these fixed
// reference files keep the three-section structure faithful and degrade
// gracefully. Replace with real data when the files store lands. The names are
// chosen to exercise the file-type icon colors (.md, .yaml, .sql, .json, .diff).
const PINNED_ROWS: FileRowData[] = [
  { name: "architecture.md", size: 18 * 1024, meta: `${formatBytes(18 * 1024)} - pinned - ref`, type: "text/markdown" },
  { name: "runbook.yaml", size: 6 * 1024, meta: `${formatBytes(6 * 1024)} - pinned - ref`, type: "text/yaml" },
];

const RECENT_ROWS: FileRowData[] = [
  { name: "release-notes.md", size: 11 * 1024, meta: `${formatBytes(11 * 1024)} - Bolt - 2h ago`, type: "text/markdown" },
  { name: "schema.sql", size: 4 * 1024, meta: `${formatBytes(4 * 1024)} - Head of SRE - 1d ago`, type: "application/sql" },
  { name: "config.json", size: 2 * 1024, meta: `${formatBytes(2 * 1024)} - Head of Engineering - 3d ago`, type: "application/json" },
];

export function FilesPanel({ attachments, messages, onClose }: FilesPanelProps): JSX.Element {
  const sessionRows: FileRowData[] = [
    ...attachments.map((a) => ({
      name: a.name,
      size: a.size ?? 0,
      meta: `${formatBytes(a.size ?? 0)} - pending - now`,
      type: a.media_type,
    })),
    ...messages.flatMap((m) =>
      (m.attachments ?? []).map((a) => ({
        name: a.name,
        size: a.size ?? 0,
        meta: `${formatBytes(a.size ?? 0)} - ${m.role} - ${whenText(m.created_at)}`,
        type: a.media_type,
      })),
    ),
  ];
  const pinnedRows = PINNED_ROWS;
  const recentRows = RECENT_ROWS;
  const allRows = [...sessionRows, ...pinnedRows, ...recentRows];
  const totalSize = allRows.reduce((sum, f) => sum + f.size, 0);

  return (
    <aside className="files-panel" aria-label="Files">
      <header className="files-panel__head">
        <strong>Files</strong>
        <button className="btn btn--ghost btn--sm" type="button">
          <Icon name="plus" size={13} />
          Upload
        </button>
        <button className="icon-btn" type="button" onClick={onClose} aria-label="Close files">
          <Icon name="x" size={15} />
        </button>
      </header>
      <input className="files-panel__search" placeholder="Search files" aria-label="Search files" />
      <div className="files-panel__body">
        <span className="files-panel__section">This session</span>
        {sessionRows.length === 0 && (
          <p className="files-panel__empty">No files attached to this conversation.</p>
        )}
        {sessionRows.map((file) => <FileRow file={file} key={`s-${file.name}-${file.meta}`} />)}

        <span className="files-panel__section">Pinned</span>
        {pinnedRows.map((file) => <FileRow file={file} key={`p-${file.name}-${file.meta}`} />)}

        <span className="files-panel__section">Recent</span>
        {recentRows.map((file) => (
          <FileRow file={file} dim downloadable={false} key={`r-${file.name}-${file.meta}`} />
        ))}
      </div>
      <footer className="files-panel__foot">
        <span>{allRows.length} files - {formatBytes(totalSize)}</span>
        <button className="files-panel__view-all" type="button">View all</button>
      </footer>
    </aside>
  );
}

export { type FilesPanelProps };
