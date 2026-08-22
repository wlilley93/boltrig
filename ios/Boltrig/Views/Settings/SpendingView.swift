import SwiftUI

/// Spending: what work has cost and the ceilings on it. Read-only; ceilings are set on the web.
struct SpendingView: View {
    @EnvironmentObject private var settings: AccountSettingsStore

    var body: some View {
        List {
            SettingsNoticeSection(message: settings.notice)

            Section {
                HStack {
                    Text("Spent so far")
                    Spacer()
                    if let cost = settings.cost {
                        Text(cost.totalLabel)
                            .foregroundStyle(.secondary)
                    } else if settings.isLoading {
                        ProgressView()
                    } else {
                        Text("Not known yet")
                            .foregroundStyle(.secondary)
                    }
                }
            } footer: {
                Text("Everything Boltrig has spent on your behalf, across the work you can see.")
            }

            Section {
                if settings.budgets.isEmpty {
                    SettingsEmptyRow(text: settings.isLoading ? "Checking" : "No ceiling is set.")
                } else {
                    ForEach(settings.budgets) { budget in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(budget.title)
                                Spacer()
                                Text(budget.spentLabel)
                                    .foregroundStyle(.secondary)
                            }
                            Text(budget.note)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }
            } header: {
                Text("Ceilings")
            } footer: {
                Text("Read-only here. Limits are set on the web.")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Spending")
        .navigationBarTitleDisplayMode(.large)
        .task { await settings.loadSpending() }
        .refreshable { await settings.loadSpending() }
    }
}
