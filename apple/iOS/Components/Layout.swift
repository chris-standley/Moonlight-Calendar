import SwiftUI

/// How much room a screen has, from its own width (not the device), so it adapts the same way on an iPhone,
/// an unfolded phone, iPad Split View, Stage Manager windows and rotation.
enum Room: Comparable {
    case narrow   // phone portrait, slide-over, narrow split view (< 600 pt)
    case medium   // big phone landscape, unfolded phone, half an iPad (600–999 pt)
    case wide     // iPad full screen, large windows (≥ 1000 pt)

    init(width: CGFloat) {
        self = width < 600 ? .narrow : width < 1000 ? .medium : .wide
    }

    /// Columns for side-by-side panels (people, days, cards).
    func columns(max: Int) -> Int {
        switch self {
        case .narrow: 1
        case .medium: min(2, max)
        case .wide: min(max, 4)
        }
    }
}

/// Measures the space it's given and hands the content its `Room`. Re-evaluates live as a window resizes
/// or a foldable opens.
struct Adaptive<Content: View>: View {
    @ViewBuilder var content: (Room, CGFloat) -> Content
    @State private var width: CGFloat = 390

    var body: some View {
        content(Room(width: width), width)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
    }
}

/// A screen: navigation title, Moonlight background, and the content measured for its width.
struct Page<Content: View, Tools: ToolbarContent>: View {
    let title: String
    @ViewBuilder var content: (Room) -> Content
    @ToolbarContentBuilder var tools: () -> Tools

    var body: some View {
        NavigationStack {
            Adaptive { room, _ in content(room) }
                .background(Theme.bg.ignoresSafeArea())
                .navigationTitle(title)
                .toolbar(content: tools)
        }
    }
}

/// Section card used across the phone and tablet screens.
struct Card<Content: View>: View {
    var title: String? = nil
    var tint: Color? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                Text(title).font(Theme.text(.title3, .heavy)).foregroundStyle(Theme.text)
            }
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.map { $0.opacity(0.12) } ?? Theme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(tint == nil ? 0.05 : 0), radius: 8, y: 3)
    }
}

struct EmptyHint: View {
    let text: String
    var body: some View {
        Text(text)
            .font(Theme.text(.subheadline))
            .foregroundStyle(Theme.muted)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
    }
}

/// "Today / ‹ / ›" date navigation for the toolbar.
struct DateStepper: View {
    let label: String
    let onToday: () -> Void
    let onStep: (Int) -> Void

    var body: some View {
        HStack(spacing: 4) {
            Button { onStep(-1) } label: { Image(systemName: "chevron.left") }.accessibilityLabel("Previous")
            Button(label, action: onToday).font(Theme.text(.subheadline, .heavy))
            Button { onStep(1) } label: { Image(systemName: "chevron.right") }.accessibilityLabel("Next")
        }
    }
}

/// Toggle chips for showing or hiding each person.
struct PeopleFilter: View {
    @Environment(AppModel.self) private var model
    @Binding var hidden: Set<String>
    var size: CGFloat = 38

    var body: some View {
        HStack(spacing: 8) {
            ForEach(model.people) { p in
                Button {
                    if hidden.contains(p.id) { hidden.remove(p.id) } else { hidden.insert(p.id) }
                } label: {
                    Avatar(person: p, size: size, dim: hidden.contains(p.id))
                        .padding(2)
                        .overlay(Circle().stroke(Color(hex: p.color), lineWidth: hidden.contains(p.id) ? 0 : 2))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(p.name), \(hidden.contains(p.id) ? "hidden" : "shown")")
            }
        }
    }
}

/// Asks for the parent PIN (if one is set) before a protected action, then runs it.
struct PinPrompt: ViewModifier {
    @Environment(AppModel.self) private var model
    @Binding var request: PinRequest?
    @State private var pin = ""
    @State private var error: String?

    func body(content: Content) -> some View {
        content
            .alert(request?.title ?? "", isPresented: Binding(get: { request != nil && model.settings?.pin_set == true },
                                                               set: { if !$0 { request = nil } })) {
                SecureField("PIN", text: $pin).keyboardType(.numberPad)
                Button("Cancel", role: .cancel) { pin = ""; request = nil }
                Button("OK") { run() }
            } message: {
                Text(error ?? "Enter the parent PIN.")
            }
            .onChange(of: request?.id) {
                // No PIN set: nothing to protect, go straight ahead.
                if request != nil && model.settings?.pin_set != true { run() }
            }
    }

    private func run() {
        guard let req = request else { return }
        let entered = pin
        Task {
            do {
                try await req.action(entered)
                error = nil
                request = nil
            } catch APIError.wrongPin {
                error = "That PIN isn't right."
                let again = req
                request = nil
                try? await Task.sleep(for: .milliseconds(350))
                request = again
            } catch {
                self.error = error.localizedDescription
                request = nil
            }
            pin = ""
        }
    }
}

struct PinRequest: Identifiable {
    let id = UUID()
    let title: String
    let action: (String) async throws -> Void
}

extension View {
    func pinPrompt(_ request: Binding<PinRequest?>) -> some View { modifier(PinPrompt(request: request)) }
}
