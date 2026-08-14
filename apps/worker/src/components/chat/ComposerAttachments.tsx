import type { ChatAttachment, ChatAttachmentLimits } from "@wlilley93/boltrig-web-sdk";

import { modelReadable } from "./attachmentPresentation";
import "./ComposerAttachments.css";

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
  return (
    <article className="composer-attachment-card">
      <span className="composer-attachment-visual">
        {image
          ? <img alt="" src={`data:${file.media_type};base64,${file.data}`} />
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
