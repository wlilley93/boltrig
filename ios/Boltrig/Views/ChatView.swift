import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var store: AppStore
    @State private var draft = ""
    @FocusState private var isComposerFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if store.isPreview {
                    Text("Preview workspace. Sign in to put Boltrig to work.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .background(BoltrigTheme.accent.opacity(0.08))
                }

                if store.needsYouDuringTurn {
                    Button {
                        store.selectedTab = .today
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "hand.raised.fill")
                            Text("Boltrig needs a decision from you. Open Today.")
                                .font(.footnote.weight(.medium))
                            Spacer()
                            Image(systemName: "chevron.right").font(.footnote)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(Color.orange.opacity(0.14))
                    }
                    .buttonStyle(.plain)
                }

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 16) {
                            if store.messages.isEmpty && store.liveReply.isEmpty {
                                VStack(spacing: 18) {
                                    FamiliarPresenceView(surface: "chat", presentation: .hero, mode: store.presenceMode, size: 220)
                                    Text("Ask Familiar to research, organise, or move work forward.")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                        .multilineTextAlignment(.center)
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.top, 48)
                            } else {
                                FamiliarPresenceView(surface: "chat", presentation: .conversation, mode: store.presenceMode, size: 96)
                                    .frame(maxWidth: .infinity)
                                    .padding(.bottom, 4)
                                ForEach(store.messages) { message in
                                    MessageBubble(role: message.role, text: message.content)
                                        .id(message.id)
                                }
                            }

                            if !store.liveReply.isEmpty {
                                MessageBubble(role: .assistant, text: store.liveReply)
                                    .id("live")
                            } else if store.isSending {
                                HStack(spacing: 9) {
                                    ProgressView().controlSize(.small)
                                    Text("Boltrig is working on it")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                                .padding(.horizontal, 4)
                                .id("sending")
                            }
                        }
                        .padding(.horizontal, 18)
                        .padding(.top, 18)
                        .padding(.bottom, 12)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .onChange(of: store.messages.count) { _, _ in
                        if let last = store.messages.last {
                            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                        }
                    }
                    .onChange(of: store.liveReply.count) { _, _ in
                        proxy.scrollTo("live", anchor: .bottom)
                    }
                }

                composer
            }
            .background(BoltrigTheme.groupedBackground.ignoresSafeArea())
            .navigationTitle(store.selectedConversationTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        isComposerFocused = false
                        store.selectedTab = .today
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "chevron.backward")
                            Text("Today")
                        }
                    }
                    .accessibilityLabel("Back to Today")
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        store.startNewChat()
                        isComposerFocused = true
                    } label: {
                        Image(systemName: "square.and.pencil")
                    }
                    .accessibilityLabel("New chat")
                }
            }
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 9) {
            TextField("Ask Boltrig", text: $draft, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .focused($isComposerFocused)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(BoltrigTheme.card, in: RoundedRectangle(cornerRadius: 18))
                .onSubmit { send() }

            if store.isSending {
                Button {
                    store.stopTurn()
                } label: {
                    Image(systemName: "stop.fill")
                        .font(.body.weight(.bold))
                        .foregroundStyle(BoltrigTheme.onControl)
                        .frame(width: 42, height: 42)
                        .background(BoltrigTheme.control.opacity(0.8), in: Circle())
                }
                .accessibilityLabel("Stop")
            } else {
                Button(action: send) {
                    Image(systemName: "arrow.up")
                        .font(.body.weight(.bold))
                        .foregroundStyle(BoltrigTheme.onControl)
                        .frame(width: 42, height: 42)
                        .background(BoltrigTheme.control, in: Circle())
                }
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .opacity(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.45 : 1)
                .accessibilityLabel("Send message")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial)
    }

    private func send() {
        let value = draft
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !store.isSending else { return }
        draft = ""
        Task { await store.sendMessage(value) }
    }
}

private struct MessageBubble: View {
    let role: ChatMessage.Role
    let text: String

    var body: some View {
        HStack {
            if role == .user { Spacer(minLength: 42) }

            Text(text)
                .font(.body)
                .foregroundStyle(role == .user ? BoltrigTheme.onControl : Color.primary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 15)
                .padding(.vertical, 12)
                .background(
                    role == .user ? BoltrigTheme.control : BoltrigTheme.card,
                    in: RoundedRectangle(cornerRadius: 18, style: .continuous)
                )
                .textSelection(.enabled)

            if role == .assistant { Spacer(minLength: 42) }
        }
    }
}
