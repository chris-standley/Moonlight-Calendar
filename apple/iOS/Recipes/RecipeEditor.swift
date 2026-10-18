import PhotosUI
import SwiftUI
import UIKit

/// Add or change a recipe, or check one that was just read from a photo, link or text (`recipe.id` nil) before
/// saving it. The ingredient lines are read back as you type, with metric amounts shown for cups, ounces and the like.
struct RecipeEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var recipe: Recipe? = nil
    /// Set when checking a recipe found in a cookbook scan: saving keeps it and takes it off the list to check.
    var draftId: String? = nil
    var onSaved: ((Recipe) -> Void)? = nil

    private struct StepDraft: Identifiable {
        let id = UUID()
        var text: String
        var minutes: String
        var photo: String?
        var photoURL: String?
    }

    @State private var loaded = false
    @State private var title = ""
    @State private var emoji = ""
    @State private var description = ""
    @State private var photo: String?
    @State private var photoURL: String?
    @State private var rating = 0
    @State private var favourite = false
    @State private var servings = ""
    @State private var prep = ""
    @State private var cook = ""
    @State private var tags = ""
    @State private var ingredients = ""
    @State private var steps: [StepDraft] = []
    @State private var notes = ""
    @State private var link = ""
    @State private var preview: Recipe?
    @State private var busy = false
    @State private var uploading = 0
    @State private var error: String?
    @State private var confirmDelete = false
    @State private var photoItem: PhotosPickerItem?
    @State private var stepPhotoItem: PhotosPickerItem?
    @State private var stepPhotoFor: UUID?
    @State private var camera = false

    private var saved: Bool { recipe?.id != nil }

    var body: some View {
        NavigationStack {
            Form {
                pictureSection
                Section {
                    TextField("Name", text: $title).font(Theme.text(.title3, .heavy))
                    TextField("Short description", text: $description, axis: .vertical).lineLimit(1...4)
                    HStack {
                        Text("Emoji")
                        Spacer()
                        TextField("🍽️", text: $emoji).multilineTextAlignment(.trailing).frame(width: 80)
                    }
                    HStack {
                        Stars(value: rating, size: 22) { rating = $0 }
                        Spacer()
                        Button { favourite.toggle() } label: {
                            Image(systemName: favourite ? "heart.fill" : "heart").font(.title3)
                                .foregroundStyle(favourite ? Theme.danger : Theme.muted)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(favourite ? "Favourite" : "Not a favourite")
                    }
                }
                Section("Makes and takes") {
                    numberRow("Servings", $servings, unit: "")
                    numberRow("Prep", $prep, unit: "min")
                    numberRow("Cook", $cook, unit: "min")
                }
                ingredientsSection
                stepsSection
                Section("Tags") {
                    TextField("e.g. quick, vegetarian, kids", text: $tags).textInputAutocapitalization(.never)
                }
                Section("Notes") {
                    TextField("Swaps, tips, what the kids thought", text: $notes, axis: .vertical).lineLimit(2...8)
                    TextField("Link to the original", text: $link).keyboardType(.URL).textInputAutocapitalization(.never)
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
                if saved {
                    Button("Delete recipe", role: .destructive) { confirmDelete = true }
                }
            }
            .navigationTitle(saved ? "Edit recipe" : recipe == nil ? "New recipe" : "Check the recipe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "Saving…" : "Save") { Task { await save() } }
                        .disabled(!valid || busy || uploading > 0)
                }
            }
            .confirmationDialog("Delete \(title)?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await delete() } }
            } message: {
                Text("Meals already planned with it keep their name.")
            }
            .sheet(isPresented: $camera) {
                CameraPicker { img in Task { await upload(img) { id, url in photo = id; photoURL = url } } }.ignoresSafeArea()
            }
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                Task { await upload(item) { id, url in photo = id; photoURL = url }; photoItem = nil }
            }
            .onChange(of: stepPhotoItem) { _, item in
                guard let item, let key = stepPhotoFor else { return }
                Task {
                    await upload(item) { id, url in
                        if let i = steps.firstIndex(where: { $0.id == key }) { steps[i].photo = id; steps[i].photoURL = url }
                    }
                    stepPhotoItem = nil
                }
            }
            .task(id: previewKey) {
                try? await Task.sleep(for: .milliseconds(500))
                guard !Task.isCancelled else { return }
                preview = await model.call { try await $0.previewRecipe(["ingredients": ingredientLines, "steps": stepBodies]) }
            }
            .onAppear(perform: load)
        }
    }

    // MARK: Sections

    private var pictureSection: some View {
        Section {
            if let photoURL {
                RemoteImage(path: photoURL)
                    .frame(height: 200)
                    .frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .listRowInsets(EdgeInsets())
            }
            HStack {
                PhotosPicker(selection: $photoItem, matching: .images) {
                    Label(photoURL == nil ? "Choose a picture" : "Change picture", systemImage: "photo")
                }
                Spacer()
                if CameraPicker.isAvailable {
                    Button { camera = true } label: { Label("Take one", systemImage: "camera") }
                }
            }
            .buttonStyle(.borderless)
            if photoURL != nil {
                Button("Remove picture", role: .destructive) { photo = nil; photoURL = nil }.buttonStyle(.borderless)
            }
        }
    }

    private var ingredientsSection: some View {
        Section {
            TextField("One per line, e.g. 2 cups plain flour, sifted", text: $ingredients, axis: .vertical)
                .lineLimit(5...30)
                .font(Theme.text(.body, .regular))
            if let preview, preview.ingredients.contains(where: { $0.metric != nil || $0.heading }) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("READS AS").font(Theme.text(.caption2, .heavy)).foregroundStyle(Theme.muted)
                    ForEach(preview.ingredients.indices, id: \.self) { i in
                        IngredientLine(ing: preview.ingredients[i], factor: 1).font(Theme.text(.subheadline))
                    }
                }
            }
        } header: {
            Text("Ingredients")
        } footer: {
            Text("Put a heading like \"For the sauce:\" on its own line. Cups, ounces and pounds are kept as written, with grams and millilitres shown beside them.")
        }
    }

    private var stepsSection: some View {
        Section {
            ForEach($steps) { $step in
                VStack(alignment: .leading, spacing: 8) {
                    let n = (steps.firstIndex { $0.id == step.id } ?? 0) + 1
                    HStack(alignment: .top) {
                        Text("\(n)").font(Theme.text(.subheadline, .heavy)).foregroundStyle(Theme.accent).frame(width: 22)
                        TextField("What to do", text: $step.text, axis: .vertical).lineLimit(1...8)
                    }
                    HStack(spacing: 14) {
                        HStack(spacing: 4) {
                            Image(systemName: "timer").foregroundStyle(Theme.muted)
                            TextField("min", text: $step.minutes).keyboardType(.decimalPad).frame(width: 54)
                        }
                        if let url = step.photoURL {
                            RemoteImage(path: url).frame(width: 44, height: 44).clipShape(RoundedRectangle(cornerRadius: 8))
                            Button("Remove", role: .destructive) { step.photo = nil; step.photoURL = nil }
                        } else {
                            PhotosPicker(selection: Binding(get: { stepPhotoItem }, set: { stepPhotoFor = step.id; stepPhotoItem = $0 }),
                                         matching: .images) {
                                Label("Picture", systemImage: "photo")
                            }
                        }
                        Spacer()
                        if let timers = previewTimers(n - 1), !timers.isEmpty {
                            Text(timers).font(Theme.text(.caption, .bold)).foregroundStyle(Theme.muted)
                        }
                    }
                    .buttonStyle(.borderless)
                    .font(Theme.text(.subheadline))
                }
                .padding(.vertical, 4)
            }
            .onDelete { steps.remove(atOffsets: $0) }
            .onMove { steps.move(fromOffsets: $0, toOffset: $1) }
            Button { steps.append(StepDraft(text: "", minutes: "")) } label: { Label("Add a step", systemImage: "plus") }
        } header: {
            HStack {
                Text("Method")
                Spacer()
                if steps.count > 1 { EditButton().font(Theme.text(.caption, .bold)) }
            }
        } footer: {
            Text("Times in a step (\"simmer for 10 minutes\") get a timer button. Add minutes for a step that doesn't say.")
        }
    }

    private func numberRow(_ label: String, _ value: Binding<String>, unit: String) -> some View {
        HStack {
            Text(label)
            Spacer()
            TextField("–", text: value).keyboardType(.numberPad).multilineTextAlignment(.trailing).frame(width: 70)
            if !unit.isEmpty { Text(unit).foregroundStyle(Theme.muted) }
        }
    }

    private func previewTimers(_ i: Int) -> String? {
        guard let p = preview, p.steps.indices.contains(i) else { return nil }
        return p.steps[i].timers.map { "⏱ \($0.label)" }.joined(separator: "  ")
    }

    // MARK: Data

    private var ingredientLines: [String] {
        ingredients.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private func number(_ s: String) -> Double? { Double(s.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")) }

    private var stepBodies: [[String: Any]] {
        steps.filter { !$0.text.trimmingCharacters(in: .whitespaces).isEmpty || $0.photo != nil }.map { s in
            ["text": s.text.trimmingCharacters(in: .whitespacesAndNewlines),
             "minutes": number(s.minutes).map { $0 as Any } ?? NSNull(),
             "photo": s.photo.map { $0 as Any } ?? NSNull()]
        }
    }

    private var previewKey: String { ingredients + "|" + steps.map { "\($0.text)#\($0.minutes)" }.joined(separator: "|") }

    private var valid: Bool {
        let whole = { (s: String) in s.trimmingCharacters(in: .whitespaces).isEmpty || Int(s.trimmingCharacters(in: .whitespaces)) != nil }
        return !title.trimmingCharacters(in: .whitespaces).isEmpty && whole(servings) && whole(prep) && whole(cook)
            && steps.allSatisfy { $0.minutes.trimmingCharacters(in: .whitespaces).isEmpty || number($0.minutes) != nil }
    }

    private func load() {
        guard !loaded else { return }
        loaded = true
        guard let r = recipe else { return }
        title = r.title
        emoji = r.emoji
        description = r.description
        photo = r.photo
        photoURL = r.photo_url
        rating = r.rating
        favourite = r.favourite
        servings = r.servings.map(String.init) ?? ""
        prep = r.prep_minutes.map(String.init) ?? ""
        cook = r.cook_minutes.map(String.init) ?? ""
        tags = r.tags.joined(separator: ", ")
        ingredients = r.ingredients.map(\.text).joined(separator: "\n")
        steps = r.steps.map { s in
            StepDraft(text: s.text, minutes: s.minutes.map { $0 == $0.rounded() ? String(Int($0)) : String($0) } ?? "",
                      photo: s.photo, photoURL: s.photo_url)
        }
        notes = r.notes
        link = r.url ?? ""
    }

    private func payload() -> [String: Any] {
        let int = { (s: String) -> Any in Int(s.trimmingCharacters(in: .whitespaces)).map { $0 as Any } ?? NSNull() }
        // A saved total was for the old times; let it follow prep + cook unless only the total was known.
        let keepTotal = recipe?.minutes != nil && recipe?.prep_minutes == nil && recipe?.cook_minutes == nil
            && prep.trimmingCharacters(in: .whitespaces).isEmpty && cook.trimmingCharacters(in: .whitespaces).isEmpty
        let trimmedLink = link.trimmingCharacters(in: .whitespaces)
        return [
            "title": title.trimmingCharacters(in: .whitespaces), "emoji": emoji.trimmingCharacters(in: .whitespaces),
            "description": description.trimmingCharacters(in: .whitespacesAndNewlines),
            "photo": photo.map { $0 as Any } ?? NSNull(), "rating": rating, "favourite": favourite,
            "servings": int(servings), "prep_minutes": int(prep), "cook_minutes": int(cook),
            "minutes": (keepTotal ? recipe?.minutes : nil).map { $0 as Any } ?? NSNull(),
            "tags": tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty },
            "ingredients": ingredientLines, "steps": stepBodies,
            "notes": notes.trimmingCharacters(in: .whitespacesAndNewlines),
            "url": trimmedLink.isEmpty ? NSNull() as Any : trimmedLink,
        ]
    }

    private func save() async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            guard let api = model.api else { return }
            let r: Recipe
            if let draftId {
                r = try await api.saveDraft(draftId, payload())
            } else {
                r = try await api.saveRecipe(id: recipe?.id, payload())
            }
            model.bump("recipes")
            onSaved?(r)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func delete() async {
        guard let id = recipe?.id else { return }
        _ = await model.call { try await $0.deleteRecipe(id) }
        model.bump("recipes")
        model.bump("meals")
        dismiss()
    }

    private func upload(_ item: PhotosPickerItem, _ done: @escaping (String, String) -> Void) async {
        guard let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data) else {
            error = "Couldn't open that picture"
            return
        }
        await upload(img, done)
    }

    private func upload(_ img: UIImage, _ done: @escaping (String, String) -> Void) async {
        guard let jpeg = img.jpeg(), let api = model.api else { return }
        uploading += 1
        defer { uploading -= 1 }
        do {
            let up = try await api.uploadImage(jpeg)
            done(up.id, up.url)
        } catch {
            self.error = error.localizedDescription
        }
    }
}
