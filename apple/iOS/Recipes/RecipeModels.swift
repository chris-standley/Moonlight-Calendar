import Foundation

// Recipes as API.md describes them, the calls that use them, and how amounts are shown (scaled, with metric alongside).
// The showing part mirrors frontend/src/recipes/recipeText.ts.

struct MetricAmount: Codable, Hashable {
    let quantity: Double
    let quantity_max: Double?
    let unit: String
}

struct Ingredient: Codable, Hashable {
    let text: String
    let quantity: Double?
    let quantity_max: Double?
    let unit: String
    let name: String
    let note: String
    let heading: Bool
    let metric: MetricAmount?
}

struct StepTimer: Codable, Hashable {
    let seconds: Int
    let label: String
}

struct RecipeStep: Codable, Hashable {
    let text: String
    let minutes: Double?
    let photo: String?
    let photo_url: String?
    let timers: [StepTimer]
    let metric_text: String?
    /// Ingredients the step mentions (indexes into the recipe's ingredients), in the order it mentions them.
    let uses: [Int]?

    var shown: String { metric_text ?? text }
}

struct Recipe: Codable, Identifiable, Hashable {
    /// Null for a draft (an import or a preview) that hasn't been saved yet.
    let id: String?
    let title: String
    let emoji: String
    let description: String
    let photo: String?
    let photo_url: String?
    let rating: Int
    let favourite: Bool
    let servings: Int?
    let prep_minutes: Int?
    let cook_minutes: Int?
    let minutes: Int?
    let ingredients: [Ingredient]
    let steps: [RecipeStep]
    let tags: [String]
    let notes: String
    let url: String?
    let cooked_count: Int
    let last_cooked: String?
    /// A key of `RecipeCourse.all`, the cookbook it came from and the page there.
    var course: String? = nil
    var book: String? = nil
    var book_page: Int? = nil

    var key: String { id ?? "draft-\(title)" }
    var defaultServings: Double { Double(servings ?? 1) }
    /// Scale for a chosen number of servings (a multiplier when the recipe doesn't say how many it serves).
    func factor(_ chosen: Double) -> Double { servings.map { chosen / Double($0) } ?? chosen }
}

/// The courses the recipe box is arranged by, in menu order (the add-on's recipe_text.COURSES).
enum RecipeCourse {
    static let all: [(key: String, name: String)] = [
        ("breakfast", "Breakfast & brunch"), ("starter", "Starters"), ("light", "Light bites"), ("main", "Main meals"),
        ("side", "Sides"), ("dessert", "Desserts"), ("baking", "Baking"), ("snack", "Snacks"), ("drink", "Drinks"),
        ("extra", "Sauces & extras"),
    ]
    static func name(_ key: String?) -> String? { all.first { $0.key == key }?.name }
    /// "From Simple, page 212"
    static func bookLine(_ book: String?, _ page: Int?) -> String? {
        guard let book, !book.isEmpty else { return nil }
        return "From \(book)" + (page.map { ", page \($0)" } ?? "")
    }
}

struct RecipeReader: Codable {
    let configured: Bool
    let model: String?
    let key_hint: String?
}

struct UploadedImage: Codable {
    let id: String
    let url: String
}

struct AddedResponse: Codable { let added: Int }

/// A whole cookbook being read by Claude on the server, page by page, with the recipes found so far to check.
struct RecipeBatch: Codable, Identifiable {
    struct Failure: Codable, Hashable { let page: Int; let error: String }
    let id: String
    let pages: Int
    let read: Int
    let reading: Bool
    /// Sent as an Anthropic Message Batch: half price, usually read within the hour, at most a day.
    let cheaper: Bool?
    let book: String?
    let failed: [Failure]
    let saved: Int
    let drafts: [RecipeDraft]
}

struct RecipeDraft: Codable, Identifiable {
    let id: String
    /// Page numbers in the scan, from 1.
    let pages: [Int]
    let recipe: Recipe
}

struct SavedCount: Codable { let saved: Int }

extension APIClient {
    func recipes() async throws -> [Recipe] { try await get("/api/recipes") }
    func recipe(_ id: String) async throws -> Recipe { try await get("/api/recipes/\(id)") }
    @discardableResult
    func saveRecipe(id: String?, _ body: [String: Any]) async throws -> Recipe {
        try await send(id == nil ? "POST" : "PATCH", id.map { "/api/recipes/\($0)" } ?? "/api/recipes", body)
    }
    func deleteRecipe(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/recipes/\(id)")
    }
    func recipeCooked(_ id: String) async throws {
        let _: Ignored = try await send("POST", "/api/recipes/\(id)/cooked", [:])
    }
    func recipeToList(_ id: String, listId: String, items: [String]) async throws -> Int {
        let r: AddedResponse = try await send("POST", "/api/recipes/\(id)/to-list", ["list_id": listId, "items": items])
        return r.added
    }
    func importRecipe(_ body: [String: Any]) async throws -> Recipe { try await send("POST", "/api/recipes/import", body) }
    func previewRecipe(_ body: [String: Any]) async throws -> Recipe { try await send("POST", "/api/recipes/preview", body) }
    func recipeReader() async throws -> RecipeReader { try await get("/api/recipes-reader") }

    func recipeBatches() async throws -> [RecipeBatch] { try await get("/api/recipes-batches") }
    func scanCookbook(images: [String], cheaper: Bool = false, book: String = "") async throws -> RecipeBatch {
        try await send("POST", "/api/recipes-batches", ["images": images, "cheaper": cheaper, "book": book])
    }
    func retryBatch(_ id: String) async throws -> RecipeBatch { try await send("POST", "/api/recipes-batches/\(id)/retry", [:]) }
    func deleteBatch(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/recipes-batches/\(id)")
    }
    func saveAllDrafts(_ batchId: String) async throws -> Int {
        let r: SavedCount = try await send("POST", "/api/recipes-batches/\(batchId)/save-all", [:])
        return r.saved
    }
    /// Save a recipe found in a scan: as read (empty body) or as changed in the editor.
    @discardableResult
    func saveDraft(_ id: String, _ body: [String: Any] = [:]) async throws -> Recipe {
        try await send("POST", "/api/recipe-drafts/\(id)/save", body)
    }
    func dismissDraft(_ id: String) async throws {
        let _: Ignored = try await send("DELETE", "/api/recipe-drafts/\(id)")
    }

    /// A picture as the raw request body (`POST /api/images`).
    func uploadImage(_ jpeg: Data) async throws -> UploadedImage {
        var req = request(url("/api/images"), method: "POST")
        req.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        req.httpBody = jpeg
        req.timeoutInterval = 60
        return try JSONDecoder().decode(UploadedImage.self, from: try await data(for: req))
    }
}

/// Showing amounts: scaled, kitchen-rounded, with fractions.
enum RecipeText {
    private static let fractions: [(Double, String)] = [(1 / 8, "⅛"), (1 / 4, "¼"), (1 / 3, "⅓"), (3 / 8, "⅜"), (1 / 2, "½"),
                                                         (5 / 8, "⅝"), (2 / 3, "⅔"), (3 / 4, "¾"), (7 / 8, "⅞")]
    private static let plural = ["cup": "cups", "pint": "pints", "quart": "quarts", "gallon": "gallons", "stick": "sticks",
                                 "pinch": "pinches", "dash": "dashes", "clove": "cloves", "can": "cans", "tin": "tins",
                                 "jar": "jars", "pack": "packs", "slice": "slices", "bunch": "bunches",
                                 "handful": "handfuls", "sprig": "sprigs", "piece": "pieces"]

    /// 7.5 g, 45 g, 225 g, 1.2 kg.
    static func roundMetric(_ v: Double, _ unit: String) -> (Double, String) {
        if (unit == "g" || unit == "ml") && v >= 1000 {
            let big = v >= 10000
            return ((v / (big ? 100 : 10)).rounded() / (big ? 10 : 100), unit == "g" ? "kg" : "l")
        }
        if v < 10 { return ((v * 2).rounded() / 2, unit) }
        if v < 100 { return (v.rounded(), unit) }
        return ((v / 5).rounded() * 5, unit)
    }

    /// 2.5 -> "2½", 0.333 -> "⅓", 12.4 -> "12", 1.15 -> "1.2".
    static func number(_ v: Double) -> String {
        if v >= 20 { return String(Int(v.rounded())) }
        let whole = floor(v)
        let frac = v - whole
        if frac < 0.04 { return String(Int(whole)) }
        if frac > 0.96 { return String(Int(whole) + 1) }
        if let near = fractions.first(where: { abs(frac - $0.0) < 0.04 }) {
            return (whole > 0 ? String(Int(whole)) : "") + near.1
        }
        let r = (v * 10).rounded() / 10
        return r == r.rounded() ? String(Int(r)) : String(r)
    }

    private static func amount(_ q: Double, _ qmax: Double?, _ unit: String) -> String {
        if unit == "g" || unit == "ml" {
            let (a, u) = roundMetric(q, unit)
            let b = qmax.map { roundMetric($0, unit).0 }
            return "\(number(a))\(b.map { "–\(number($0))" } ?? "") \(u)"
        }
        let n = "\(number(q))\(qmax.map { "–\(number($0))" } ?? "")"
        if unit.isEmpty { return n }
        return "\(n) \((qmax ?? q) > 1 ? plural[unit] ?? unit : unit)"
    }

    /// The amount in metric, scaled; nil when the line is metric already or has no amount.
    static func metric(_ ing: Ingredient, _ factor: Double = 1) -> String? {
        guard let m = ing.metric, ing.quantity != nil else { return nil }
        return amount(m.quantity * factor, m.quantity_max.map { $0 * factor }, m.unit)
    }

    /// The line as shown: scaled ("2½ cups plain flour, sifted"), or as saved when it has no amount.
    static func line(_ ing: Ingredient, _ factor: Double = 1, withNote: Bool = true) -> String {
        if ing.heading { return ing.name }
        guard let q = ing.quantity else { return ing.text }
        if factor == 1 && withNote { return ing.text }
        let amt = amount(q * factor, ing.quantity_max.map { $0 * factor }, ing.unit)
        let note = withNote && !ing.note.isEmpty ? ", \(ing.note)" : ""
        return "\(amt) \(ing.name)\(note)".trimmingCharacters(in: .whitespaces)
    }

    /// For the shopping list: the scaled amount with metric in brackets, no preparation notes.
    static func shopping(_ ing: Ingredient, _ factor: Double = 1) -> String {
        if ing.quantity == nil {
            let head = ing.text.split(separator: ",", maxSplits: 1).first.map(String.init)?.trimmingCharacters(in: .whitespaces) ?? ""
            return head.isEmpty ? ing.text : head
        }
        return line(ing, factor, withNote: false) + (metric(ing, factor).map { " (\($0))" } ?? "")
    }

    /// "1 h 20 min", "45 min".
    static func minutes(_ m: Int?) -> String {
        guard let m else { return "" }
        let h = m / 60, mm = m % 60
        return h > 0 ? (mm > 0 ? "\(h) h \(mm) min" : "\(h) h") : "\(mm) min"
    }

    /// "4:05", "1:02:00".
    static func clock(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds.rounded(.up)))
        let h = s / 3600, m = (s % 3600) / 60, r = s % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, r) : String(format: "%d:%02d", m, r)
    }

    /// The servings stepper's label: "4 servings", or "1½× recipe" when the recipe doesn't say.
    static func servings(_ recipe: Recipe, _ chosen: Double) -> String {
        if recipe.servings != nil {
            let n = Int(chosen)
            return "\(n) \(n == 1 ? "serving" : "servings")"
        }
        return "\(number(chosen))× recipe"
    }
}
