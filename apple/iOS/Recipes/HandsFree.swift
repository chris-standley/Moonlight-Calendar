import AVFoundation
import Foundation
import Observation
import Speech

/// Hands-free cook mode: listens for a few short commands with Apple's speech recognition (on the phone when it can,
/// so nothing is sent away) and reads steps out loud.
@Observable
@MainActor
final class HandsFree {
    enum Command { case next, back, repeatStep, startTimer, stopTimer, ingredients }

    private(set) var listening = false
    private(set) var problem: String?
    var onCommand: ((Command) -> Void)?

    private let audio = AVAudioEngine()
    private let voice = AVSpeechSynthesizer()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var acted = 0         // commands already acted on in the current recognition run
    private let feed = AudioFeed()
    private var restart: Task<Void, Never>?

    /// The commands in what's been heard so far, in order: "next", "back", "repeat", "start the timer", "stop",
    /// "ingredients".
    nonisolated static func commands(in text: String) -> [Command] {
        let words = text.lowercased().split { !$0.isLetter }.map(String.init)
        var out: [Command] = []
        var i = 0
        while i < words.count {
            let w = words[i]
            if ["start", "set"].contains(w), let t = words[(i + 1)..<min(words.count, i + 4)].firstIndex(of: "timer") {
                out.append(.startTimer)
                i = t + 1
                continue
            }
            switch w {
            case "stop", "cancel": out.append(.stopTimer)
            case "next", "forward", "continue": out.append(.next)
            case "back", "previous": out.append(.back)
            case "repeat", "again": out.append(.repeatStep)
            case "ingredients": out.append(.ingredients)
            default: break
            }
            i += 1
        }
        return out
    }

    func start() async {
        problem = nil
        let speech = await withCheckedContinuation { done in SFSpeechRecognizer.requestAuthorization { done.resume(returning: $0) } }
        guard speech == .authorized else { problem = "Allow speech recognition for Moonlight in Settings to use hands-free."; return }
        guard await AVAudioApplication.requestRecordPermission() else {
            problem = "Allow the microphone for Moonlight in Settings to use hands-free."
            return
        }
        recognizer = SFSpeechRecognizer(locale: Locale.current) ?? SFSpeechRecognizer(locale: Locale(identifier: "en-GB"))
        guard let recognizer, recognizer.isAvailable else { problem = "Speech recognition isn't available right now."; return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let input = audio.inputNode
            input.removeTap(onBus: 0)
            Self.tap(input, feed)
            audio.prepare()
            try audio.start()
            listening = true
            begin()
        } catch {
            problem = "Couldn't start listening: \(error.localizedDescription)"
            stop()
        }
    }

    /// The microphone tap runs on an audio thread, so it's set up outside the main actor.
    nonisolated private static func tap(_ input: AVAudioInputNode, _ feed: AudioFeed) {
        input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
            feed.append(buffer)
        }
    }

    func stop() {
        restart?.cancel()
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        feed.request = nil
        if audio.isRunning { audio.stop() }
        audio.inputNode.removeTap(onBus: 0)
        voice.stopSpeaking(at: .immediate)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        listening = false
    }

    func say(_ text: String) {
        voice.stopSpeaking(at: .immediate)
        let u = AVSpeechUtterance(string: text)
        u.rate = AVSpeechUtteranceDefaultSpeechRate * 0.95
        voice.speak(u)
    }

    /// One recognition run. Each run ends after about a minute or a long silence, so a new one starts after it.
    private func begin() {
        guard listening, let recognizer else { return }
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        req.taskHint = .confirmation
        request = req
        feed.request = req
        acted = 0
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let final = result?.isFinal ?? false
            Task { @MainActor in self?.handle(text: text, final: final || error != nil) }
        }
    }

    private func handle(text: String?, final: Bool) {
        // Partial results repeat everything heard so far: act only on commands past the ones already done.
        let cmds = Self.commands(in: text ?? "")
        if cmds.count > acted {
            for c in cmds[acted...] { onCommand?(c) }
            acted = cmds.count
        }
        if final {
            task = nil
            request?.endAudio()
            request = nil
            feed.request = nil
            restart = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(300))
                self?.begin()
            }
        }
    }
}

/// Hands microphone audio from the audio thread to the current recognition request.
private final class AudioFeed: @unchecked Sendable {
    private let lock = NSLock()
    private var _request: SFSpeechAudioBufferRecognitionRequest?

    var request: SFSpeechAudioBufferRecognitionRequest? {
        get { lock.withLock { _request } }
        set { lock.withLock { _request = newValue } }
    }

    func append(_ buffer: AVAudioPCMBuffer) { request?.append(buffer) }
}
