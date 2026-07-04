import { useState } from "react";

import { api } from "@/api/client";
import type { AdapterInventoryResponse } from "@/api/types";
import type { FetchState } from "@/useFetch";
import { CodeBlock, errText } from "@/panels/shared";
import { Field, Select } from "@/panels/ux";

export function useAdapterSource(adapters: FetchState<AdapterInventoryResponse>) {
  const adapterRecords = adapters.data?.adapters ?? [];

  const [adapterId, setAdapterId] = useState("");
  const [srcBusy, setSrcBusy] = useState(false);
  const [srcError, setSrcError] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);

  async function loadSource() {
    if (!adapterId.trim()) {
      setSrcError("Pick an adapter first.");
      return;
    }
    setSrcBusy(true);
    setSrcError(null);
    setSource(null);
    try {
      const res = await api.adapterSource(adapterId.trim());
      if (res.error) setSrcError(res.error);
      else setSource(res.source ?? "");
    } catch (err) {
      setSrcError(errText(err));
    } finally {
      setSrcBusy(false);
    }
  }

  return {
    adapters,
    adapterRecords,
    adapterId,
    setAdapterId,
    srcBusy,
    srcError,
    source,
    loadSource,
  };
}

export function AdapterSourceSection({
  adapters,
}: {
  adapters: FetchState<AdapterInventoryResponse>;
}) {
  const {
    adapterRecords,
    adapterId,
    setAdapterId,
    srcBusy,
    srcError,
    source,
    loadSource,
  } = useAdapterSource(adapters);

  return (
    <div className="form">
      <div className="form__title">Adapter source</div>
      <p className="ux-hint">
        The generated source for a registered adapter, read-only - useful to
        see exactly what a verb runs.
      </p>
      <div className="form__actions">
        <Field label="Adapter">
          <Select
            value={adapterId}
            ariaLabel="Pick an adapter"
            onChange={setAdapterId}
            options={[
              { value: "", label: adapters.loading ? "Loading adapters..." : "Choose an adapter..." },
              ...adapterRecords.map((a) => ({
                value: a.id,
                label: `${a.id} (${a.runtime} ${a.version})`,
              })),
            ]}
          />
        </Field>
        <button className="btn" disabled={srcBusy} onClick={loadSource}>
          {srcBusy ? "Loading..." : "View source"}
        </button>
        {srcError && <span className="error">{srcError}</span>}
      </div>
      {adapters.error && (
        <p className="error">Could not load adapters: {adapters.error}</p>
      )}
      {source !== null && <CodeBlock value={source} />}
    </div>
  );
}
