import { useEffect, useMemo } from "react";
import type { ChatAttachment, ChatMessage } from "@/api/types";
import { fileExtClass, formatBytes, whenText } from "@/panels/chat/formatting";
import { Icon } from "@/panels/chat/icons";
import {
  useFilesStore,
  type FileRef,
  type PinnedFile,
  type RecentFile,
} from "@/panels/chat/useFilesStore";

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

// A live-session file paired with the stable identity it shares with the
// Pinned/Recent stores, kept in lockstep so a row and its toggle never drift.
interface SessionItem {
  ref: FileRef;
  row: FileRowData;
}

// ChatAttachment carries no id, so we derive a stable identity from name + size
// to dedupe a file across the stores and the current session.
function fileId(name: string, size: number): string {
  return `${name}#${size}`;
}

function attachmentItem(a: ChatAttachment, agent: string, when: string): SessionItem {
  const size = a.size ?? 0;
  return {
    ref: { id: fileId(a.name, size), name: a.name, size, agent },
    row: {
      name: a.name,
      size,
      meta: `${formatBytes(size)} - ${agent} - ${when}`,
      type: a.media_type,
    },
  };
}

interface FileRowProps {
  file: FileRowData;
  dim?: boolean;
  downloadable?: boolean;
  // When provided, a pin toggle is rendered. `pinned` selects the solid glyph
  // and the aria-label; the parent decides pin vs unpin on click.
  pinned?: boolean;
  onTogglePin?: () => void;
}

function FileRow({
  file,
  dim,
  downloadable = true,
  pinned = false,
  onTogglePin,
}: FileRowProps): JSX.Element {
  const pinnable = onTogglePin !== undefined;
  return (
    <div
      className={`file-row ${fileExtClass(file.name)} ${dim ? "file-row--dim" : ""} ${
        pinnable ? "file-row--pinnable" : ""
      }`}
    >
      <span className="file-row__icon"><Icon name="file" size={15} /></span>
      <span className="file-row__copy">
        <strong>{file.name}</strong>
        <small>{file.meta}</small>
      </span>
      {onTogglePin && (
        <button
          className="icon-btn file-row__pin"
          type="button"
          onClick={onTogglePin}
          aria-label={pinned ? `Unpin ${file.name}` : `Pin ${file.name}`}
          aria-pressed={pinned}
        >
          <Icon name="pin" size={13} filled={pinned} />
        </button>
      )}
      {downloadable && (
        <button className="icon-btn" type="button" aria-label={`Download ${file.name}`}>
          <Icon name="download" size={14} />
        </button>
      )}
    </div>
  );
}

export function FilesPanel({ attachments, messages, onClose }: FilesPanelProps): JSX.Element {
  const { pinned, recent, pin, unpin, trackRecent } = useFilesStore();

  const sessionItems: SessionItem[] = useMemo(
    () => [
      ...attachments.map((a) => attachmentItem(a, "pending", "now")),
      ...messages.flatMap((m) =>
        (m.attachments ?? []).map((a) => attachmentItem(a, m.role, whenText(m.created_at))),
      ),
    ],
    [attachments, messages],
  );
  const sessionRefs = sessionItems.map((it) => it.ref);

  // Grow the Recent history from real usage whenever the session's file set
  // changes. Keyed on the id signature so repeat renders are a no-op.
  const sessionSignature = sessionRefs.map((f) => f.id).join("|");
  useEffect(() => {
    sessionRefs.forEach((f) => trackRecent(f));
    // trackRecent is stable; sessionRefs is captured per signature.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionSignature, trackRecent]);

  const pinnedIds = useMemo(() => new Set(pinned.map((p) => p.id)), [pinned]);
  const sessionIds = useMemo(() => new Set(sessionRefs.map((f) => f.id)), [sessionSignature]);

  const pinnedRows: FileRowData[] = pinned.map((p) => ({
    name: p.name,
    size: p.size,
    meta: `${formatBytes(p.size)} - pinned - ${whenText(new Date(p.pinnedAt).toISOString())}`,
    type: "application/octet-stream",
  }));

  // Recent shows files from PREVIOUS sessions: drop anything still live so a
  // current file is not listed twice. Dimmer, no download icon (brief 13.2).
  const displayedRecent: RecentFile[] = recent.filter((r) => !sessionIds.has(r.id));
  const recentRows: FileRowData[] = displayedRecent.map((r) => ({
    name: r.name,
    size: r.size,
    meta: `${formatBytes(r.size)} - ${r.agent} - ${whenText(new Date(r.seenAt).toISOString())}`,
    type: "application/octet-stream",
  }));

  const sessionCount = sessionItems.length;
  const allCount = sessionCount + pinnedRows.length + recentRows.length;
  const totalSize =
    sessionItems.reduce((s, it) => s + it.row.size, 0) +
    pinned.reduce((s, p) => s + p.size, 0) +
    displayedRecent.reduce((s, r) => s + r.size, 0);

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
        {sessionItems.length === 0 && (
          <p className="files-panel__empty">No files attached to this conversation.</p>
        )}
        {sessionItems.map(({ ref, row }) => {
          const isPinned = pinnedIds.has(ref.id);
          return (
            <FileRow
              file={row}
              key={`s-${ref.id}`}
              pinned={isPinned}
              onTogglePin={() => (isPinned ? unpin(ref.id) : pin(ref))}
            />
          );
        })}

        <span className="files-panel__section">Pinned</span>
        {pinned.length === 0 ? (
          <p className="files-panel__empty">No pinned files yet</p>
        ) : (
          pinned.map((entry: PinnedFile, i) => (
            <FileRow
              file={pinnedRows[i]}
              key={`p-${entry.id}`}
              pinned
              onTogglePin={() => unpin(entry.id)}
            />
          ))
        )}

        <span className="files-panel__section">Recent</span>
        {recentRows.length === 0 ? (
          <p className="files-panel__empty">No recent files</p>
        ) : (
          recentRows.map((row, i) => (
            <FileRow file={row} dim downloadable={false} key={`r-${displayedRecent[i].id}`} />
          ))
        )}
      </div>
      <footer className="files-panel__foot">
        <span>{allCount} files - {formatBytes(totalSize)}</span>
        <button className="files-panel__view-all" type="button">View all</button>
      </footer>
    </aside>
  );
}

export { type FilesPanelProps };
