import SwiftUI
import UIKit

/// Step by step: the current step large in the middle, its timers one tap away, ingredients to tick off. The screen
/// stays on, and the step and next timer show on the Lock Screen while it's open.
struct CookView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let recipe: Recipe
    let factor: Double

    @State private var index = 0
    @State private var showIngredients = false
    @State private var ticked: Set<Int> = []
    private var timers: KitchenTimers { KitchenTimers.shared }

    private var count: Int { recipe.steps.count }

    var body: some View {
        VStack(spacing: 0) {
            header
            ProgressView(value: Double(min(index + 1, count)), total: Double(max(1, count)))
                .tint(Theme.accent)
                .padding(.horizontal, 16)
            TabView(selection: $index) {
                ForEach(recipe.steps.indices, id: \.self) { i in
                    page(i).tag(i)
                }
                done.tag(count)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            TimerTray(timers: timers)
            footer
        }
        .background(Theme.bg.ignoresSafeArea())
        .sheet(isPresented: $showIngredients) { ingredients }
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            CookingLiveActivity.shared.begin(recipe)
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            CookingLiveActivity.shared.end()
        }
        .onChange(of: index) { _, i in
            CookingLiveActivity.shared.show(step: i, of: count, text: i < count ? recipe.steps[i].shown : "All done. Enjoy!")
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button { dismiss() } label: {
                Image(systemName: "xmark").font(.headline).frame(width: 40, height: 40).background(Theme.surface, in: Circle())
            }
            .accessibilityLabel("Close")
            VStack(alignment: .leading, spacing: 0) {
                Text(recipe.title).font(Theme.text(.headline, .heavy)).lineLimit(1)
                Text(index < count ? "Step \(index + 1) of \(count)" : "All done")
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            }
            Spacer()
            Button { showIngredients = true } label: {
                Label("Ingredients", systemImage: "list.bullet").font(Theme.text(.subheadline, .bold))
            }
            .buttonStyle(.bordered)
        }
        .foregroundStyle(Theme.text)
        .padding(16)
    }

    private func page(_ i: Int) -> some View {
        let step = recipe.steps[i]
        return ScrollView {
            VStack(spacing: 22) {
                Text("\(i + 1)")
                    .font(Theme.text(.title2, .heavy))
                    .foregroundStyle(.white)
                    .frame(width: 52, height: 52)
                    .background(Theme.accentGradient, in: Circle())
                if step.photo_url != nil {
                    RemoteImage(path: step.photo_url)
                        .frame(maxWidth: 520, maxHeight: 280)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                }
                Text(step.shown)
                    .font(Theme.text(.title2, .bold))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Theme.text)
                    .frame(maxWidth: 720)
                ForEach(step.timers, id: \.seconds) { t in
                    let label = "Step \(i + 1): \(t.label)"
                    let running = timers.running(label: label, recipe: recipe.title)
                    Button {
                        timers.start(label, seconds: t.seconds, recipe: recipe.title)
                    } label: {
                        Label(running ? "Running" : "Start \(t.label) timer", systemImage: "timer")
                            .font(Theme.text(.headline, .heavy))
                            .padding(.horizontal, 22).padding(.vertical, 12)
                            .foregroundStyle(.white)
                            .background(Theme.accent.opacity(running ? 0.45 : 1), in: Capsule())
                    }
                    .disabled(running)
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, minHeight: 360)
        }
    }

    private var done: some View {
        VStack(spacing: 16) {
            Text(recipe.emoji.isEmpty ? "🎉" : recipe.emoji).font(.system(size: 72))
            Text("That's everything").font(Theme.text(.title, .heavy))
            Text(recipe.cooked_count > 0 ? "Made \(recipe.cooked_count) \(recipe.cooked_count == 1 ? "time" : "times") before." : "First time making this one.")
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.muted)
            Button {
                Task {
                    if let id = recipe.id { _ = await model.call { try await $0.recipeCooked(id) } }
                    model.bump("recipes")
                    dismiss()
                }
            } label: {
                Label("Mark as made", systemImage: "checkmark")
                    .font(Theme.text(.headline, .heavy))
                    .padding(.horizontal, 26).padding(.vertical, 14)
                    .foregroundStyle(.white)
                    .background(Theme.accent, in: Capsule())
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var footer: some View {
        HStack {
            Button { withAnimation { index = max(0, index - 1) } } label: {
                Label("Back", systemImage: "chevron.left").font(Theme.text(.headline, .heavy)).frame(minWidth: 90, minHeight: 44)
            }
            .buttonStyle(.bordered)
            .disabled(index == 0)
            Spacer()
            if index < count {
                Button { withAnimation { index += 1 } } label: {
                    Label(index == count - 1 ? "Finish" : "Next", systemImage: "chevron.right")
                        .labelStyle(TrailingIcon())
                        .font(Theme.text(.headline, .heavy)).frame(minWidth: 90, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
            } else {
                Button { dismiss() } label: {
                    Text("Close").font(Theme.text(.headline, .heavy)).frame(minWidth: 90, minHeight: 44)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(16)
    }

    private var ingredients: some View {
        NavigationStack {
            List {
                ForEach(recipe.ingredients.indices, id: \.self) { i in
                    let ing = recipe.ingredients[i]
                    if ing.heading {
                        IngredientLine(ing: ing, factor: factor)
                    } else {
                        Button {
                            if ticked.contains(i) { ticked.remove(i) } else { ticked.insert(i) }
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: ticked.contains(i) ? "checkmark.circle.fill" : "circle")
                                    .font(.title3)
                                    .foregroundStyle(ticked.contains(i) ? Theme.accent : Theme.muted)
                                IngredientLine(ing: ing, factor: factor)
                                    .strikethrough(ticked.contains(i))
                                    .opacity(ticked.contains(i) ? 0.5 : 1)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .navigationTitle("Ingredients")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showIngredients = false } } }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct TrailingIcon: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) { configuration.title; configuration.icon }
    }
}

/// Running timers: countdown, pause, +1 minute and stop. One that has gone off turns red until it's stopped.
struct TimerTray: View {
    let timers: KitchenTimers

    var body: some View {
        if !timers.timers.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(timers.timers) { t in
                        let ringing = t.done(at: timers.now)
                        HStack(spacing: 10) {
                            VStack(alignment: .leading, spacing: 0) {
                                Text(t.label).font(Theme.text(.caption, .bold)).lineLimit(1)
                                Text(ringing ? "Time's up" : RecipeText.clock(t.left(at: timers.now)))
                                    .font(Theme.text(.title3, .heavy)).monospacedDigit()
                            }
                            if !ringing {
                                Button { timers.togglePause(t.id) } label: { Image(systemName: t.pausedLeft == nil ? "pause.fill" : "play.fill") }
                                    .accessibilityLabel(t.pausedLeft == nil ? "Pause" : "Resume")
                            }
                            Button("+1") { timers.add(t.id, seconds: 60) }.font(Theme.text(.subheadline, .heavy))
                                .accessibilityLabel("Add a minute")
                            Button { timers.stop(t.id) } label: { Image(systemName: "xmark") }
                                .accessibilityLabel("Stop")
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .foregroundStyle(ringing ? .white : Theme.text)
                        .background(ringing ? Theme.danger : Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .shadow(color: .black.opacity(0.08), radius: 6, y: 2)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 6)
            }
        }
    }
}
