import SwiftUI

/// Step one: the name Boltrig greets the person by.
struct NameStepView: View {
    @ObservedObject var store: OnboardingStore
    @FocusState private var focused: Bool

    var body: some View {
        OnboardingCard(kicker: "First things first", title: "What should Boltrig call you?", lead: "This is how Boltrig will greet you.") {
            VStack(alignment: .leading, spacing: 6) {
                OnboardingFieldLabel("Your name")
                TextField("Your name", text: $store.name)
                    .textContentType(.name)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .focused($focused)
                    .onSubmit { Task { await store.continueFlow() } }
                    .onboardingField()
            }
            if let message = store.nameMessage {
                OnboardingMessage(message: message)
            }
        }
        .onAppear { focused = true }
    }
}
