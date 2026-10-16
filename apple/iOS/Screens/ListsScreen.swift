import SwiftUI

/// Shopping and to-do lists. A split view: lists beside items when there's room, a stack on a phone.
struct ListsScreen: View {
    @Environment(AppModel.self) private var model
    @State private var lists: [TaskList] = []
    @State private var selected: String?
    @State private var addingList = false
    @State private var visibility: NavigationSplitViewVisibility = .all

    var body: some View {
        NavigationSplitView(columnVisibility: $visibility) {
            List(selection: $selected) {
                ForEach(lists) { l in
                    NavigationLink(value: l.id) {
                        HStack {
                            Text(l.emoji).font(.system(size: 24))
                            Text(l.name).font(Theme.text(.body, .heavy))
                            Spacer()
                            Text("\(l.open_count)").font(Theme.text(.subheadline, .bold)).foregroundStyle(Theme.muted)
                        }
                    }
                    .listRowBackground(selected == l.id ? Color(hex: l.color).opacity(0.18) : nil)
                }
                .onDelete { idx in
                    let gone = idx.map { lists[$0] }
                    lists.remove(atOffsets: idx)
                    Task {
                        for l in gone { _ = await model.call { try await $0.deleteList(l.id) } }
                        model.bump("lists")
                    }
                }
            }
            .navigationTitle("Lists")
            .moreTabBar()
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { addingList = true } label: { Image(systemName: "plus") }.accessibilityLabel("New list")
                }
            }
            .overlay { if lists.isEmpty { EmptyHint(text: "No lists yet") } }
        } detail: {
            if let l = lists.first(where: { $0.id == selected }) {
                ListDetail(list: l)
            } else {
                EmptyHint(text: lists.isEmpty ? "Add a list with +" : "Pick a list")
            }
        }
        .task(id: model.rev("lists")) {
            if let v = await model.call({ try await $0.lists() }) {
                lists = v.sorted { $0.sort < $1.sort }
            }
        }
        .sheet(isPresented: $addingList) { ListEditor() }
    }
}

struct ListDetail: View {
    @Environment(AppModel.self) private var model
    let list: TaskList
    @State private var items: [ListItem] = []
    @State private var draft = ""
    @FocusState private var typing: Bool

    var body: some View {
        let color = Color(hex: list.color)
        List {
            Section {
                HStack {
                    Image(systemName: "plus.circle.fill").foregroundStyle(color).font(.title3)
                    TextField(list.kind == "grocery" ? "Add an item" : "Add a task", text: $draft)
                        .focused($typing)
                        .submitLabel(.done)
                        .onSubmit(add)
                }
            }
            Section {
                ForEach(items.filter { !$0.done }) { row($0, color: color) }
                    .onDelete { delete(items.filter { !$0.done }, $0) }
            }
            let done = items.filter(\.done)
            if !done.isEmpty {
                Section("Done") {
                    ForEach(done) { row($0, color: color) }
                        .onDelete { delete(done, $0) }
                }
            }
        }
        .navigationTitle("\(list.emoji) \(list.name)")
        .toolbar {
            if items.contains(where: \.done) {
                ToolbarItem(placement: .primaryAction) {
                    Button("Clear done") {
                        items.removeAll(where: \.done)
                        Task {
                            _ = await model.call { try await $0.clearDone(list.id) }
                            model.bump("lists")
                        }
                    }
                }
            }
        }
        .refreshable { model.bump("lists") }
        .task(id: "\(list.id)|\(model.rev("lists"))") {
            if let v = await model.call({ try await $0.items(list.id) }) { items = v }
        }
        .sensoryFeedback(.selection, trigger: items.filter(\.done).count)
    }

    private func row(_ item: ListItem, color: Color) -> some View {
        Button { toggle(item) } label: {
            HStack(spacing: 12) {
                Image(systemName: item.done ? "checkmark.circle.fill" : "circle")
                    .font(.title2).foregroundStyle(color)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title).font(Theme.text(.body, .semibold)).foregroundStyle(Theme.text)
                        .strikethrough(item.done).opacity(item.done ? 0.5 : 1)
                    if let due = item.due {
                        Text("Due \(model.dates.relative(due))").font(Theme.text(.caption)).foregroundStyle(Theme.muted)
                    }
                }
                Spacer()
                if let p = model.person(item.person_id) { Avatar(person: p, size: 26) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func add() {
        let title = draft.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty else { return }
        draft = ""
        typing = true // keep the keyboard up for the next item
        Task {
            _ = await model.call { try await $0.addItem(list.id, title: title) }
            model.bump("lists")
        }
    }

    private func toggle(_ item: ListItem) {
        if let i = items.firstIndex(where: { $0.id == item.id }) {
            withAnimation { items[i].done.toggle() }
        }
        Task {
            _ = await model.call { try await $0.setItem(item.id, done: !item.done) }
            model.bump("lists")
        }
    }

    private func delete(_ source: [ListItem], _ idx: IndexSet) {
        let gone = idx.map { source[$0] }
        items.removeAll { i in gone.contains { $0.id == i.id } }
        Task {
            for g in gone { _ = await model.call { try await $0.deleteItem(g.id) } }
            model.bump("lists")
        }
    }
}

struct ListEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var emoji = ""
    @State private var kind = "todo"
    @State private var color = "#6C7BF0"
    @State private var error: String?
    private let colors = ["#6C7BF0", "#3BB273", "#F2994A", "#E0475B", "#8B6CF0", "#2D9CDB"]

    var body: some View {
        NavigationStack {
            Form {
                HStack {
                    TextField("📝", text: $emoji).frame(width: 44).font(.system(size: 28))
                        .onChange(of: emoji) { if emoji.count > 1 { emoji = String(emoji.suffix(1)) } }
                    TextField("List name", text: $name).font(Theme.text(.headline))
                }
                Picker("Kind", selection: $kind) {
                    Text("To-do").tag("todo")
                    Text("Shopping").tag("grocery")
                }
                .pickerStyle(.segmented)
                HStack {
                    ForEach(colors, id: \.self) { c in
                        Button { color = c } label: {
                            Circle().fill(Color(hex: c)).frame(width: 34, height: 34)
                                .overlay(Circle().stroke(Theme.text, lineWidth: color == c ? 3 : 0).padding(-4))
                        }
                        .buttonStyle(.plain)
                        .frame(maxWidth: .infinity)
                    }
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .navigationTitle("New list")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            do {
                                try await model.api?.createList(name: name, emoji: emoji.isEmpty ? (kind == "grocery" ? "🛒" : "📝") : emoji,
                                                                color: color, kind: kind)
                                model.bump("lists")
                                dismiss()
                            } catch { self.error = error.localizedDescription }
                        }
                    }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }
}
