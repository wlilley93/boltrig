import SwiftUI

/// The provider intake body, shared by the Provider step (text) and the Image model step
/// (vision): provider, key, address when one is needed, model, and the note that says what
/// the chosen model can read.
struct ProviderStepView: View {
    @ObservedObject var setup: ProviderSetupStore
    var kicker: String? = nil
    let title: String
    let lead: String
    var skip: (label: String, action: () -> Void)? = nil
    /// Enter on a field does what Continue does.
    let onSubmit: () -> Void

    var body: some View {
        OnboardingCard(kicker: kicker, title: title, lead: lead) {
            if setup.readiness == nil && setup.isLoading {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text(ProviderSetupStore.Copy.checking)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 6)
            } else if setup.readiness == nil {
                if !setup.message.isEmpty {
                    OnboardingMessage(message: setup.message)
                }
                Button("Try again") { Task { await setup.load() } }
                    .font(.subheadline)
            } else if !setup.canAddKey {
                Text(ProviderSetupStore.Copy.managed)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                form
            }
            if setup.readiness != nil && !setup.message.isEmpty {
                OnboardingMessage(message: setup.message)
            }
            if let skip {
                Button(skip.label) { skip.action() }
                    .font(.subheadline)
                    .disabled(setup.busy)
            }
        }
        .task {
            if setup.readiness == nil { await setup.load() }
        }
    }

    // MARK: Form

    private var form: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let existing = setup.existingKey, existing.gatewayReady == true {
                NoticeBanner(message: "Your AI is connected: \(providerName(existing.provider)), \(existing.modelLabel).",
                             symbol: "checkmark.circle.fill")
            }

            VStack(alignment: .leading, spacing: 6) {
                OnboardingFieldLabel("Provider")
                NavigationLink {
                    ProviderPickerView(providers: setup.rules.providers, selection: setup.provider) { id in
                        setup.selectProvider(id)
                    }
                } label: {
                    OnboardingPickerLabel(value: setup.selectedProvider?.name ?? setup.provider)
                        .onboardingField()
                }
                .buttonStyle(.plain)
                if let info = setup.selectedProvider?.info {
                    Text(info)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                OnboardingFieldLabel(setup.keyOptional ? "Key (optional)" : "Key")
                SecureField(setup.keyOptional ? "Leave empty for a self-hosted server" : "Your key", text: $setup.apiKey)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .onSubmit(onSubmit)
                    .onboardingField()
            }

            if setup.needsAddress {
                VStack(alignment: .leading, spacing: 6) {
                    OnboardingFieldLabel("Address")
                    TextField(addressPlaceholder, text: $setup.baseURL)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.go)
                        .onSubmit(onSubmit)
                        .onboardingField()
                }
            }

            modelRow

            if let model = setup.selectedModel {
                Text(capabilityNote(vision: model.vision))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private var modelRow: some View {
        if let provider = setup.selectedProvider, !provider.models.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                OnboardingFieldLabel("Model")
                NavigationLink {
                    ModelPickerView(provider: provider, selection: setup.model) { id in
                        setup.model = id
                    }
                } label: {
                    OnboardingPickerLabel(value: setup.selectedModel?.label ?? (setup.model.isEmpty ? "Choose a model" : setup.typedModelName),
                                          placeholder: setup.model.isEmpty)
                        .onboardingField()
                }
                .buttonStyle(.plain)
            }
        } else {
            VStack(alignment: .leading, spacing: 6) {
                OnboardingFieldLabel("Model name")
                TextField("model-name", text: Binding(get: { setup.typedModelName }, set: { setup.setTypedModelName($0) }))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .onSubmit(onSubmit)
                    .onboardingField()
            }
        }
    }

    private var addressPlaceholder: String {
        setup.selectedProvider?.requiresBaseURL == true ? "http://localhost:11434" : "https://api.example.com/v1"
    }

    private func providerName(_ id: String) -> String {
        setup.rules.provider(id)?.name ?? id
    }

    private func capabilityNote(vision: Bool) -> String {
        switch setup.modality {
        case .text:
            return vision ? "This model reads text and images. You can skip the next step." : "You can add an image model on the next step."
        case .vision:
            return vision ? "This model reads images." : "This model reads text only. Pick one that reads images."
        }
    }
}
