import type { ComponentType, HTMLAttributes, ReactNode, Ref } from "react";

/**
 * Permissive component type for the animation engine's dynamic `<Tag>` renders
 * (`animated[tag]` / a runtime tag string). Using `React.ElementType` there
 * collapses `children` to `never` once `@react-three/fiber` augments the global
 * `JSX.IntrinsicElements` with its `never`-typed pseudo-elements — this single
 * element's prop shape avoids that union. See [[decisions-log]] ADR-0013.
 */
export type DynamicTag = ComponentType<
  HTMLAttributes<HTMLElement> & {
    children?: ReactNode;
    ref?: Ref<HTMLElement>;
  }
>;

export type Tags =
  | "div"
  | "span"
  | "p"
  | "h1"
  | "h2"
  | "h3"
  | "h4"
  | "h5"
  | "h6"
  | "section"
  | "article"
  | "nav"
  | "aside"
  | "header"
  | "footer"
  | "main"
  | "form"
  | "input"
  | "button"
  | "a"
  | "img"
  | "ul"
  | "ol"
  | "li"
  | "table"
  | "tr"
  | "td"
  | "th"
  | "thead"
  | "tbody"
  | "label"
  | "select"
  | "option"
  | "textarea"
  | "canvas"
  | "svg"
  | "path"
  | "circle"
  | "rect"
  | "polygon"
  | "video"
  | "audio"
  | "source"
  | "iframe"
  | "figure"
  | "figcaption"
  | "picture"
  | "time"
  | "address"
  | "blockquote"
  | "code"
  | "pre"
  | "details"
  | "summary"
  | "dialog"
  | "menu"
  | "menuitem"
  | "progress"
  | "meter"
  | "fieldset"
  | "legend"
  | "datalist"
  | "optgroup"
  | "output"
  | "template"
  | "slot";
