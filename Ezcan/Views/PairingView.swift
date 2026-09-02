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
            HStack(spacing: 0) {
                pairingRail
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 18) {
                        pairingHeader
                        connectionCard
                        Button {
                            scannerPresented = true
                        } label: {
                            Label("Scan computer QR code", systemImage: "qrcode.viewfinder")
                                .font(.headline)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 16)
                        }
                        .buttonStyle(EzcanPrimaryButtonStyle(color: EzcanTheme.cyan))
                        manualPairingCard
                        if let errorMessage = pairingStore.errorMessage {
                            Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                                .font(.footnote)
                                .foregroundStyle(EzcanTheme.pink)
                                .padding(16)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .ezcanPanel(accent: EzcanTheme.pink)
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.vertical, 26)
                }
                .frame(maxWidth: .infinity)
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
            .onAppear {
                guard !hasOpenedScanner else { return }
                hasOpenedScanner = true
                scannerPresented = true
            }
        }
    }

    private var pairingRail: some View {
        VStack(spacing: 12) {
            Image("ezcan_logo")
                .resizable()
                .scaledToFit()
                .frame(width: 38, height: 38)
                .padding(.bottom, 24)
            RoundedRectangle(cornerRadius: 1)
                .fill(EzcanTheme.line)
                .frame(width: 24, height: 1)
            Spacer()
            Image(systemName: "antenna.radiowaves.left.and.right")
                .font(.title3)
                .foregroundStyle(EzcanTheme.cyan)
            Text("PAIR")
                .font(.system(size: 9, weight: .bold, design: .rounded))
                .foregroundStyle(EzcanTheme.muted)
            Spacer()
            Text("01")
                .font(.caption.monospacedDigit().bold())
                .foregroundStyle(EzcanTheme.muted)
        }
        .frame(width: 78)
        .padding(.vertical, 24)
        .background(EzcanTheme.white, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .shadow(color: EzcanTheme.shadow, radius: 14, y: 5)
        .padding(.leading, 12)
        .padding(.vertical, 14)
    }

    private var pairingHeader: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Welcome back")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(EzcanTheme.muted)
                Text("Connect your workspace")
                    .font(.system(size: 27, weight: .bold, design: .rounded))
                    .foregroundStyle(EzcanTheme.ink)
            }
            Spacer()
            EzcanStatusPill(title: "AWAITING PAIRING", color: EzcanTheme.amber)
        }
    }

    private var connectionCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Image(systemName: "link.circle.fill")
                    .font(.system(size: 27))
                    .foregroundStyle(EzcanTheme.cyan)
                Spacer()
                Text("01")
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(EzcanTheme.muted)
            }
            Text("Connect to Ezcan")
                .font(.title2.bold())
                .foregroundStyle(EzcanTheme.ink)
            Text("Scan the QR code shown in Ezcan Computer to begin.")
                .font(.subheadline)
                .foregroundStyle(EzcanTheme.muted)
        }
        .padding(24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .ezcanPanel(accent: EzcanTheme.cyan, glow: true)
    }

    private var manualPairingCard: some View {
        VStack(alignment: .leading, spacing: 13) {
            Text("Enter details manually")
                .font(.headline)
                .foregroundStyle(EzcanTheme.ink)
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
        .ezcanPanel()
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