import AppIntents
import Foundation

// Siri and Shortcuts. These run inside the app's process (no extension), using the pairing the app already has.

enum IntentError: Error, CustomLocalizedStringResourceConvertible {
    case notPaired
    case noList
    case noSuchPerson
    case nothingToTick

    var localizedStringResource: LocalizedStringResource {
        switch self {
        case .notPaired: "Open Moonlight on this device and pair it first."
        case .noList: "There's no list to add to yet. Make one in Moonlight first."
        case .noSuchPerson: "I couldn't find that person in Moonlight."
        case .nothingToTick: "There are no chores left to tick off today."
        }
    }
}

enum IntentSupport {
    static func client() async throws -> APIClient {
        guard let token = Credentials.token, let server = await Credentials.reachableServer() else { throw IntentError.notPaired }
        return APIClient(baseURL: server, token: token)
    }

    static func dates(_ api: APIClient) async -> Dates {
        Dates(timezone: (try? await api.settings())?.timezone)
    }

    /// "milk, eggs and bread" -> ["milk", "eggs", "bread"]
    static func splitItems(_ text: String) -> [String] {
        text.replacingOccurrences(of: " and ", with: ",")
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
    }

    static func sentenceList(_ parts: [String]) -> String {
        switch parts.count {
        case 0: ""
        case 1: parts[0]
        default: parts.dropLast().joined(separator: ", ") + " and " + parts.last!
        }
    }
}

// MARK: Entities

struct PersonEntity: AppEntity {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Family member"
    static var defaultQuery: PersonQuery { PersonQuery() }
    let id: String
    let name: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(name)") }
}

struct PersonQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [PersonEntity] {
        try await all().filter { identifiers.contains($0.id) }
    }
    func suggestedEntities() async throws -> [PersonEntity] { try await all() }
    private func all() async throws -> [PersonEntity] {
        try await IntentSupport.client().people().map { PersonEntity(id: $0.id, name: $0.name) }
    }
}

struct ListEntity: AppEntity {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "List"
    static var defaultQuery: ListQuery { ListQuery() }
    let id: String
    let name: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(name)") }
}

struct ListQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [ListEntity] {
        try await all().filter { identifiers.contains($0.id) }
    }
    func suggestedEntities() async throws -> [ListEntity] { try await all() }
    private func all() async throws -> [ListEntity] {
        try await IntentSupport.client().lists().map { ListEntity(id: $0.id, name: $0.name) }
    }
}

/// One of today's chores that isn't done yet.
struct ChoreEntity: AppEntity {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Chore"
    static var defaultQuery: ChoreQuery { ChoreQuery() }
    let id: String
    let title: String
    let person: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(title)", subtitle: "\(person)") }
}

struct ChoreQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [ChoreEntity] {
        try await today(includeDone: true).filter { identifiers.contains($0.id) }
    }
    func suggestedEntities() async throws -> [ChoreEntity] { try await today(includeDone: false) }
    private func today(includeDone: Bool) async throws -> [ChoreEntity] {
        let api = try await IntentSupport.client()
        let d = await IntentSupport.dates(api)
        let people = try await api.people()
        return try await api.chores(d.today)
            .filter { includeDone || !$0.completed }
            .map { c in ChoreEntity(id: c.id, title: "\(c.emoji) \(c.title)".trimmingCharacters(in: .whitespaces),
                                    person: people.first { $0.id == c.person_id }?.name ?? "") }
    }
}

// MARK: Intents

struct TodayIntent: AppIntent {
    static let title: LocalizedStringResource = "What's on today"
    static let description = IntentDescription("Hear what's left on the family calendar today.")

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try await IntentSupport.client()
        let d = await IntentSupport.dates(api)
        let today = d.today
        let people = try await api.people()
        let events = try await api.events(today, d.addDays(today, 1))
            .filter { $0.all_day || $0.end > d.now }
            .sorted { ($0.all_day ? 0 : 1, $0.start) < ($1.all_day ? 0 : 1, $1.start) }
        guard !events.isEmpty else { return .result(dialog: "Nothing else is planned for today.") }
        let parts = events.prefix(6).map { e -> String in
            let names = e.person_ids.compactMap { id in people.first { $0.id == id }?.name }
            let who = e.busy == nil && !names.isEmpty && names.count < people.count ? " for \(IntentSupport.sentenceList(names))" : ""
            return e.all_day ? "\(e.displayTitle(people))\(who) all day" : "\(e.displayTitle(people))\(who) at \(d.time(e.start))"
        }
        let more = events.count > 6 ? ", and \(events.count - 6) more" : ""
        return .result(dialog: "Today: \(IntentSupport.sentenceList(parts))\(more).")
    }
}

struct DinnerIntent: AppIntent {
    static let title: LocalizedStringResource = "What's for dinner"
    static let description = IntentDescription("Hear tonight's dinner from the meal plan.")

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try await IntentSupport.client()
        let d = await IntentSupport.dates(api)
        let meals = try await api.meals(d.today, d.addDays(d.today, 2))
        if let tonight = meals.first(where: { $0.date == d.today && $0.slot == "dinner" }) {
            return .result(dialog: "Tonight it's \(tonight.title).")
        }
        if let tomorrow = meals.first(where: { $0.date == d.addDays(d.today, 1) && $0.slot == "dinner" }) {
            return .result(dialog: "Nothing's planned for tonight. Tomorrow it's \(tomorrow.title).")
        }
        return .result(dialog: "Nothing's planned for dinner yet.")
    }
}

struct StarsIntent: AppIntent {
    static let title: LocalizedStringResource = "Check stars"
    static let description = IntentDescription("Hear how many stars someone has.")

    @Parameter(title: "Person") var person: PersonEntity

    static var parameterSummary: some ParameterSummary { Summary("How many stars does \(\.$person) have") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try await IntentSupport.client()
        guard let bal = try await api.points().first(where: { $0.person_id == person.id }) else { throw IntentError.noSuchPerson }
        let rewards = try await api.rewards().filter { $0.person_id == nil || $0.person_id == person.id }.sorted { $0.cost < $1.cost }
        let next = rewards.first { $0.cost > bal.balance }
        let tail = next.map { " \($0.cost - bal.balance) more for \($0.title)." } ?? ""
        return .result(dialog: "\(person.name) has \(bal.balance) star\(bal.balance == 1 ? "" : "s").\(tail)")
    }
}

struct AddToListIntent: AppIntent {
    static let title: LocalizedStringResource = "Add to a list"
    static let description = IntentDescription("Add things to the shopping list (or another list). Say several at once: \"milk, eggs and bread\".")

    @Parameter(title: "Item", requestValueDialog: "What should I add?") var item: String
    @Parameter(title: "List") var list: ListEntity?

    static var parameterSummary: some ParameterSummary { Summary("Add \(\.$item) to \(\.$list)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try await IntentSupport.client()
        let lists = try await api.lists()
        let chosen = list.flatMap { l in lists.first { $0.id == l.id } }
        guard let target = chosen ?? lists.first(where: { $0.kind == "grocery" }) ?? lists.first else { throw IntentError.noList }
        let parts = IntentSupport.splitItems(item)
        for p in parts { try await api.addItem(target.id, title: p) }
        return .result(dialog: "Added \(IntentSupport.sentenceList(parts)) to \(target.name).")
    }
}

struct CompleteChoreIntent: AppIntent {
    static let title: LocalizedStringResource = "Tick off a chore"
    static let description = IntentDescription("Mark one of today's chores as done and add its stars.")

    @Parameter(title: "Chore", requestValueDialog: "Which chore?") var chore: ChoreEntity

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try await IntentSupport.client()
        let d = await IntentSupport.dates(api)
        try await api.setChore(chore.id, date: d.today, done: true)
        return .result(dialog: "Done: \(chore.title) for \(chore.person). Well done!")
    }
}

struct MoonlightShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: TodayIntent(), phrases: [
            "What's on today in \(.applicationName)",
            "What's happening today in \(.applicationName)",
            "Ask \(.applicationName) what's on today",
        ], shortTitle: "Today", systemImageName: "sun.horizon")
        AppShortcut(intent: DinnerIntent(), phrases: [
            "What's for dinner in \(.applicationName)",
            "Ask \(.applicationName) what's for dinner",
        ], shortTitle: "Dinner", systemImageName: "fork.knife")
        AppShortcut(intent: AddToListIntent(), phrases: [
            "Add to the shopping list in \(.applicationName)",
            "Add something to \(.applicationName)",
            "Add to \(\.$list) in \(.applicationName)",
        ], shortTitle: "Add to list", systemImageName: "cart.badge.plus")
        AppShortcut(intent: StarsIntent(), phrases: [
            "How many stars does \(\.$person) have in \(.applicationName)",
            "Check stars in \(.applicationName)",
        ], shortTitle: "Stars", systemImageName: "star")
        AppShortcut(intent: CompleteChoreIntent(), phrases: [
            "Tick off a chore in \(.applicationName)",
            "Mark a chore done in \(.applicationName)",
        ], shortTitle: "Chore done", systemImageName: "checkmark.circle")
    }
}
