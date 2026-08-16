import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type SetStateAction,
} from "react";
import type { ChatAttachment, ChatAttachmentLimits } from "@wlilley93/boltrig-web-sdk";

import {
  arrayBufferToBase64,
  attachmentTextPreview,
  formatBytes,
  modelReadable,
} from "./attachmentPresentation";
import "./ComposerAttachments.css";

export const CHAT_QUEUE_DRAG_TYPE = "application/x-boltrig-queued-message";
export const LONG_TEXT_ATTACHMENT_THRESHOLD = 2_000;

type FileSource = FileList | readonly File[] | null;
type TextAttachmentSource = "dropped" | "pasted";

function attachmentError(
  current: ChatAttachment[],
  selected: File[],
  limits: ChatAttachmentLimits,
): string | null {
  if (current.length + selected.length > limits.max_count) {
    return `Attach at most ${limits.max_count} files to one turn.`;
  }
  const tooLarge = selected.find((file) => file.size > limits.max_bytes);
  if (tooLarge) {
    return `${tooLarge.name} is too large. Each file must be ${formatBytes(limits.max_bytes)} or smaller.`;
  }
  const total = current.reduce((sum, file) => sum + (file.size ?? 0), 0)
    + selected.reduce((sum, file) => sum + file.size, 0);
  return total > limits.max_total_bytes
    ? `Attachments must total ${formatBytes(limits.max_total_bytes)} or less.`
    : null;
}

function nextTextName(source: TextAttachmentSource, files: ChatAttachment[]): string {
  const stem = `${source}-text`;
  const names = new Set(files.map((file) => file.name));
  for (let index = 1; index <= files.length + 1; index += 1) {
    const name = index === 1 ? `${stem}.txt` : `${stem}-${index}.txt`;
    if (!names.has(name)) return name;
  }
  return `${stem}-${files.length + 2}.txt`;
}

export function useComposerAttachments(
  conversationKey: string | null,
  attachmentLimits: ChatAttachmentLimits,
) {
  const [files, setFilesState] = useState<ChatAttachment[]>([]);
  const [fileError, setFileError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const conversationKeyRef = useRef(conversationKey);
  const filesRef = useRef(files);
  conversationKeyRef.current = conversationKey;
  filesRef.current = files;

  function updateFiles(update: SetStateAction<ChatAttachment[]>) {
    const next = typeof update === "function" ? update(filesRef.current) : update;
    filesRef.current = next;
    setFilesState(next);
  }

  useLayoutEffect(() => {
    updateFiles([]);
    setFileError("");
    if (input.current) input.current.value = "";
  }, [conversationKey]);

  async function addFiles(list: FileSource): Promise<boolean> {
    const selected = list ? Array.from(list) : [];
    if (selected.length === 0) return false;
    const owner = conversationKeyRef.current;
    setFileError("");
    const invalid = attachmentError(filesRef.current, selected, attachmentLimits);
    if (invalid) { setFileError(invalid); return false; }
    try {
      const added = await Promise.all(selected.map(async (file) => ({
        name: file.name,
        media_type: file.type || "application/octet-stream",
        data: arrayBufferToBase64(await file.arrayBuffer()),
        size: file.size,
      })));
      if (conversationKeyRef.current !== owner) return false;
      const changedWhileReading = attachmentError(filesRef.current, selected, attachmentLimits);
      if (changedWhileReading) { setFileError(changedWhileReading); return false; }
      updateFiles((current) => [...current, ...added]);
      return true;
    } catch {
      if (conversationKeyRef.current === owner) {
        setFileError("That attachment could not be read. Try the file again.");
      }
      return false;
    }
  }

  function addText(text: string, source: TextAttachmentSource): Promise<boolean> {
    const file = new File(
      [text],
      nextTextName(source, filesRef.current),
      { type: "text/plain" },
    );
    return addFiles([file]);
  }

  return {
    addFiles,
    addText,
    fileError,
    files,
    input,
    ownsConversation: (owner: string | null) => conversationKeyRef.current === owner,
    setFiles: updateFiles,
  };
}

function transferTypes(transfer: DataTransfer): string[] {
  return Array.from(transfer.types ?? []);
}

export function supportsComposerTransfer(transfer: DataTransfer | null): boolean {
  if (!transfer) return false;
  const types = transferTypes(transfer);
  if (types.includes(CHAT_QUEUE_DRAG_TYPE)) return false;
  return types.some((type) => type === "Files" || type === "text/plain" || type === "text/uri-list");
}

function transferText(transfer: DataTransfer): string {
  return transfer.getData("text/plain") || transfer.getData("text/uri-list");
}

export function useComposerAttachmentIngress({
  addFiles,
  addText,
  enabled,
}: {
  addFiles(files: FileSource): Promise<boolean>;
  addText(text: string, source: TextAttachmentSource): Promise<boolean>;
  enabled: boolean;
}) {
  const [dragActive, setDragActive] = useState(false);
  const actions = useRef({ addFiles, addText });
  actions.current = { addFiles, addText };

  useEffect(() => {
    if (!enabled) { setDragActive(false); return undefined; }
    let depth = 0;
    const clear = () => { depth = 0; setDragActive(false); };
    const enter = (event: DragEvent) => {
      if (!supportsComposerTransfer(event.dataTransfer)) return;
      event.preventDefault();
      depth += 1;
      setDragActive(true);
    };
    const over = (event: DragEvent) => {
      if (!supportsComposerTransfer(event.dataTransfer)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      setDragActive(true);
    };
    const leave = () => {
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragActive(false);
    };
    const drop = (event: DragEvent) => {
      const transfer = event.dataTransfer;
      clear();
      if (!supportsComposerTransfer(transfer) || !transfer) return;
      event.preventDefault();
      const files = Array.from(transfer.files ?? []);
      if (files.length > 0) void actions.current.addFiles(files);
      else {
        const text = transferText(transfer);
        if (text.trim()) void actions.current.addText(text, "dropped");
      }
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    window.addEventListener("dragend", clear);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
      window.removeEventListener("dragend", clear);
      window.removeEventListener("blur", clear);
    };
  }, [enabled]);

  function onPaste(event: ReactClipboardEvent<HTMLTextAreaElement>) {
    if (!enabled) return;
    const files = Array.from(event.clipboardData.files ?? []);
    if (files.length > 0) {
      event.preventDefault();
      void actions.current.addFiles(files);
      return;
    }
    const text = event.clipboardData.getData("text/plain");
    if (text.length < LONG_TEXT_ATTACHMENT_THRESHOLD) return;
    event.preventDefault();
    void actions.current.addText(text, "pasted");
  }

  return { dragActive, onPaste };
}

export function AttachmentStatus({
  attachmentLimits,
  fileError,
  files,
  onRemove,
}: {
  attachmentLimits: ChatAttachmentLimits;
  fileError: string;
  files: ChatAttachment[];
  onRemove(file: ChatAttachment): void;
}) {
  return (
    <>
      {files.length > 0 && (
        <div aria-label="Attached files" className="file-row composer-attachment-row">
          {files.map((file, index) => (
            <AttachmentPreview
              attachmentLimits={attachmentLimits}
              file={file}
              key={`${file.name}-${index}`}
              onRemove={onRemove}
            />
          ))}
        </div>
      )}
      {fileError && <p className="notice" role="alert">{fileError}</p>}
    </>
  );
}

function AttachmentPreview({
  attachmentLimits,
  file,
  onRemove,
}: {
  attachmentLimits: ChatAttachmentLimits;
  file: ChatAttachment;
  onRemove(file: ChatAttachment): void;
}) {
  const readable = modelReadable(
    file.media_type,
    attachmentLimits.model_readable_media_types,
  );
  const image = file.media_type.toLowerCase().startsWith("image/");
  const textPreview = attachmentTextPreview(file);
  return (
    <article className="composer-attachment-card">
      <span className={`composer-attachment-visual${textPreview ? " text" : ""}`}>
        {image
          ? <img alt="" src={`data:${file.media_type};base64,${file.data}`} />
          : textPreview
            ? <pre aria-hidden>{textPreview}</pre>
          : <svg aria-hidden fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24"><path d="M6 2h8l4 4v16H6z" /><path d="M14 2v5h5M9 13h6M9 17h5" /></svg>}
      </span>
      <span className="composer-attachment-copy">
        <strong title={file.name}>{file.name}</strong>
        <small>{readable ? "model-readable" : "record only"}</small>
      </span>
      <button aria-label={`Remove ${file.name}`} onClick={() => onRemove(file)} type="button">×</button>
    </article>
  );
}
