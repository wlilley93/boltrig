import SwiftUI

/// The sign-in ceremony, one screen per state the session can be in before it is signed in.
struct AuthFlowView: View {
    @EnvironmentObject private var session: SessionStore
    let onExplorePreview: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    header
                    screen
                }
                .padding(.horizontal, 24)
                .padding(.top, 32)
                .padding(.bottom, 40)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
        }
    }

    private var header: some View {
        VStack(spacing: 14) {
            BrandMark(size: 84)
            Text("Boltrig")
                .font(.system(size: 30, weight: .heavy, design: .default))
                .tracking(-0.6)
        }
        .padding(.bottom, 4)
    }

    @ViewBuilder
    private var screen: some View {
        switch session.state {
        case .signedOut, .signingIn:
            SignInForm(onExplorePreview: onExplorePreview)
        case .twoFactor:
            TwoFactorForm()
        case .passwordChange:
            PasswordChangeForm()
        case let .twoFactorEnrolment(_, enrolment):
            TwoFactorEnrolmentForm(enrolment: enrolment)
        case let .recoveryCodes(_, codes):
            RecoveryCodesForm(codes: codes)
        default:
            ProgressView()
        }
    }
}

// MARK: - Shared pieces

private struct AuthCard<Content: View>: View {
    let title: String
    let lead: String?
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.title2.weight(.semibold))
                if let lead {
                    Text(lead)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            content
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}

private struct AuthMessage: View {
    let message: String

    var body: some View {
        Text(message)
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(BoltrigTheme.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
            .accessibilityAddTraits(.isStaticText)
    }
}

private struct PrimaryButton: View {
    let title: String
    let busy: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if busy { ProgressView().controlSize(.small).tint(BoltrigTheme.onControl) }
                Text(busy ? "One moment" : title)
            }
            .foregroundStyle(BoltrigTheme.onControl)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .tint(BoltrigTheme.control)
        .disabled(busy)
    }
}

private extension View {
    func authField() -> some View {
        self
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Color(uiColor: .tertiarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: - Sign in

private struct SignInForm: View {
    @EnvironmentObject private var session: SessionStore
    @State private var email = ""
    @State private var password = ""
    @State private var showingInstance = false
    @FocusState private var focus: Field?
    let onExplorePreview: () -> Void

    private enum Field { case email, password }

    var body: some View {
        VStack(spacing: 16) {
            AuthCard(title: "Sign in", lead: "Use the email and password from your invitation.") {
                TextField("Email", text: $email)
                    .textContentType(.username)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.next)
                    .focused($focus, equals: .email)
                    .onSubmit { focus = .password }
                    .authField()

                SecureField("Password", text: $password)
                    .textContentType(.password)
                    .submitLabel(.go)
                    .focused($focus, equals: .password)
                    .onSubmit { signIn() }
                    .authField()

                if let message = session.errorMessage {
                    AuthMessage(message: message)
                }

                PrimaryButton(title: "Sign in", busy: session.isBusy, action: signIn)

                Button("Forgotten your password?") {
                    Task { await session.requestPasswordReset(email: email) }
                }
                .font(.subheadline)
                .disabled(session.isBusy)
            }

            VStack(spacing: 10) {
                Button {
                    showingInstance = true
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "server.rack")
                        Text(session.isHostedInstance ? "Connected to Boltrig" : "Connected to \(session.instanceLabel)")
                    }
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }
                #if DEBUG
                Button("Explore the preview workspace") { onExplorePreview() }
                    .font(.footnote)
                #endif
            }
        }
        .sheet(isPresented: $showingInstance) {
            InstanceSheet()
                .environmentObject(session)
        }
    }

    private func signIn() {
        focus = nil
        Task { await session.signIn(email: email, password: password) }
    }
}

// MARK: - Two-step code

private struct TwoFactorForm: View {
    @EnvironmentObject private var session: SessionStore
    @State private var code = ""
    @FocusState private var focused: Bool

    var body: some View {
        AuthCard(title: "Two-step verification", lead: "Enter the code from your authenticator app, or one of your recovery codes.") {
            TextField("Code", text: $code)
                .textContentType(.oneTimeCode)
                .keyboardType(.asciiCapable)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(.system(.title3, design: .monospaced))
                .focused($focused)
                .submitLabel(.go)
                .onSubmit(submit)
                .authField()

            if let message = session.errorMessage {
                AuthMessage(message: message)
            }

            PrimaryButton(title: "Continue", busy: session.isBusy, action: submit)

            Button("Start again") { session.cancelSignIn() }
                .font(.subheadline)
        }
        .onAppear { focused = true }
    }

    private func submit() {
        Task { await session.submitTwoFactorCode(code) }
    }
}

// MARK: - Forced password change

private struct PasswordChangeForm: View {
    @EnvironmentObject private var session: SessionStore
    @State private var current = ""
    @State private var new = ""
    @State private var confirmation = ""

    var body: some View {
        AuthCard(title: "Choose a new password", lead: "Your account needs a new password before you continue. Twelve characters or more.") {
            SecureField("Current password", text: $current)
                .textContentType(.password)
                .authField()
            SecureField("New password", text: $new)
                .textContentType(.newPassword)
                .authField()
            SecureField("New password again", text: $confirmation)
                .textContentType(.newPassword)
                .authField()

            if let message = session.errorMessage {
                AuthMessage(message: message)
            }

            PrimaryButton(title: "Save and continue", busy: session.isBusy) {
                Task { await session.changePassword(current: current, new: new, confirmation: confirmation) }
            }

            Button("Start again") { session.cancelSignIn() }
                .font(.subheadline)
        }
    }
}

// MARK: - Two-step setup

private struct TwoFactorEnrolmentForm: View {
    @EnvironmentObject private var session: SessionStore
    let enrolment: TwoFactorEnrolment?
    @State private var code = ""

    var body: some View {
        AuthCard(title: "Set up two-step verification",
                 lead: "Your organisation asks for a second step when signing in. Add Boltrig to an authenticator app, then enter the code it shows.") {
            if let enrolment {
                if let url = URL(string: enrolment.otpauthURI) {
                    Link(destination: url) {
                        Label("Open in your authenticator app", systemImage: "arrow.up.forward.app")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("Or enter this key by hand")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    HStack {
                        Text(enrolment.secret)
                            .font(.system(.footnote, design: .monospaced))
                            .textSelection(.enabled)
                        Spacer()
                        Button {
                            UIPasteboard.general.string = enrolment.secret
                        } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .accessibilityLabel("Copy key")
                    }
                    .authField()
                }
                TextField("Six-digit code", text: $code)
                    .textContentType(.oneTimeCode)
                    .keyboardType(.numberPad)
                    .font(.system(.title3, design: .monospaced))
                    .authField()
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }

            if let message = session.errorMessage {
                AuthMessage(message: message)
            }

            if enrolment != nil {
                PrimaryButton(title: "Verify", busy: session.isBusy) {
                    Task { await session.verifyTwoFactorEnrolment(code: code) }
                }
            }

            Button("Start again") { session.cancelSignIn() }
                .font(.subheadline)
        }
        .task {
            if enrolment == nil { await session.beginTwoFactorEnrolment() }
        }
    }
}

// MARK: - Recovery codes

private struct RecoveryCodesForm: View {
    @EnvironmentObject private var session: SessionStore
    let codes: [String]

    var body: some View {
        AuthCard(title: "Keep these recovery codes",
                 lead: "Each one signs you in once if you lose your authenticator app. They are shown only now.") {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(codes, id: \.self) { code in
                    Text(code)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .authField()

            Button {
                UIPasteboard.general.string = codes.joined(separator: "\n")
            } label: {
                Label("Copy all", systemImage: "doc.on.doc").frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)

            if let message = session.errorMessage {
                AuthMessage(message: message)
            }

            PrimaryButton(title: "I have saved them", busy: session.isBusy) {
                Task { await session.acknowledgeRecoveryCodes() }
            }
        }
    }
}

// MARK: - Instance picker

/// Lets a person point the app at a different Boltrig: a self-hosted box, a preview host.
struct InstanceSheet: View {
    @EnvironmentObject private var session: SessionStore
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(session.instanceLabel)
                        .font(.body.monospaced())
                } header: {
                    Text("Currently connected to")
                }

                Section {
                    TextField("your-boltrig.example.com", text: $text)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    if let problem {
                        Text(problem).font(.footnote).foregroundStyle(.red)
                    }
                    Button("Use this Boltrig") { apply() }
                        .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: {
                    Text("Connect to a different Boltrig")
                } footer: {
                    Text("Only secure (https) addresses are accepted. Changing instance signs you out of the current one.")
                }

                if !session.isHostedInstance {
                    Section {
                        Button("Back to the hosted Boltrig") {
                            Task {
                                await session.useInstance(BoltrigEnvironment.hostedInstanceURL)
                                dismiss()
                            }
                        }
                    }
                }
            }
            .navigationTitle("Boltrig instance")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func apply() {
        guard let url = InstanceAddress.parse(text) else {
            problem = "That does not look like a secure web address."
            return
        }
        Task {
            await session.useInstance(url)
            dismiss()
        }
    }
}
