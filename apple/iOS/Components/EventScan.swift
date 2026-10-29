import PhotosUI
import SwiftUI
import UIKit

/// An event read from a photo of an invitation or flier, not saved yet. The photo comes along as its attachment.
struct EventDraft: Codable, Identifiable {
    var id: String { attachments.first?.id ?? title }
    var title: String
    var start: String
    var end: String
    var all_day: Bool
    var location: String
    var notes: String
    var person_ids: [String]
    var attachments: [EventAttachment]
    /// False when no date was found: the draft is on today, for the family to change.
    var found_date: Bool
}

extension APIClient {
    /// Claude reads the uploaded photo (one Anthropic request). 409 when the add-on has no API key.
    func scanEvent(image: String, today: String) async throws -> EventDraft {
        try await send("POST", "/api/events/scan", ["image": image, "today": today])
    }
}

/// Reads an invitation's words (already read from the photo by Vision) on the phone: the date and time and the
/// address with Apple's data detector, the title and notes from the lines around them. Nothing leaves the phone.
enum InviteReader {
    private static let eventWords = ["party", "birthday", "celebrat", "fair", "festival", "fête", "fete", "gala", "disco",
                                     "bbq", "barbecue", "show", "concert", "wedding", "christening", "baptism", "sleepover",
                                     "quiz", "sale", "match", "picnic", "play", "performance", "open day", "open evening",
                                     "parade", "carnival", "ball", "dinner", "lunch", "brunch", "service", "reunion"]
    private static let noteWords = ["rsvp", "r.s.v.p", "reply", "let us know", "bring", "wear", "dress", "fancy dress",
                                    "theme", "tickets", "£", "$", "€", "cost", "price", "free entry", "please", "parking"]
    private static let skipLines = ["you're invited", "you are invited", "youre invited", "join us", "please come",
                                    "come and", "come along", "invites you", "invite you", "invitation"]

    static func read(_ text: String, people: [Person], now: Date = Date()) -> EventDraft {
        let lines = text.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let joined = lines.joined(separator: "\n")
        let ns = joined as NSString
        let types: NSTextCheckingResult.CheckingType = [.date, .address]
        let matches = (try? NSDataDetector(types: types.rawValue))?.matches(in: joined, range: NSRange(location: 0, length: ns.length)) ?? []

        var cal = Calendar.current
        cal.timeZone = .current
        let startOfToday = cal.startOfDay(for: now)

        // Dates: the first one from today on; a date with no year printed that has passed is next year's.
        var start: Date?
        var end: Date?
        var timed = false
        var used: [NSRange] = []
        for m in matches where m.resultType == .date {
            guard var d = m.date else { continue }
            let s = ns.substring(with: m.range)
            if d < startOfToday, s.range(of: #"\b(19|20)\d{2}\b"#, options: .regularExpression) == nil,
               let next = cal.date(byAdding: .year, value: 1, to: d) { d = next }
            let hasTime = s.range(of: #"\d\s*(am|pm|a\.m|p\.m)|\d{1,2}[:.]\d{2}|noon|midday"#, options: [.regularExpression, .caseInsensitive]) != nil
            let timeOnly = s.range(of: #"^\s*(\d{1,2}([:.]\d{2})?\s*(am|pm|a\.m\.?|p\.m\.?)?|noon|midday)\s*$"#,
                                   options: [.regularExpression, .caseInsensitive]) != nil
            if let first = start {
                // A later time on the same day, or a time on its own, finishes the date: "Sat 14 Nov" then "2-4pm".
                guard hasTime, timeOnly || cal.isDate(d, inSameDayAs: first),
                      let at = cal.date(bySettingHour: cal.component(.hour, from: d), minute: cal.component(.minute, from: d),
                                        second: 0, of: first) else { continue }
                if !timed {
                    start = at
                    timed = true
                } else if end == nil, at > first {
                    end = at
                } else {
                    continue
                }
            } else {
                if d < startOfToday || timeOnly { continue }
                start = d
                timed = hasTime
                if m.duration > 0 { end = d.addingTimeInterval(m.duration) }
            }
            used.append(m.range)
        }

        // Where: the first address, or a line that says where.
        var location = ""
        if let a = matches.first(where: { $0.resultType == .address }) {
            location = ns.substring(with: a.range).components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }.joined(separator: ", ")
            used.append(a.range)
        } else if let l = lines.first(where: { $0.range(of: #"^(where|venue|location|at)\b[:\s]"#, options: [.regularExpression, .caseInsensitive]) != nil }) {
            location = l.replacingOccurrences(of: #"^(where|venue|location|at)\b[:\s]*"#, with: "", options: [.regularExpression, .caseInsensitive])
        }
        let usedText = used.map { ns.substring(with: $0).lowercased() }
        func isUsed(_ l: String) -> Bool { usedText.contains { $0.contains(l.lowercased()) || l.lowercased().contains($0) } }

        // Title: the line that names the event best.
        func score(_ l: String) -> Int {
            let low = l.lowercased()
            if l.count < 3 || l.count > 70 || isUsed(l) || noteWords.contains(where: low.contains) { return -1 }
            var n = 0
            if eventWords.contains(where: low.contains) { n += 3 }
            if low.contains("'s") || low.contains("’s") { n += 1 }
            if skipLines.contains(where: low.contains) { n -= 2 }
            return n
        }
        let ranked = lines.enumerated().map { ($0.offset, score($0.element)) }.filter { $0.1 >= 0 }
        let best = ranked.max { a, b in a.1 != b.1 ? a.1 < b.1 : a.0 > b.0 }
        var title = best.map { lines[$0.0] } ?? ""
        title = title.replacingOccurrences(of: #"^(you'?re|you are) invited( to)?:?\s*|^join us (for|at)\s*|^please come to\s*"#,
                                           with: "", options: [.regularExpression, .caseInsensitive])
        if title == title.uppercased() { title = title.capitalized }

        let notes = lines.filter { l in
            let low = l.lowercased()
            return noteWords.contains(where: low.contains) && l != title && !isUsed(l)
        }.joined(separator: "\n")

        let words = Set(joined.lowercased().components(separatedBy: CharacterSet.letters.inverted))
        let who = people.filter { words.contains($0.name.lowercased()) }.map(\.id)

        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.timeZone = .current
        fmt.dateFormat = "yyyy-MM-dd'T'HH:mm"
        let day = start.map { cal.startOfDay(for: $0) } ?? startOfToday
        let s: Date, e: Date
        if let start, timed {
            s = start
            e = end.flatMap { $0 > start ? $0 : nil } ?? start.addingTimeInterval(2 * 3600)
        } else {
            s = day
            e = cal.date(byAdding: .day, value: 1, to: day) ?? day
        }
        return EventDraft(title: String(title.prefix(120)), start: fmt.string(from: s), end: fmt.string(from: e),
                          all_day: !(timed && start != nil), location: location, notes: notes, person_ids: who,
                          attachments: [], found_date: start != nil)
    }
}

/// Scan an invitation or flier: the photo is read on the phone (or by Claude when chosen and the add-on has a key)
/// into a draft event for the editor. The photo is kept with the event.
struct EventScanView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var onDraft: (EventDraft) -> Void

    @State private var image: UIImage?
    @State private var scanning = false
    @State private var camera = false
    @State private var pick: PhotosPickerItem?
    @State private var reader: RecipeReader?
    @AppStorage("eventScanUsesClaude") private var useClaude = false
    @State private var busy: String?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if let image {
                        Image(uiImage: image).resizable().scaledToFit()
                            .frame(maxHeight: 280)
                            .frame(maxWidth: .infinity)
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                    if DocumentScanner.isAvailable {
                        Button { scanning = true } label: { Label(image == nil ? "Scan it" : "Scan again", systemImage: "doc.viewfinder") }
                    } else if CameraPicker.isAvailable {
                        Button { camera = true } label: { Label("Take a photo", systemImage: "camera") }
                    }
                    PhotosPicker(selection: $pick, matching: .images) {
                        Label("Choose a photo", systemImage: "photo.on.rectangle")
                    }
                } footer: {
                    Text("A party invitation, a school letter or an event poster. The photo is kept with the event.")
                }
                Section {
                    if reader?.configured == true { Toggle("Read with Claude", isOn: $useClaude) }
                } footer: {
                    Text(reader?.configured == true && useClaude
                         ? "The photo is sent to Claude, Anthropic's AI, in one short request. Better with handwriting and fancy lettering."
                         : "The words are read here on your phone, nothing is sent to an AI. You check everything before it's added.")
                }
                if let error {
                    Section { Text(error).foregroundStyle(Theme.danger) }
                }
            }
            .navigationTitle("Scan an invite")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if let busy {
                        HStack(spacing: 6) { ProgressView(); Text(busy).font(.footnote) }
                    } else {
                        Button("Read it") { Task { await run() } }.disabled(image == nil)
                    }
                }
            }
            .fullScreenCover(isPresented: $scanning) {
                DocumentScanner { pages in
                    if let first = pages.first { image = first }
                    scanning = false
                } onCancel: {
                    scanning = false
                }
                .ignoresSafeArea()
            }
            .fullScreenCover(isPresented: $camera) {
                CameraPicker { image = $0 }.ignoresSafeArea()
            }
            .onChange(of: pick) { _, item in
                Task {
                    if let data = try? await item?.loadTransferable(type: Data.self), let img = UIImage(data: data) { image = img }
                }
            }
            .task {
                reader = await model.call { try await $0.recipeReader() }
                if image == nil && DocumentScanner.isAvailable { scanning = true }
            }
        }
    }

    private func run() async {
        guard let api = model.api, let image else { return }
        error = nil
        defer { busy = nil }
        do {
            busy = "Uploading…"
            guard let jpeg = image.jpeg(max: 2000, quality: 0.85) else { error = "Couldn't use that photo."; return }
            let pic = try await api.uploadImage(jpeg)
            let attachment = EventAttachment(id: pic.id, url: pic.url)
            var draft: EventDraft
            if useClaude && reader?.configured == true {
                busy = "Claude is reading it…"
                draft = try await api.scanEvent(image: pic.id, today: model.dates.today)
            } else {
                busy = "Reading the words…"
                let words = await TextReader.read([image])
                draft = InviteReader.read(words, people: model.people)
                draft.attachments = [attachment]
            }
            dismiss()
            onDraft(draft)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// An event's pictures as thumbnails; tap one to see it whole.
struct EventPictures: View {
    let pictures: [EventAttachment]
    var onRemove: ((EventAttachment) -> Void)? = nil
    @State private var open: EventAttachment?

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(pictures) { p in
                    Button { open = p } label: {
                        RemoteImage(path: p.url)
                            .frame(width: 90, height: 120)
                            .background(Theme.surface)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Show the picture")
                    .overlay(alignment: .topTrailing) {
                        if let onRemove {
                            Button { onRemove(p) } label: {
                                Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette)
                                    .foregroundStyle(.white, .black.opacity(0.6))
                            }
                            .padding(4)
                            .accessibilityLabel("Remove the picture")
                        }
                    }
                }
            }
            .padding(.vertical, 4)
        }
        .fullScreenCover(item: $open) { p in
            ZStack(alignment: .topTrailing) {
                Color.black.ignoresSafeArea()
                RemoteImage(path: p.url, contentMode: .fit)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                Button { open = nil } label: {
                    Image(systemName: "xmark.circle.fill").font(.largeTitle).symbolRenderingMode(.palette)
                        .foregroundStyle(.white, .white.opacity(0.25))
                }
                .padding()
                .accessibilityLabel("Close")
            }
        }
    }
}
