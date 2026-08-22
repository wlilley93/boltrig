import SwiftUI

/// Look: the five appearance keys the web stores, written together, plus whether finished
/// replies are read out loud. Theme takes effect on this phone; the rest is the web's.
struct AppearanceView: View {
    @EnvironmentObject private var settings: AccountSettingsStore

    var body: some View {
        List {
            SettingsNoticeSection(message: settings.notice)

            Section {
                labelled("Theme") {
                    Picker("Theme", selection: binding(\.theme)) {
                        Text("System").tag(AppearanceSettings.Theme.system)
                        Text("Dark").tag(AppearanceSettings.Theme.dark)
                        Text("Light").tag(AppearanceSettings.Theme.light)
                    }
                }
                labelled("Density") {
                    Picker("Density", selection: binding(\.density)) {
                        Text("Comfortable").tag(AppearanceSettings.Density.comfortable)
                        Text("Compact").tag(AppearanceSettings.Density.compact)
                    }
                }
                labelled("Text size") {
                    Picker("Text size", selection: binding(\.fontScale)) {
                        Text("Small").tag("0.9")
                        Text("Normal").tag("1")
                        Text("Large").tag("1.1")
                        Text("Extra large").tag("1.25")
                    }
                }
                Toggle("Reduced motion", isOn: binding(\.reducedMotion))
                Toggle("High contrast", isOn: binding(\.highContrast))
            } header: {
                Text("Look")
            } footer: {
                Text("Theme applies here and on the web. Density, text size, motion and contrast apply on the web; this phone follows your iPhone settings.")
            }

            Section {
                Toggle("Read out replies", isOn: Binding(
                    get: { settings.readReplies },
                    set: { value in Task { await settings.setReadReplies(value) } }
                ))
            } header: {
                Text("Voice")
            } footer: {
                Text("Speaks finished replies aloud in Familiar's voice.")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Look")
        .navigationBarTitleDisplayMode(.large)
    }

    /// One key of the appearance; setting it writes all five together.
    private func binding<Value>(_ keyPath: WritableKeyPath<AppearanceSettings, Value>) -> Binding<Value> {
        Binding(
            get: { settings.appearance[keyPath: keyPath] },
            set: { value in
                var next = settings.appearance
                next[keyPath: keyPath] = value
                Task { await settings.saveAppearance(next) }
            }
        )
    }

    private func labelled<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
            content()
                .pickerStyle(.segmented)
                .labelsHidden()
        }
        .padding(.vertical, 4)
    }
}
