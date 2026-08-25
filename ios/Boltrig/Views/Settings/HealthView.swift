import SwiftUI

/// Health: what is working and what is not, one plain line per check.
struct HealthView: View {
    @EnvironmentObject private var settings: AccountSettingsStore

    var body: some View {
        List {
            SettingsNoticeSection(message: settings.notice)

            if let report = settings.readiness {
                Section {
                    HStack(spacing: 10) {
                        StatusDot(color: report.ready ? .green : .orange)
                        Text(report.ready ? "Everything is working" : "Something is not working")
                            .font(.body.weight(.semibold))
                    }
                    .padding(.vertical, 2)
                }

                Section {
                    ForEach(report.checks) { check in
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(check.label)
                                if !check.required {
                                    Text("Optional")
                                        .font(.footnote)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            Text(check.statusLabel)
                                .foregroundStyle(color(for: check))
                        }
                        .accessibilityElement(children: .combine)
                    }
                } footer: {
                    Text("Optional checks do not stop Boltrig from working.")
                }
            } else if settings.isLoading {
                Section {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .listRowBackground(Color.clear)
                }
            } else {
                Section {
                    SettingsEmptyRow(text: "Health is not known yet.")
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Health")
        .navigationBarTitleDisplayMode(.large)
        .task { await settings.loadReadiness() }
        .refreshable { await settings.loadReadiness() }
    }

    private func color(for check: ReadinessReport.Check) -> Color {
        if check.isWorking { return .secondary }
        if check.status == "failed" { return check.required ? .orange : .secondary }
        return Color(uiColor: .tertiaryLabel)
    }
}
