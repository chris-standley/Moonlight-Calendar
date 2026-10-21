import SwiftUI

/// Shopping and to-do lists. Pick a list on the left; select an item to tick it off.
struct ListsView: View {
    @Environment(AppModel.self) private var model
    @State private var lists: [TaskList] = []
    @State private var selected: String?
    @State private var items: [ListItem] = []

    var body: some View {
        let current = lists.first { $0.id == selected } ?? lists.first
        Screen {
            if lists.isEmpty {
                FamilyPrompt(text: "No lists yet. Add one on a wall screen or your phone.")
            } else {
                HStack(alignment: .top, spacing: 36) {
                    ScrollView {
                        VStack(spacing: 14) {
                            ForEach(lists) { l in listButton(l, on: l.id == current?.id) }
                        }
                        .padding(14)
                    }
                    .scrollClipDisabled()
                    .frame(width: 460)
                    .focusSection()

                    if let current { itemsPanel(current) }
                }
                .padding(.bottom, 40)
            }
        }
        .task(id: model.rev("lists")) {
            if let v = await model.call({ try await $0.lists() }) { lists = v.sorted { $0.sort < $1.sort } }
        }
        .task(id: "\(current?.id ?? "")|\(model.rev("lists"))") {
            guard let id = current?.id else { return }
            if let v = await model.call({ try await $0.items(id) }) { items = v }
        }
    }

    private func listButton(_ l: TaskList, on: Bool) -> some View {
        let color = Color(hex: l.color)
        return Button { selected = l.id } label: {
            HStack(spacing: 16) {
                Text(l.emoji).font(.system(size: 40))
                Text(l.name).font(Theme.font(28, .heavy)).foregroundStyle(on ? Color.white : Theme.text).lineLimit(1)
                Spacer()
                Text("\(l.open_count)").font(Theme.font(24, .heavy))
                    .foregroundStyle(on ? Color.white : Theme.muted)
            }
            .padding(.horizontal, 22).padding(.vertical, 18)
            .background(on ? color : Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .buttonStyle(.moonCard(radius: 18, ring: color))
    }

    private func itemsPanel(_ list: TaskList) -> some View {
        let color = Color(hex: list.color)
        let open = items.filter { !$0.done }
        let done = items.filter(\.done)
        return VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("\(list.emoji) \(list.name)").font(Theme.font(36, .heavy)).foregroundStyle(Theme.text)
                Spacer()
                Text("\(open.count) to go").font(Theme.font(24, .bold)).foregroundStyle(Theme.muted)
            }
            ScrollView {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 18), GridItem(.flexible(), spacing: 18)], spacing: 14) {
                    ForEach(open + done) { item in itemRow(item, color: color) }
                }
                .padding(14)
                if items.isEmpty { EmptyNote(text: "Nothing on this list") }
            }
            .scrollClipDisabled()
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(color.opacity(0.1), in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .focusSection()
    }

    private func itemRow(_ item: ListItem, color: Color) -> some View {
        Button { toggle(item) } label: {
            HStack(spacing: 16) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10).strokeBorder(color, lineWidth: 3.5)
                    if item.done {
                        RoundedRectangle(cornerRadius: 10).fill(color)
                        Image(systemName: "checkmark").font(.system(size: 22, weight: .heavy)).foregroundStyle(.white)
                    }
                }
                .frame(width: 44, height: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title).font(Theme.font(26, .bold)).foregroundStyle(Theme.text)
                        .strikethrough(item.done).opacity(item.done ? 0.5 : 1).lineLimit(2)
                    if let due = item.due {
                        Text("Due \(model.dates.relative(due))").font(Theme.font(18, .bold)).foregroundStyle(Theme.muted)
                    }
                }
                Spacer()
                if let p = model.person(item.person_id) { Avatar(person: p, size: 40) }
            }
            .padding(.horizontal, 18).padding(.vertical, 14)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.moonCard(radius: 16, ring: color))
        .accessibilityLabel("\(item.title), \(item.done ? "done" : "to do")")
    }

    private func toggle(_ item: ListItem) {
        if let i = items.firstIndex(where: { $0.id == item.id }) { items[i].done.toggle() } // optimistic
        Task {
            _ = await model.call { try await $0.setItem(item.id, done: !item.done) }
            model.bump("lists")
        }
    }
}
