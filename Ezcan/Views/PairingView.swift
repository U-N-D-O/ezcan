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
            Form {
                Section {
                    Image("ezcan_logo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 128, height: 128)
                        .frame(maxWidth: .infinity)
                    Text("Scan the QR code in Ezcan Computer to connect this iPhone.")
                        .frame(maxWidth: .infinity)
                        .multilineTextAlignment(.center)
                }

                Section("Pair with computer") {
                    Button {
                        scannerPresented = true
                    } label: {
                        Label("Scan computer QR code", systemImage: "qrcode.viewfinder")
                    }

                    TextField("Computer address", text: $computerURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    TextField("Pairing token", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Computer name (optional)", text: $computerName)
                    Button("Pair manually") {
                        pairManually()
                    }
                    .disabled(token.isEmpty || computerURL == "http://")
                }

                if let errorMessage = pairingStore.errorMessage {
                    Section {
                        Label(errorMessage, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Connect Ezcan")
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