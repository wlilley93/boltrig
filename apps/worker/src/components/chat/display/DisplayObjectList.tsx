import { useMemo } from "react";
import {
  parseDisplayObject,
  type DisplayObjectEntry,
} from "@wlilley93/boltrig-web-sdk";

import { DisplayObjectCard } from "./DisplayObjectCard";
import type { DisplayObjectReply } from "./DecisionDisplayCards";
import "./DisplayObjects.css";

export function DisplayObjectList({ entries, settled, onReply }: {
  entries: DisplayObjectEntry[];
  settled: boolean;
  onReply?: DisplayObjectReply;
}) {
  const objects = useMemo(() => latestValidObjects(entries), [entries]);
  if (objects.length === 0 && entries.length === 0) return null;
  return <div aria-label="Chat visual objects" className="display-object-list">
    {objects.map(({ key, object }) => (
      <DisplayObjectCard key={key} object={object} onReply={onReply} settled={settled} />
    ))}
    {objects.length < entries.length && <p className="display-object-unavailable" role="status">
      A visual object was unavailable because it did not match the reviewed display contract.
    </p>}
  </div>;
}

function latestValidObjects(entries: DisplayObjectEntry[]): DisplayObjectEntry[] {
  const latest = new Map<string, DisplayObjectEntry>();
  entries.forEach((entry) => {
    const object = parseDisplayObject(entry.object);
    if (!object) return;
    const current = latest.get(object.id);
    if (!current || (current.object.revision ?? 1) <= (object.revision ?? 1)) {
      latest.set(object.id, { ...entry, object });
    }
  });
  return [...latest.values()];
}
