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
                colors: [EzcanTheme.cyanSoft.opacity(0.62), Color.white.opacity(0.84), EzcanTheme.canvas.opacity(0.72)],
                startPoint: .top,
                endPoint: .bottom
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

struct EzcanInstrumentRing<Content: View>: View {
    let progress: Double
    let accent: Color
    let content: Content

    init(progress: Double, accent: Color = EzcanTheme.cyan, @ViewBuilder content: () -> Content) {
        self.progress = progress
        self.accent = accent
        self.content = content()
    }

    var body: some View {
        ZStack {
            ForEach(0..<24, id: \.self) { tick in
                Capsule()
                    .fill(tick < Int(progress * 24) ? accent : EzcanTheme.line)
                    .frame(width: 2, height: tick.isMultiple(of: 4) ? 11 : 7)
                    .offset(y: -114)
                    .rotationEffect(.degrees(Double(tick) * 15))
            }
            Circle()
                .stroke(EzcanTheme.line, lineWidth: 10)
            Circle()
                .trim(from: 0, to: progress)
                .stroke(accent, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Circle()
                .fill(EzcanTheme.white)
                .overlay { Circle().stroke(EzcanTheme.line.opacity(0.7), lineWidth: 1) }
                .padding(22)
            content
        }
        .frame(width: 250, height: 250)
    }
}

struct CaptureProgressButton: View {
    let isComplete: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(isComplete ? EzcanTheme.greenSoft : EzcanTheme.cyanSoft)
                    .frame(width: 94, height: 94)
                    .overlay {
                        Circle()
                            .stroke(EzcanTheme.line, lineWidth: 1)
                    }
                    .shadow(color: EzcanTheme.shadow, radius: 5, x: 2, y: 3)
                Circle()
                    .fill(
                        LinearGradient(
                            colors: isComplete
                                ? [EzcanTheme.green.opacity(0.92), EzcanTheme.green]
                                : [EzcanTheme.blue, EzcanTheme.cyan],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .frame(width: 78, height: 78)
                    .overlay {
                        Circle()
                            .stroke(isComplete ? EzcanTheme.green.opacity(0.75) : EzcanTheme.blue.opacity(0.75), lineWidth: 1)
                    }
                    .shadow(color: EzcanTheme.ink.opacity(0.3), radius: 2, y: 3)
                Image(isComplete ? "finish" : "scan")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 34, height: 34)
                    .shadow(color: .black.opacity(0.28), radius: 2, y: 2)
            }
        }
        .buttonStyle(.plain)
        .disabled(!isComplete)
        .accessibilityLabel(isComplete ? "Continue to archive code" : "Capture progress")
        .accessibilityHint(isComplete ? "Double tap to continue" : "Complete the remaining card media steps")
    }
}

struct EzcanSoftControl<Content: View>: View {
    let tint: Color
    let content: Content

    init(tint: Color = EzcanTheme.cyan, @ViewBuilder content: () -> Content) {
        self.tint = tint
        self.content = content()
    }

    var body: some View {
        content
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
            .background(EzcanTheme.white, in: Capsule())
            .overlay { Capsule().stroke(tint.opacity(0.28), lineWidth: 1) }
            .shadow(color: EzcanTheme.shadow, radius: 8, y: 4)
    }
}
