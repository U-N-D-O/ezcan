import SwiftUI

enum EzcanTheme {
    static let midnight = Color(red: 0.025, green: 0.055, blue: 0.11)
    static let deep = Color(red: 0.018, green: 0.035, blue: 0.07)
    static let panel = Color(red: 0.055, green: 0.105, blue: 0.17)
    static let panelRaised = Color(red: 0.075, green: 0.145, blue: 0.23)
    static let panelDeep = Color(red: 0.025, green: 0.065, blue: 0.115)
    static let cyan = Color(red: 0.20, green: 0.90, blue: 0.87)
    static let blue = Color(red: 0.30, green: 0.55, blue: 1.0)
    static let magenta = Color(red: 0.90, green: 0.22, blue: 0.43)
    static let green = Color(red: 0.34, green: 0.95, blue: 0.53)
    static let amber = Color(red: 0.96, green: 0.72, blue: 0.28)
    static let text = Color(red: 0.95, green: 0.98, blue: 1.0)
    static let muted = Color(red: 0.52, green: 0.64, blue: 0.77)
    static let border = Color(red: 0.13, green: 0.28, blue: 0.40)
}

struct EzcanBackground: View {
    var body: some View {
        Canvas { context, size in
            let gridColor = EzcanTheme.cyan.opacity(0.055)
            var grid = Path()
            stride(from: CGFloat(0), through: size.width, by: 42).forEach { x in
                grid.move(to: CGPoint(x: x, y: 0))
                grid.addLine(to: CGPoint(x: x, y: size.height))
            }
            stride(from: CGFloat(0), through: size.height, by: 42).forEach { y in
                grid.move(to: CGPoint(x: 0, y: y))
                grid.addLine(to: CGPoint(x: size.width, y: y))
            }
            context.stroke(grid, with: .color(gridColor), lineWidth: 0.5)

            var network = Path()
            let points = [
                CGPoint(x: size.width * 0.04, y: size.height * 0.18),
                CGPoint(x: size.width * 0.24, y: size.height * 0.08),
                CGPoint(x: size.width * 0.44, y: size.height * 0.21),
                CGPoint(x: size.width * 0.68, y: size.height * 0.10),
                CGPoint(x: size.width * 0.94, y: size.height * 0.20)
            ]
            for index in 0..<points.count - 1 {
                network.move(to: points[index])
                network.addLine(to: points[index + 1])
            }
            context.stroke(network, with: .color(EzcanTheme.cyan.opacity(0.12)), lineWidth: 1)
            for point in points {
                context.fill(Path(ellipseIn: CGRect(x: point.x - 2, y: point.y - 2, width: 4, height: 4)), with: .color(EzcanTheme.cyan.opacity(0.55)))
            }
        }
        .background(
            LinearGradient(
                colors: [EzcanTheme.midnight, EzcanTheme.deep],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .ignoresSafeArea()
    }
}

struct EzcanPanelModifier: ViewModifier {
    var accent: Color = EzcanTheme.border
    var glow: Bool = false

    func body(content: Content) -> some View {
        content
            .background(
                LinearGradient(
                    colors: [EzcanTheme.panelRaised.opacity(0.94), EzcanTheme.panel.opacity(0.94)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                in: RoundedRectangle(cornerRadius: 20, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(accent.opacity(glow ? 0.9 : 0.55), lineWidth: glow ? 1.5 : 1)
            }
            .shadow(color: glow ? accent.opacity(0.22) : .black.opacity(0.2), radius: glow ? 16 : 8, y: 5)
    }
}

extension View {
    func ezcanPanel(accent: Color = EzcanTheme.border, glow: Bool = false) -> some View {
        modifier(EzcanPanelModifier(accent: accent, glow: glow))
    }
}

struct EzcanStatusPill: View {
    let title: String
    var color: Color = EzcanTheme.green

    var body: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
                .shadow(color: color.opacity(0.9), radius: 5)
            Text(title)
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .tracking(0.4)
                .foregroundStyle(color)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(color.opacity(0.10), in: Capsule())
        .overlay { Capsule().stroke(color.opacity(0.65), lineWidth: 1) }
    }
}

struct EzcanPrimaryButtonStyle: ButtonStyle {
    var color: Color = EzcanTheme.blue

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .background(
                LinearGradient(colors: [color, color.opacity(0.68)], startPoint: .topLeading, endPoint: .bottomTrailing),
                in: Capsule()
            )
            .overlay { Capsule().stroke(.white.opacity(0.25), lineWidth: 1) }
            .shadow(color: color.opacity(configuration.isPressed ? 0.2 : 0.45), radius: configuration.isPressed ? 5 : 12)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
    }
}

struct EzcanSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(EzcanTheme.text)
            .background(EzcanTheme.panelRaised.opacity(configuration.isPressed ? 0.9 : 0.72), in: Capsule())
            .overlay { Capsule().stroke(EzcanTheme.cyan.opacity(0.42), lineWidth: 1) }
            .shadow(color: EzcanTheme.cyan.opacity(configuration.isPressed ? 0.08 : 0.14), radius: 9)
    }
}
