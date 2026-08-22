import SwiftUI

/// First-run setup: the frame around the four steps, the step marker, Back and the one
/// forward button. Enter on a field advances the same way the button does.
struct OnboardingFlowView: View {
    @ObservedObject var store: OnboardingStore

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    header
                    stepView
                    if let finishMessage = store.finishMessage {
                        OnboardingMessage(message: finishMessage)
                    }
                    actions
                }
                .padding(.horizontal, 24)
                .padding(.top, 32)
                .padding(.bottom, 40)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
                .animation(.easeInOut(duration: 0.2), value: store.step)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(BoltrigTheme.groupedBackground.ignoresSafeArea())
        }
    }

    private var header: some View {
        VStack(spacing: 14) {
            BrandMark(size: 64)
            Text("Boltrig")
                .font(.system(size: 26, weight: .heavy, design: .default))
                .tracking(-0.5)
            progress
        }
        .padding(.bottom, 4)
    }

    private var progress: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                ForEach(0..<OnboardingStore.stepCount, id: \.self) { index in
                    Capsule()
                        .fill(index <= store.step.rawValue ? BoltrigTheme.accent : Color.secondary.opacity(0.25))
                        .frame(width: index == store.step.rawValue ? 22 : 8, height: 8)
                }
            }
            Text("Step \(store.stepNumber) of \(OnboardingStore.stepCount)")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(store.stepNumber) of \(OnboardingStore.stepCount)")
    }

    @ViewBuilder
    private var stepView: some View {
        switch store.step {
        case .name:
            NameStepView(store: store)
        case .provider:
            ProviderStepView(
                setup: store.text,
                title: "Connect your AI",
                lead: "Boltrig works through an AI provider you choose. Your key is sent once and kept safe; it is never shown again.",
                onSubmit: advance
            )
        case .vision:
            VisionStepView(store: store)
        case .ready:
            ReadyStepView(name: store.name)
        }
    }

    private var actions: some View {
        HStack(spacing: 12) {
            if store.canGoBack {
                Button("Back") { store.back() }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
            }
            OnboardingPrimaryButton(title: store.primaryLabel, busy: store.isBusy, enabled: store.canContinue, action: advance)
        }
    }

    private func advance() {
        Task { await store.continueFlow() }
    }
}
