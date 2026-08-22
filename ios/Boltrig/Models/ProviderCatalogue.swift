import Foundation

/// One model a provider lists, with whether it reads images.
struct CatalogueModel: Equatable, Hashable, Identifiable {
    let id: String
    let name: String?
    let vision: Bool

    var label: String { name ?? id }
}

/// One provider the picker offers. `api` is the address models.dev publishes for it;
/// `requiresBaseURL` and `keyOptional` mark the self-hosted entry the phone adds itself.
struct CatalogueProvider: Equatable, Hashable, Identifiable {
    let id: String
    let name: String
    let models: [CatalogueModel]
    var detail: String? = nil
    var info: String? = nil
    var api: String? = nil
    var requiresBaseURL = false
    var keyOptional = false
}

/// The provider and model list first-run setup offers: the web app's models.dev snapshot,
/// bundled whole so the phone and the browser agree. `scripts/sync-provider-catalogue.sh`
/// keeps the copy identical and a test pins `pinnedRevision` to the bundled file.
struct ProviderCatalogue: Equatable {
    /// The upstream models.dev commit the bundled file records. Bump with the file.
    static let pinnedRevision = "318e78edb69805bb278d841495a5e317044d9d9b"
    static let resourceName = "ProviderCatalogue"

    /// Self-hosted Ollama, placed before Ollama Cloud exactly as the web does: a local server
    /// that authenticates nothing and lists its own models, so the picker offers none.
    static let selfHostedOllama = CatalogueProvider(
        id: "ollama",
        name: "Ollama",
        models: [],
        detail: "Self-hosted",
        info: "Hosted Boltrig can use Ollama through a secured public HTTPS endpoint. Never expose an unauthenticated Ollama port. Use Boltrig Desktop to keep Ollama local to your computer.",
        requiresBaseURL: true,
        keyOptional: true
    )

    /// The providers the server drives with a native driver. Any other catalogue provider is
    /// bound through its published address as an OpenAI-compatible custom provider, so this
    /// set decides which path a provider takes, not whether it is offered. A second copy of
    /// the server's list; the web's test parses the Python source to keep them equal.
    static let bifrostSupported: Set<String> = [
        "anthropic", "azure", "bedrock", "cerebras", "cohere", "elevenlabs",
        "fireworks", "gemini", "groq", "huggingface", "mistral", "nebius",
        "ollama", "openai", "openrouter", "parasail", "perplexity", "replicate",
        "runway", "sgl", "vertex", "vllm", "xai",
    ]

    /// models.dev spells a few providers differently from the server.
    static let catalogueAliases: [String: String] = [
        "google": "gemini",
        "google-generative-ai": "gemini",
        "x-ai": "xai",
        "amazon-bedrock": "bedrock",
        "fireworks-ai": "fireworks",
        "google-vertex": "vertex",
    ]

    let source: String
    let revision: String
    let license: String
    let providers: [CatalogueProvider]
    private let byID: [String: CatalogueProvider]

    init(source: String, revision: String, license: String, providers: [CatalogueProvider]) {
        self.source = source
        self.revision = revision
        self.license = license
        self.providers = providers
        var index: [String: CatalogueProvider] = [:]
        index.reserveCapacity(providers.count)
        for provider in providers where index[provider.id] == nil {
            index[provider.id] = provider
        }
        self.byID = index
    }

    /// What the rules fall back to before the bundled file has loaded: the two entries whose
    /// rules do not come from the snapshot.
    static let minimal = ProviderCatalogue(source: "", revision: "", license: "", providers: [
        selfHostedOllama,
        CatalogueProvider(id: "custom", name: "Custom / self-hosted", models: []),
    ])

    // MARK: Loading

    enum LoadError: Error {
        case missingResource
        case unreadable
    }

    /// Reads and decodes the bundled file away from the main thread.
    static func load(bundle: Bundle = .main) async throws -> ProviderCatalogue {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            throw LoadError.missingResource
        }
        return try await Task.detached(priority: .userInitiated) {
            let data = try Data(contentsOf: url)
            return try decode(data)
        }.value
    }

    @MainActor private static var sharedTask: Task<ProviderCatalogue, Error>?

    /// The bundled catalogue, decoded once per launch.
    @MainActor
    static func shared() async throws -> ProviderCatalogue {
        if let sharedTask {
            return try await sharedTask.value
        }
        let task = Task { try await load() }
        sharedTask = task
        do {
            return try await task.value
        } catch {
            sharedTask = nil
            throw error
        }
    }

    /// Decodes the snapshot and inserts the self-hosted entry before Ollama Cloud.
    static func decode(_ data: Data) throws -> ProviderCatalogue {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rows = root["providers"] as? [[String: Any]] else {
            throw LoadError.unreadable
        }
        var providers: [CatalogueProvider] = []
        providers.reserveCapacity(rows.count + 1)
        for row in rows {
            guard let id = row["id"] as? String, !id.isEmpty else { continue }
            let models = (row["models"] as? [[String: Any]] ?? []).compactMap { entry -> CatalogueModel? in
                guard let modelID = entry["id"] as? String, !modelID.isEmpty else { return nil }
                return CatalogueModel(id: modelID, name: entry["name"] as? String, vision: entry["vision"] as? Bool ?? false)
            }
            if id == "ollama-cloud" {
                providers.append(selfHostedOllama)
            }
            providers.append(CatalogueProvider(id: id, name: row["name"] as? String ?? id, models: models,
                                               api: (row["api"] as? String).flatMap { $0.isEmpty ? nil : $0 }))
        }
        return ProviderCatalogue(
            source: root["source"] as? String ?? "",
            revision: root["revision"] as? String ?? "",
            license: root["license"] as? String ?? "",
            providers: providers
        )
    }

    // MARK: Rules

    /// The id the server knows a catalogue provider by.
    static func bifrostProviderID(_ catalogueID: String) -> String {
        let id = catalogueID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return catalogueAliases[id] ?? id
    }

    static func isBifrostSupported(_ catalogueID: String) -> Bool {
        bifrostSupported.contains(bifrostProviderID(catalogueID))
    }

    /// The model id the server stores: `provider/model`, unless the provider is custom or
    /// the model is already written that way.
    static func exactModelID(provider: String, model: String) -> String {
        let provider = provider.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = model.trimmingCharacters(in: .whitespacesAndNewlines)
        if provider.isEmpty || provider == "custom" || model.hasPrefix(provider + "/") { return model }
        return provider + "/" + model
    }

    func provider(_ id: String) -> CatalogueProvider? {
        byID[id]
    }

    /// Whether the person must type an address: self-hosted entries always, and any
    /// non-native provider the catalogue publishes no address for. A non-native provider
    /// with a published address submits it silently.
    func needsBaseURL(_ id: String) -> Bool {
        guard let provider = byID[id] else { return false }
        if provider.requiresBaseURL { return true }
        return !Self.isBifrostSupported(provider.id) && (provider.api ?? "").isEmpty
    }

    func keyOptional(_ id: String) -> Bool {
        byID[id]?.keyOptional == true
    }

    /// The catalogue's published address for a provider, if it has one.
    func publishedBaseURL(_ id: String) -> String? {
        byID[id]?.api
    }

    static func == (lhs: ProviderCatalogue, rhs: ProviderCatalogue) -> Bool {
        lhs.source == rhs.source && lhs.revision == rhs.revision && lhs.license == rhs.license && lhs.providers == rhs.providers
    }
}
