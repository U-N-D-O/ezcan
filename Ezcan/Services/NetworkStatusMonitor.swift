import Combine
import Network

final class NetworkStatusMonitor: ObservableObject {
    @Published private(set) var isOffline = true

    private let monitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "com.undu.ezcan.network-status")

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            DispatchQueue.main.async {
                self?.isOffline = path.status != .satisfied
            }
        }
        monitor.start(queue: monitorQueue)
    }

    deinit {
        monitor.cancel()
    }
}