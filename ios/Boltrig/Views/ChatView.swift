import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var draft = ""
    @FocusState private var isComposerFocused: Bool

    private var chat: ChatSession { store.chat }

    var body: some View {
        NavigationStack {
            ChatThread(chat: chat, draft: $draft, isComposerFocused: $isComposerFocused, onOpenToday: { store.selectedTab = .today })
            .background(BoltrigTheme.groupedBackground.ignoresSafeArea())
            .navigationTitle(chat.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        isComposerFocused = false
                        store.selectedTab = .today
                    } label: {
                        HStack(spacing: 4) { Image(systemName: "chevron.backward"); Text("Today") }
                    }
                    .accessibilityLabel("Back to Today")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        store.startNewChat()
                        isComposerFocused = true
                    } label: { Image(systemName: "square.and.pencil") }
                    .accessibilityLabel("New chat")
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { Task { await chat.reconnectIfRunning() } }
            }
        }
    }
}

/// The thread and composer, observing the chat session directly.
private struct ChatThread: View {
    @ObservedObject var chat: ChatSession
    @Binding var draft: String
    var isComposerFocused: FocusState<Bool>.Binding
    let onOpenToday: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            if chat.isPreview {
                Text("Preview workspace. Sign in to put Boltrig to work.")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity).padding(.vertical, 8)
                    .background(BoltrigTheme.accent.opacity(0.08))
            }
            if chat.needsYouDuringTurn {
                Button(action: onOpenToday) {
                    HStack(spacing: 8) {
                        Image(systemName: "hand.raised.fill")
                        Text("Boltrig needs a decision from you. Open Today.").font(.footnote.weight(.medium))
                        Spacer()
                        Image(systemName: "chevron.right").font(.footnote)
                    }
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(Color.orange.opacity(0.14))
                }
                .buttonStyle(.plain)
            }
            if let notice = chat.notice {
                Text(notice).font(.footnote).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity).padding(.vertical, 6).padding(.horizontal, 16)
                    .background(BoltrigTheme.accent.opacity(0.06))
            }
            thread
            composer
        }
    }

    private var thread: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    if chat.messages.isEmpty && chat.liveReply.isEmpty && !chat.isLoadingHistory {
                        VStack(spacing: 18) {
                            FamiliarPresenceView(surface: "chat", presentation: .hero, mode: chat.presenceMode, level: chat.speakingLevel, size: 220)
                            Text("Ask Familiar to research, organise, or move work forward.")
                                .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity).padding(.top, 48)
                    } else {
                        FamiliarPresenceView(surface: "chat", presentation: .conversation, mode: chat.presenceMode, level: chat.speakingLevel, size: 96)
                            .frame(maxWidth: .infinity).padding(.bottom, 4)
                        if chat.isLoadingHistory {
                            ProgressView().frame(maxWidth: .infinity).padding(.vertical, 12)
                        }
                        if let historyError = chat.historyError {
                            VStack(spacing: 8) {
                                Text("This conversation could not be loaded.").font(.subheadline)
                                Text(historyError).font(.footnote).foregroundStyle(.secondary)
                                Button("Try again") { Task { await chat.loadHistory() } }.buttonStyle(.bordered)
                            }
                            .frame(maxWidth: .infinity)
                        }
                        ForEach(chat.messages) { message in
                            MessageBubble(role: message.role, text: message.content).id(message.id)
                        }
                    }
                    ForEach(Array(chat.receipts.enumerated()), id: \.offset) { _, receipt in
                        ReceiptLine(text: receipt)
                    }
                    if let question = chat.pendingQuestion {
                        QuestionCard(question: question) { answer in Task { await chat.answerQuestion(answer) } }
                            .id("question")
                    }
                    if !chat.liveReply.isEmpty {
                        MessageBubble(role: .assistant, text: chat.liveReply).id("live")
                    } else if chat.isSending || chat.isReconnecting {
                        HStack(spacing: 9) {
                            ProgressView().controlSize(.small)
                            Text(chat.isReconnecting ? "Picking up where it left off" : "Boltrig is working on it")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 4).id("sending")
                    }
                }
                .padding(.horizontal, 18).padding(.top, 18).padding(.bottom, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: chat.messages.count) { _, _ in
                if let last = chat.messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
            }
            .onChange(of: chat.liveReply.count) { _, _ in proxy.scrollTo("live", anchor: .bottom) }
            .onChange(of: chat.pendingQuestion) { _, _ in proxy.scrollTo("question", anchor: .bottom) }
        }
    }

    private var composer: some View {
        VStack(spacing: 6) {
            if !chat.attachments.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(chat.attachments, id: \.name) { attachment in
                            AttachmentChip(name: attachment.name) { chat.removeAttachment(named: attachment.name) }
                        }
                    }
                    .padding(.horizontal, 14)
                }
            }
            HStack(alignment: .bottom, spacing: 9) {
                TextField("Ask Boltrig", text: $draft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...5)
                    .focused(isComposerFocused)
                    .padding(.horizontal, 14).padding(.vertical, 12)
                    .background(BoltrigTheme.card, in: RoundedRectangle(cornerRadius: 18))
                    .onSubmit { send() }

                if chat.isSending || chat.isReconnecting {
                    Button { chat.stopTurn() } label: {
                        Image(systemName: "stop.fill").font(.body.weight(.bold))
                            .foregroundStyle(BoltrigTheme.onControl)
                            .frame(width: 42, height: 42)
                            .background(BoltrigTheme.control.opacity(0.8), in: Circle())
                    }
                    .accessibilityLabel("Stop")
                } else {
                    Button(action: send) {
                        Image(systemName: "arrow.up").font(.body.weight(.bold))
                            .foregroundStyle(BoltrigTheme.onControl)
                            .frame(width: 42, height: 42)
                            .background(BoltrigTheme.control, in: Circle())
                    }
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .opacity(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.45 : 1)
                    .accessibilityLabel("Send message")
                }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(.ultraThinMaterial)
    }

    private func send() {
        let value = draft
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !chat.isSending else { return }
        draft = ""
        Task { await chat.sendMessage(value) }
    }
}
