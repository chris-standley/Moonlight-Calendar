import SwiftUI

/// One event, focusable; select opens its details.
struct EventCard: View {
    @Environment(AppModel.self) private var model
    let event: Occurrence
    var compact = false
    var showDay = false
    let onSelect: (Occurrence) -> Void

    var body: some View {
        let colors = EventColors(event, people: model.people)
        let people = event.person_ids.compactMap(model.person)
        Button { onSelect(event) } label: {
            if event.all_day {
                HStack {
                    Text(event.displayTitle(model.people)).font(Theme.font(compact ? 22 : 26, .heavy)).lineLimit(1)
                    Spacer(minLength: 6)
                    if people.count > 1 { AvatarStack(people: people, size: 28) }
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(colors.main, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            } else {
                HStack(spacing: 0) {
                    VStack(spacing: 0) {
                        ForEach(Array(colors.stripe.enumerated()), id: \.offset) { item in item.element }
                    }
                    .frame(width: 8)
                    VStack(alignment: .leading, spacing: 4) {
                        Text((showDay ? model.dates.dow(event.start) + " · " : "") + model.dates.range(event))
                            .font(Theme.font(compact ? 19 : 22, .bold))
                            .foregroundStyle(colors.main.mix(with: .black, by: 0.3))
                        Text(event.displayTitle(model.people))
                            .font(Theme.font(compact ? 23 : 27, .heavy))
                            .foregroundStyle(Theme.text)
                            .lineLimit(2)
                        if !compact, let loc = event.location, !loc.isEmpty {
                            Text(loc).font(Theme.font(19, .semibold)).foregroundStyle(Theme.muted).lineLimit(1)
                        }
                        if people.count > 1 { AvatarStack(people: people, size: 28).padding(.top, 2) }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(colors.main.opacity(colors.busy ? 0.08 : 0.16))
                .background(Theme.surface)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
        }
        .buttonStyle(.moonCard(radius: 16, ring: colors.main))
    }
}

/// Event details (read only: the TV has no keyboard; edit on a wall screen or phone).
struct EventDetail: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let event: Occurrence

    var body: some View {
        let colors = EventColors(event, people: model.people)
        let people = event.person_ids.compactMap(model.person)
        VStack(alignment: .leading, spacing: 30) {
            HStack(spacing: 20) {
                RoundedRectangle(cornerRadius: 6).fill(colors.main).frame(width: 12, height: 80)
                VStack(alignment: .leading, spacing: 6) {
                    Text(event.displayTitle(model.people)).font(Theme.font(54, .heavy))
                    Text("\(model.dates.relative(event.startDay)) · \(model.dates.range(event))")
                        .font(Theme.font(32, .bold)).foregroundStyle(Theme.muted)
                }
            }
            if let loc = event.location, !loc.isEmpty {
                Label(loc, systemImage: "mappin.and.ellipse").font(Theme.font(30, .bold))
            }
            if event.recurring == true || event.custom_repeat == true {
                Label(repeatText, systemImage: "repeat").font(Theme.font(30, .bold))
            }
            if !people.isEmpty {
                HStack(spacing: 24) {
                    ForEach(people) { p in
                        HStack(spacing: 12) {
                            Avatar(person: p, size: 54)
                            Text(p.name).font(Theme.font(30, .bold))
                        }
                    }
                }
            }
            if let notes = event.notes, !notes.isEmpty {
                Text(notes).font(Theme.font(28, .medium)).foregroundStyle(Theme.muted).lineLimit(8)
            }
            Button("Close") { dismiss() }.buttonStyle(.pillProminent)
        }
        .foregroundStyle(Theme.text)
        .padding(60)
        .frame(width: 1100, alignment: .leading)
    }

    private var repeatText: String {
        guard let r = event.`repeat` else { return "Repeats" }
        let unit = ["daily": "day", "weekly": "week", "monthly": "month"][r.freq] ?? r.freq
        return r.interval == 1 ? "Every \(unit)" : "Every \(r.interval) \(unit)s"
    }
}
