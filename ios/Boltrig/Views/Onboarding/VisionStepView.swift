import SwiftUI

/// Step three, optional: a model that reads images. Skipping submits nothing and finishes setup.
struct VisionStepView: View {
    @ObservedObject var store: OnboardingStore

    var body: some View {
        ProviderStepView(
            setup: store.vision,
            kicker: "Optional",
            title: "Add an image model",
            lead: "Save a model that can read images now, or skip it for later.",
            skip: (label: "Skip for now", action: { Task { await store.skipVision() } }),
            onSubmit: { Task { await store.continueFlow() } }
        )
    }
}
