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

export function FilesPanel({ attachments, messages, onClose }: FilesPanelProps): JSX.Element {
  const rows: FileRowData[] = [
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
  const totalSize = rows.reduce((sum, f) => sum + f.size, 0);

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
        {rows.length === 0 && (
          <p className="files-panel__empty">No files attached to this conversation.</p>
        )}
        {rows.map((file) => <FileRow file={file} key={`${file.name}-${file.meta}`} />)}
      </div>
      <footer className="files-panel__foot">
        <span>{rows.length} files · {formatBytes(totalSize)}</span>
      </footer>
    </aside>
  );
}

export { type FilesPanelProps };
