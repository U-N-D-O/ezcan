import SwiftUI

struct PairingView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    let onPaired: () -> Void

    @State private var computerURL = "http://"
    @State private var token = ""
    @State private var computerName = ""
    @State private var scannerPresented = false
    @State private var hasOpenedScanner = false
    @State private var logPresented = false

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 18) {
                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .center, spacing: 18) {
                            pairingInstrument
                            pairingActions
                        }
                        VStack(spacing: 18) {
                            pairingInstrument
                            pairingActions
                        }
                    }
                    manualPairingPanel
                    if let errorMessage = pairingStore.errorMessage {
                        Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundStyle(EzcanTheme.pink)
                            .padding(16)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(EzcanTheme.white, in: Capsule())
                            .overlay { Capsule().stroke(EzcanTheme.pink.opacity(0.35), lineWidth: 1) }
                    }
                }
                .padding(.horizontal, 18)
                .padding(.top, 72)
                .padding(.bottom, 18)
            }
            .background(EzcanBackground())
            .toolbar(.hidden, for: .navigationBar)
            .fullScreenCover(isPresented: $scannerPresented) {
                QRScannerView { payload in
                    scannerPresented = false
                    pairFromQR(payload)
                } onCancel: {
                    scannerPresented = false
                }
            }
            .sheet(isPresented: $logPresented) {
                CrashLogView()
            }
            .onAppear {
                guard !hasOpenedScanner else { return }
                hasOpenedScanner = true
                scannerPresented = true
            }
        }
    }

    private var pairingInstrument: some View {
        VStack(spacing: 14) {
            EzcanInstrumentRing(progress: 0.68, accent: EzcanTheme.cyan) {
                VStack(spacing: 6) {
                    Image(systemName: "antenna.radiowaves.left.and.right")
                        .font(.system(size: 25, weight: .medium))
                        .foregroundStyle(EzcanTheme.cyan)
                    Text("PAIR")
                        .font(.system(size: 20, weight: .black, design: .rounded))
                        .foregroundStyle(EzcanTheme.ink)
                    Text("SCANNER READY")
                        .font(.system(size: 8, weight: .bold, design: .monospaced))
                        .foregroundStyle(EzcanTheme.muted)
                }
            }
            Text("Connect a trusted capture station")
                .font(.caption)
                .foregroundStyle(EzcanTheme.muted)
        }
        .padding(.vertical, 20)
        .frame(maxWidth: .infinity)
        .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 28, style: .continuous).stroke(EzcanTheme.cyan.opacity(0.35), lineWidth: 1) }
        .shadow(color: EzcanTheme.shadow, radius: 14, y: 7)
    }

    private var pairingActions: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("LINK DEVICE")
                .font(.caption.weight(.bold))
                .foregroundStyle(EzcanTheme.muted)
            Text("Scan the QR code shown in Ezcan Computer.")
                .font(.title3.bold())
                .foregroundStyle(EzcanTheme.ink)
            Button {
                scannerPresented = true
            } label: {
                Label("Scan computer QR", systemImage: "qrcode.viewfinder")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 15)
            }
            .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.cyan))
            HStack(spacing: 10) {
                EzcanSoftControl(tint: EzcanTheme.blue) {
                    HStack(spacing: 8) {
                        Image(systemName: "lock.shield")
                        Text("PRIVATE NETWORK")
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                    }
                    .foregroundStyle(EzcanTheme.blue)
                }
                Button {
                    logPresented = true
                } label: {
                    Label("LOG", systemImage: "doc.text.magnifyingglass")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(EzcanTheme.pink)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 13)
                        .background(EzcanTheme.white, in: Capsule())
                        .overlay { Capsule().stroke(EzcanTheme.pink.opacity(0.28), lineWidth: 1) }
                        .shadow(color: EzcanTheme.shadow, radius: 8, y: 4)
                }
                .buttonStyle(.plain)
                .accessibilityHint("Show the latest crash and activity log")
            }
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .shadow(color: EzcanTheme.shadow, radius: 14, y: 7)
    }

    private var manualPairingPanel: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                Text("MANUAL CONNECTION")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(EzcanTheme.muted)
                Spacer()
                Text("02")
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(EzcanTheme.cyan)
            }
            inputField("Computer address", text: $computerURL, placeholder: "http://192.168.1.25:8765")
            inputField("Pairing token", text: $token, placeholder: "Temporary token")
            inputField("Computer name", text: $computerName, placeholder: "Optional")
            Button {
                pairManually()
            } label: {
                Text("Pair manually")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
            }
            .buttonStyle(EzcanSecondaryButtonStyle())
            .disabled(token.isEmpty || computerURL == "http://")
            .opacity(token.isEmpty || computerURL == "http://" ? 0.45 : 1)
        }
        .padding(20)
        .background(EzcanTheme.panelDeep, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(EzcanTheme.line, lineWidth: 1) }
    }

    private func inputField(_ title: String, text: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(EzcanTheme.muted)
            TextField(placeholder, text: text)
                .font(.body)
                .foregroundStyle(EzcanTheme.ink)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(.horizontal, 13)
                .padding(.vertical, 12)
                .background(EzcanTheme.panelDeep, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(EzcanTheme.line, lineWidth: 1)
                }
        }
    }

    private func pairManually() {
        guard let url = URL(string: computerURL) else {
            pairingStore.errorMessage = PairingError.invalidURL.localizedDescription
            return
        }
        do {
            let code = try PairingCode(
                url: url,
                token: token,
                computerName: computerName.isEmpty ? nil : computerName
            )
            pairingStore.pair(with: code)
            onPaired()
        } catch {
            pairingStore.errorMessage = error.localizedDescription
        }
    }

    private func pairFromQR(_ payload: String) {
        do {
            pairingStore.pair(with: try PairingCode.decode(payload))
            onPaired()
        } catch {
            pairingStore.errorMessage = error.localizedDescription
        }
    }
}