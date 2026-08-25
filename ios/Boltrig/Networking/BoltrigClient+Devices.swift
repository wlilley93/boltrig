import Foundation

extension BoltrigClient {
    /// The computers signed in to this account with Boltrig Desktop.
    func devices() async throws -> [LinkedDevice] {
        let (data, _) = try await perform(path: "/v1/devices", method: "GET", body: nil)
        return try LinkedDevice.decodeList(data)
    }

    /// Disconnects a computer: its desktop session ends at once and it has to sign in again.
    func revokeDevice(id: String) async throws {
        _ = try await perform(path: "/v1/devices/\(id)", method: "DELETE", body: nil)
    }
}
