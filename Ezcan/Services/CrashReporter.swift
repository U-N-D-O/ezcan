import Foundation

struct CrashReport: Identifiable {
    let id = UUID()
    let message: String
}

final class CrashReporter {
    static let shared = CrashReporter()

    private static let reportFileName = "last-crash-report.txt"
    private static let sessionFileName = "active-session.txt"
    private static var installed = false
    private let lock = NSLock()
    private let directory: URL

    private init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        directory = base.appendingPathComponent("Ezcan", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    static func install() {
        guard !installed else { return }
        installed = true
        NSSetUncaughtExceptionHandler { exception in
            CrashReporter.shared.writeCrashReport(
                reason: "Unhandled exception: \(exception.name.rawValue)\n\(exception.reason ?? "No exception reason was provided.")"
            )
        }
    }

    func startSession() {
        write("Started at \(ISO8601DateFormatter().string(from: Date()))", to: Self.sessionFileName)
    }

    func record(_ operation: String) {
        write(operation, to: Self.sessionFileName)
    }

    func previousCrash() -> CrashReport? {
        lock.lock()
        defer { lock.unlock() }
        guard FileManager.default.fileExists(atPath: sessionURL.path) else { return nil }

        let report: String
        if let savedReport = try? String(contentsOf: reportURL, encoding: .utf8), !savedReport.isEmpty {
            report = savedReport
        } else if let lastOperation = try? String(contentsOf: sessionURL, encoding: .utf8) {
            report = "The previous session ended unexpectedly.\n\nLast known activity: \(lastOperation)"
        } else {
            report = "The previous session ended unexpectedly, but no additional details were saved."
        }
        try? FileManager.default.removeItem(at: sessionURL)
        try? FileManager.default.removeItem(at: reportURL)
        return CrashReport(message: report)
    }

    func markBackgrounded() {
        lock.lock()
        defer { lock.unlock() }
        try? FileManager.default.removeItem(at: sessionURL)
    }

    private func writeCrashReport(reason: String) {
        let operation = (try? String(contentsOf: sessionURL, encoding: .utf8)) ?? "Unknown"
        write("\(reason)\n\nLast known activity: \(operation)", to: Self.reportFileName)
    }

    private func write(_ value: String, to fileName: String) {
        lock.lock()
        defer { lock.unlock() }
        try? value.write(to: directory.appendingPathComponent(fileName), atomically: true, encoding: .utf8)
    }

    private var reportURL: URL { directory.appendingPathComponent(Self.reportFileName) }
    private var sessionURL: URL { directory.appendingPathComponent(Self.sessionFileName) }
}