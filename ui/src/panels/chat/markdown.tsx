import {
  Children,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CopyButton } from "@/panels/chat/CopyButton";
import { navigate } from "@/router";

function CodeBlock({ children }: { children: ReactNode }): JSX.Element {
  const only = Children.only(children) as ReactElement<{
    className?: string;
    children?: ReactNode;
  }>;
  const className = isValidElement(only) ? only.props.className ?? "" : "";
  const raw = isValidElement(only) ? only.props.children : children;
  const text = String(raw ?? "").replace(/\n$/, "");
  const lang = /language-([a-zA-Z0-9_-]+)/.exec(className)?.[1];

  return (
    <div className="md-code">
      <div className="md-code__bar">
        <span className="badge">{lang ?? "code"}</span>
        <CopyButton text={text} label="Copy" className="btn btn--ghost btn--sm md-code__copy" />
      </div>
      <pre>
        <code className={className}>{text}</code>
      </pre>
    </div>
  );
}

const MARKDOWN_COMPONENTS: Components = {
  a({ href, children }) {
    const target = href ?? "";
    if (target.startsWith("#/")) {
      return (
        <button
          type="button"
          className="chat-md__linkchip"
          onClick={() => navigate(target.slice(1))}
        >
          {children}
        </button>
      );
    }
    return (
      <a href={target} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  img({ src, alt }) {
    return (
      <a href={src ?? ""} target="_blank" rel="noopener noreferrer">
        {alt || src || "image"}
      </a>
    );
  },
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>;
  },
};

export function MarkdownText({ value }: { value: string }): JSX.Element {
  return (
    <div className="chat-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {value}
      </ReactMarkdown>
    </div>
  );
}

export { MARKDOWN_COMPONENTS };
