import SwiftUI
import UIKit

/// The Moonlight palette (frontend/src/styles.css), with a dark variant for evenings in front of the TV.
enum Theme {
    static let bg = dynamic(light: 0xF7F5F2, dark: 0x16171D)
    static let surface = dynamic(light: 0xFFFFFF, dark: 0x22242C)
    static let surface2 = dynamic(light: 0xF1EEE9, dark: 0x2C2E37)
    static let line = dynamic(light: 0xE9E4DC, dark: 0x343743)
    static let text = dynamic(light: 0x22252E, dark: 0xF2F2F5)
    static let muted = dynamic(light: 0x7B7F8B, dark: 0x9DA1AD)
    static let accent = Color(hex: "#6C7BF0")
    static let accent2 = Color(hex: "#8B6CF0")
    static let star = Color(hex: "#FFB938")
    static let starText = dynamic(light: 0xC78400, dark: 0xFFC95C)
    static let starBg = dynamic(light: 0xFFF4DC, dark: 0x3A3020)
    static let mealBg = dynamic(light: 0xFFF7E8, dark: 0x332B1E)
    static let mealText = dynamic(light: 0x9A6A12, dark: 0xF0C578)
    static let danger = Color(hex: "#E0475B")
    static let fallbackEvent = "#8A94A6"

    static let logoGradient = LinearGradient(colors: [Color(hex: "#7C8CF8"), Color(hex: "#B38CF0")],
                                             startPoint: .topLeading, endPoint: .bottomTrailing)
    static let accentGradient = LinearGradient(colors: [accent, accent2], startPoint: .topLeading, endPoint: .bottomTrailing)

    static let radius: CGFloat = 24
    static let gutter: CGFloat = 80 // tvOS safe area is 80pt left/right, 60pt top/bottom

    /// Fixed sizes for the TV, which is always 1920x1080 points at ten feet.
    static func font(_ size: CGFloat, _ weight: Font.Weight = .bold) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    /// Text styles for iPhone and iPad, so Dynamic Type scales them.
    static func text(_ style: Font.TextStyle, _ weight: Font.Weight = .bold) -> Font {
        .system(style, design: .rounded, weight: weight)
    }

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(rgb: dark) : UIColor(rgb: light) })
    }
}

extension UIColor {
    convenience init(rgb: UInt32, alpha: CGFloat = 1) {
        self.init(red: CGFloat((rgb >> 16) & 255) / 255, green: CGFloat((rgb >> 8) & 255) / 255,
                  blue: CGFloat(rgb & 255) / 255, alpha: alpha)
    }
}

extension Color {
    /// `#RRGGBB` (or `#RGB`) from the API; grey if unreadable.
    init(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "#", with: "")
        if s.count == 3 { s = s.map { "\($0)\($0)" }.joined() }
        self.init(uiColor: UIColor(rgb: UInt32(s, radix: 16) ?? 0x8A94A6))
    }
}

extension View {
    /// A white rounded panel with the screens' soft shadow.
    func panel(padding: CGFloat = 28) -> some View {
        self.padding(padding)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 12, y: 4)
    }
}

/// Focus treatment for Moonlight's own cards: the platform's lift (scale + deeper shadow) and an accent ring,
/// so a card reads as focused from across the room without losing the screens' flat look.
struct CardButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = 18
    var ring: Color = Theme.accent

    func makeBody(configuration: Configuration) -> some View {
        Styled(configuration: configuration, cornerRadius: cornerRadius, ring: ring)
    }

    private struct Styled: View {
        let configuration: ButtonStyleConfiguration
        let cornerRadius: CGFloat
        let ring: Color
        @Environment(\.isFocused) private var focused

        var body: some View {
            configuration.label
                .overlay {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .strokeBorder(ring, lineWidth: focused ? 4 : 0)
                }
                .scaleEffect(configuration.isPressed ? 0.97 : focused ? 1.06 : 1)
                .shadow(color: .black.opacity(focused ? 0.28 : 0), radius: focused ? 24 : 0, y: focused ? 14 : 0)
                .zIndex(focused ? 1 : 0)
                .animation(.easeOut(duration: 0.18), value: focused)
                .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
        }
    }
}

/// Pill buttons like the screens' `.btn` / `.btn.ghost`.
struct PillButtonStyle: ButtonStyle {
    var prominent = false

    func makeBody(configuration: Configuration) -> some View {
        Styled(configuration: configuration, prominent: prominent)
    }

    private struct Styled: View {
        let configuration: ButtonStyleConfiguration
        let prominent: Bool
        @Environment(\.isFocused) private var focused

        var body: some View {
            configuration.label
                .font(Theme.font(28, .heavy))
                .padding(.horizontal, 34)
                .frame(minHeight: 66)
                .foregroundStyle(prominent || focused ? Color.white : Theme.text)
                .background(Capsule().fill(prominent || focused ? Theme.accent : Theme.surface))
                .overlay(Capsule().strokeBorder(Theme.line, lineWidth: prominent || focused ? 0 : 2))
                .scaleEffect(configuration.isPressed ? 0.96 : focused ? 1.08 : 1)
                .shadow(color: Theme.accent.opacity(focused ? 0.45 : 0), radius: 18, y: 8)
                .animation(.easeOut(duration: 0.15), value: focused)
        }
    }
}

extension ButtonStyle where Self == CardButtonStyle {
    static func moonCard(radius: CGFloat, ring: Color = Theme.accent) -> CardButtonStyle {
        CardButtonStyle(cornerRadius: radius, ring: ring)
    }
}

extension ButtonStyle where Self == PillButtonStyle {
    static var pill: PillButtonStyle { PillButtonStyle() }
    static var pillProminent: PillButtonStyle { PillButtonStyle(prominent: true) }
}

extension Settings {
    /// The household's appearance choice; nil follows the device's own light/dark setting.
    var colorScheme: ColorScheme? {
        switch theme {
        case "light": .light
        case "dark": .dark
        default: nil
        }
    }
}
