import SwiftUI
import UIKit

struct CrashLogView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var logText = CrashReporter.shared.currentLog()
    @State private var didCopy = false

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(logText)
                    .font(.system(.footnote, design: .monospaced))
                    .foregroundStyle(EzcanTheme.ink)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
            }
            .background(EzcanTheme.panelDeep)
            .navigationTitle("Crash Log")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button {
                        UIPasteboard.general.string = logText
                        didCopy = true
                    } label: {
                        Label(didCopy ? "Copied" : "Copy", systemImage: didCopy ? "checkmark" : "doc.on.doc")
                    }
                }
            }
        }
        .preferredColorScheme(.light)
    }
}