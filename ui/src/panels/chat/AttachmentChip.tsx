import type { ChatAttachment } from "@/api/types";
import { decodeAttachmentText, formatBytes, isTextAttachmentType } from "@/panels/chat/attachmentUtils";

interface AttachmentChipProps {
  att: ChatAttachment;
}

function AttachmentChip({ att }: AttachmentChipProps): JSX.Element {
  const meta = `${att.media_type}${att.size ? ` - ${formatBytes(att.size)}` : ""}`;
  if (isTextAttachmentType(att.media_type)) {
    const text = decodeAttachmentText(att.data);
    return (
      <details className="chat-att chat-att--text">
        <summary className="chat-att__head">
          <span className="chat-att__name">{att.name}</span>
          <span className="chat-att__meta muted">{meta}</span>
        </summary>
        <pre className="chat-att__preview">{text.slice(0, 4000)}</pre>
      </details>
    );
  }
  return (
    <span className="chat-att">
      <span className="chat-att__name">{att.name}</span>
      <span className="chat-att__meta muted">{meta}</span>
    </span>
  );
}

interface AttachmentListProps {
  attachments?: ChatAttachment[];
}

export function AttachmentList({ attachments }: AttachmentListProps): JSX.Element | null {
  if (!attachments || attachments.length === 0) return null;
  return (
    <div className="chat-atts">
      {attachments.map((a, i) => (
        <AttachmentChip key={`${a.name}-${i}`} att={a} />
      ))}
    </div>
  );
}

export { AttachmentChip };
export type { AttachmentChipProps, AttachmentListProps };
