import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var pairingStore: PairingStore
    @State private var launchPairingComplete = false

    var body: some View {
        Group {
            if pairingStore.isPaired && launchPairingComplete {
                CardCaptureFlowView()
            } else {
                PairingView {
                    launchPairingComplete = true
                }
            }
        }
        .onChange(of: pairingStore.isPaired) { _, isPaired in
            if !isPaired {
                launchPairingComplete = false
            }
        }
    }
}