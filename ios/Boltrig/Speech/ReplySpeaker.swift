import AVFoundation
import Combine
import Foundation

/// What plays the audio. The real one wraps AVAudioPlayer; tests use a fake.
protocol AudioPlaying: AnyObject {
    var isPlaying: Bool { get }
    /// 0..1 loudness of what is playing right now.
    var level: Double { get }
    var onFinished: (() -> Void)? { get set }
    func play(_ data: Data) throws
    func stop()
}

/// Reads finished replies aloud in Familiar's voice: one request to the server per reply,
/// one WAV back, played here. Every failure is silent; a reply that cannot be spoken is
/// still on the screen.
@MainActor
final class ReplySpeaker: ObservableObject {
    @Published private(set) var isSpeaking = false
    @Published private(set) var level: Double = 0
    @Published var resolution: SpeechResolution = .silent

    static let maxAudioBase64 = 12_000_000

    private let player: AudioPlaying
    private let client: BoltrigClient?
    private var spokenRuns: Set<String> = []
    private var generation = 0
    private var meter: Task<Void, Never>?

    init(client: BoltrigClient?, player: AudioPlaying) {
        self.client = client
        self.player = player
        self.player.onFinished = { [weak self] in
            Task { @MainActor [weak self] in self?.finish() }
        }
    }

    /// Speaks a reply once per run. Does nothing when reading aloud is off or no voice is bound.
    func speak(runID: String, markdown: String) async {
        guard resolution.canSpeak, let client, let voice = resolution.voiceID else { return }
        guard !spokenRuns.contains(runID) else { return }
        spokenRuns.insert(runID)
        let text = SpeechResolution.speechText(markdown)
        guard !text.isEmpty else { return }
        generation += 1
        let mine = generation
        do {
            let outcome = try await client.invoke(noun: "voice", verb: SpeechResolution.speakVerb, params: ["text": text, "voice": voice])
            guard mine == generation else { return }
            guard case let .ok(output) = outcome,
                  let encoded = output["audio_b64"] as? String, encoded.count <= Self.maxAudioBase64,
                  (output["content_type"] as? String ?? "audio/wav").hasPrefix("audio/"),
                  let data = Data(base64Encoded: encoded), !data.isEmpty else { return }
            try player.play(data)
            isSpeaking = true
            startMetering()
        } catch {
            // Silent by design: no audio is not an error the person needs to see.
        }
    }

    /// Stops speech, forgets nothing: a run already spoken stays spoken.
    func stop() {
        generation += 1
        player.stop()
        finish()
    }

    /// Conversation changed: runs of the old one may be spoken again if replayed.
    func reset() {
        stop()
        spokenRuns.removeAll()
    }

    private func startMetering() {
        meter?.cancel()
        meter = Task { @MainActor [weak self] in
            while let self, self.player.isPlaying, !Task.isCancelled {
                self.level = self.player.level
                try? await Task.sleep(nanoseconds: 33_000_000)
            }
            self?.finish()
        }
    }

    private func finish() {
        meter?.cancel()
        meter = nil
        isSpeaking = false
        level = 0
    }
}

/// AVAudioPlayer behind the protocol, with metering and a spoken-audio session.
final class SystemAudioPlayer: NSObject, AudioPlaying, AVAudioPlayerDelegate {
    private var current: AVAudioPlayer?
    var onFinished: (() -> Void)?

    var isPlaying: Bool { current?.isPlaying ?? false }

    var level: Double {
        guard let current, current.isPlaying else { return 0 }
        current.updateMeters()
        let decibels = Double(current.averagePower(forChannel: 0))
        return min(1, max(0, (decibels + 50) / 50))
    }

    func play(_ data: Data) throws {
        current?.stop()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try session.setActive(true)
        let player = try AVAudioPlayer(data: data)
        player.isMeteringEnabled = true
        player.delegate = self
        current = player
        player.prepareToPlay()
        player.play()
    }

    func stop() {
        current?.stop()
        current = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        current = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        onFinished?()
    }
}
