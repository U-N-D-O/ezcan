import SwiftUI

struct PairingView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    let onPaired: () -> Void

    @State private var computerURL = "http://"
    @State private var token = ""
    @State private var computerName = ""
    @State private var scannerPresented = false
    @State private var hasOpenedScanner = false

    var body: some View {
        NavigationStack {
            ZStack {
                EzcanBackground()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        GeometryReader { proxy in
                            pairingHeader(compact: proxy.size.width < 370)
                        }
                        .frame(height: 44)

                        VStack(spacing: 14) {
                            Image("ezcan_logo")
                                .resizable()
                                .scaledToFit()
                                .frame(width: 112, height: 112)
                            Text("CONNECT TO EZCAN")
                                .font(.system(size: 23, weight: .black, design: .rounded))
                                .tracking(1.4)
                                .foregroundStyle(EzcanTheme.text)
                            Text("Scan the QR code in Ezcan Computer to connect this iPhone.")
                                .font(.subheadline)
                                .foregroundStyle(EzcanTheme.muted)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 24)
                        .ezcanPanel(accent: EzcanTheme.cyan, glow: true)

                        Button {
                            scannerPresented = true
                        } label: {
                            Label("SCAN COMPUTER QR CODE", systemImage: "qrcode.viewfinder")
                                .font(.system(size: 14, weight: .bold, design: .rounded))
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 16)
                        }
                        .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.cyan))

                        VStack(alignment: .leading, spacing: 13) {
                            Text("MANUAL PAIRING")
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .tracking(1)
                                .foregroundStyle(EzcanTheme.cyan)
                            inputField("COMPUTER ADDRESS", text: $computerURL, placeholder: "http://192.168.1.25:8765")
                            inputField("PAIRING TOKEN", text: $token, placeholder: "Temporary token")
                            inputField("COMPUTER NAME (OPTIONAL)", text: $computerName, placeholder: "Ezcan Computer")
                            Button {
                                pairManually()
                            } label: {
                                Text("PAIR MANUALLY")
                                    .font(.system(size: 13, weight: .bold, design: .rounded))
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 14)
                            }
                            .buttonStyle(EzcanSecondaryButtonStyle())
                            .disabled(token.isEmpty || computerURL == "http://")
                            .opacity(token.isEmpty || computerURL == "http://" ? 0.45 : 1)
                        }
                        .padding(18)
                        .ezcanPanel()

                        if let errorMessage = pairingStore.errorMessage {
                            Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                                .font(.footnote)
                                .foregroundStyle(EzcanTheme.magenta)
                                .padding(16)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .ezcanPanel(accent: EzcanTheme.magenta)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 18)
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .fullScreenCover(isPresented: $scannerPresented) {
                QRScannerView { payload in
                    scannerPresented = false
                    pairFromQR(payload)
                } onCancel: {
                    scannerPresented = false
                }
            }
            .onAppear {
                guard !hasOpenedScanner else { return }
                hasOpenedScanner = true
                scannerPresented = true
            }
        }
    }

    private func pairingHeader(compact: Bool) -> some View {
        HStack(alignment: .top, spacing: compact ? 8 : 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("EZCAN")
                    .font(.system(size: compact ? 27 : 30, weight: .black, design: .rounded))
                    .tracking(2)
                    .foregroundStyle(EzcanTheme.text)
                if !compact {
                    Text("CARD OPERATIONS CONSOLE")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .tracking(0.8)
                        .foregroundStyle(EzcanTheme.cyan)
                }
            }
            Spacer()
            EzcanStatusPill(title: compact ? "PAIR" : "AWAITING PAIRING", color: EzcanTheme.amber)
        }
    }

    private func inputField(_ title: String, text: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(EzcanTheme.muted)
            TextField(placeholder, text: text)
                .font(.system(size: 14, design: .monospaced))
                .foregroundStyle(EzcanTheme.text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(.horizontal, 13)
                .padding(.vertical, 12)
                .background(EzcanTheme.panelDeep, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(EzcanTheme.border, lineWidth: 1)
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