import SwiftUI

/// The full provider list, searchable. Picking a row hands the id back and closes.
struct ProviderPickerView: View {
    let providers: [CatalogueProvider]
    let selection: String
    let onSelect: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    private var filtered: [CatalogueProvider] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return providers }
        return providers.filter { provider in
            provider.name.localizedCaseInsensitiveContains(needle)
                || provider.id.localizedCaseInsensitiveContains(needle)
                || (provider.detail ?? "").localizedCaseInsensitiveContains(needle)
        }
    }

    var body: some View {
        List {
            if filtered.isEmpty {
                Text("No providers match that search.")
                    .foregroundStyle(.secondary)
            }
            ForEach(filtered) { provider in
                Button {
                    onSelect(provider.id)
                    dismiss()
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(provider.name)
                                .foregroundStyle(.primary)
                            Text(provider.detail ?? (provider.id == "llama" ? "Meta's Llama" : provider.id))
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if provider.id == selection {
                            Image(systemName: "checkmark")
                                .foregroundStyle(BoltrigTheme.accent)
                        }
                    }
                }
                .accessibilityAddTraits(provider.id == selection ? .isSelected : [])
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Provider")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search providers")
    }
}

/// The models one provider lists, searchable. Picking a row hands back the exact model id.
struct ModelPickerView: View {
    let provider: CatalogueProvider
    let selection: String
    let onSelect: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    private var filtered: [CatalogueModel] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return provider.models }
        return provider.models.filter { model in
            model.label.localizedCaseInsensitiveContains(needle) || model.id.localizedCaseInsensitiveContains(needle)
        }
    }

    var body: some View {
        List {
            if filtered.isEmpty {
                Text("No models match that search.")
                    .foregroundStyle(.secondary)
            }
            ForEach(filtered) { model in
                let exact = ProviderCatalogue.exactModelID(provider: provider.id, model: model.id)
                Button {
                    onSelect(exact)
                    dismiss()
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.label)
                                .foregroundStyle(.primary)
                            Text(model.vision ? "Text + vision" : "Text")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if exact == selection {
                            Image(systemName: "checkmark")
                                .foregroundStyle(BoltrigTheme.accent)
                        }
                    }
                }
                .accessibilityAddTraits(exact == selection ? .isSelected : [])
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Model")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search models")
    }
}
