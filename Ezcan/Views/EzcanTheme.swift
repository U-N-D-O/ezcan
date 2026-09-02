import SwiftUI

enum EzcanTheme {
    static let canvas = Color(red: 0.955, green: 0.969, blue: 0.973)
    static let white = Color.white
    static let ink = Color(red: 0.145, green: 0.212, blue: 0.239)
    static let muted = Color(red: 0.455, green: 0.541, blue: 0.565)
    static let cyan = Color(red: 0.075, green: 0.788, blue: 0.839)
    static let cyanSoft = Color(red: 0.847, green: 0.961, blue: 0.965)
    static let green = Color(red: 0.294, green: 0.820, blue: 0.549)
    static let greenSoft = Color(red: 0.890, green: 0.976, blue: 0.929)
    static let blue = Color(red: 0.282, green: 0.529, blue: 0.969)
    static let blueSoft = Color(red: 0.898, green: 0.929, blue: 1.0)
    static let amber = Color(red: 0.937, green: 0.667, blue: 0.235)
    static let amberSoft = Color(red: 1.0, green: 0.957, blue: 0.855)
    static let pink = Color(red: 0.902, green: 0.416, blue: 0.569)
    static let pinkSoft = Color(red: 1.0, green: 0.918, blue: 0.945)
    static let line = Color(red: 0.850, green: 0.890, blue: 0.902)
    static let shadow = Color(red: 0.220, green: 0.302, blue: 0.329).opacity(0.10)
    static let border = line
    static let text = ink
    static let midnight = canvas
    static let deep = canvas
    static let panel = white
    static let panelRaised = white
    static let panelDeep = Color(red: 0.973, green: 0.984, blue: 0.986)
    static let magenta = pink
}

struct EzcanBackground: View {
    var body: some View {
        ZStack {
            EzcanTheme.canvas
            LinearGradient(
                colors: [Color.white.opacity(0.92), EzcanTheme.canvas.opacity(0.72)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
        .ignoresSafeArea()
    }
}

struct EzcanPanelModifier: ViewModifier {
    var accent: Color = EzcanTheme.line
    var glow: Bool = false

    func body(content: Content) -> some View {
        content
            .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(accent.opacity(glow ? 0.55 : 0.7), lineWidth: 1)
            }
            .shadow(color: glow ? accent.opacity(0.15) : EzcanTheme.shadow, radius: glow ? 18 : 14, y: 7)
    }
}

extension View {
    func ezcanPanel(accent: Color = EzcanTheme.line, glow: Bool = false) -> some View {
        modifier(EzcanPanelModifier(accent: accent, glow: glow))
    }
}

struct EzcanStatusPill: View {
    let title: String
    var color: Color = EzcanTheme.green

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(title)
                .font(.system(size: 10, weight: .bold, design: .rounded))
                .tracking(0.5)
                .foregroundStyle(color)
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 8)
        .background(color.opacity(0.12), in: Capsule())
    }
}

struct EzcanPrimaryButtonStyle: ButtonStyle {
    var color: Color = EzcanTheme.cyan

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(EzcanTheme.ink)
            .background(color.opacity(configuration.isPressed ? 0.72 : 1), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: color.opacity(configuration.isPressed ? 0.08 : 0.22), radius: configuration.isPressed ? 4 : 10, y: 5)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
    }
}

struct EzcanSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(EzcanTheme.ink)
            .background(EzcanTheme.white.opacity(configuration.isPressed ? 0.72 : 1), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay { RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(EzcanTheme.line, lineWidth: 1) }
            .shadow(color: EzcanTheme.shadow, radius: 8, y: 4)
    }
}

struct EzcanNavigationItem: View {
    let title: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .semibold))
                Text(title)
                    .font(.system(size: 10, weight: .semibold, design: .rounded))
            }
            .foregroundStyle(isSelected ? EzcanTheme.cyan : EzcanTheme.muted)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(isSelected ? EzcanTheme.cyanSoft : .clear, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
