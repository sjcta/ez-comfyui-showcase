import Foundation

final class SettingsStore {
    static let shared = SettingsStore()

    private enum Key {
        static let serverURLString = "serverURLString"
    }

    private let defaults: UserDefaults
    private let bundledServerURLString: String

    init(defaults: UserDefaults = .standard, bundle: Bundle = .main) {
        self.defaults = defaults
        self.bundledServerURLString = bundle.object(forInfoDictionaryKey: "EZComfyUIServerURL") as? String
            ?? "https://imdjj.cn:1313/comfy/"
    }

    var serverURLString: String {
        get {
            defaults.string(forKey: Key.serverURLString) ?? bundledServerURLString
        }
        set {
            defaults.set(Self.normalizedURLString(from: newValue), forKey: Key.serverURLString)
        }
    }

    static func normalizedURLString(from rawValue: String) -> String {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "https://imdjj.cn:1313/comfy/" }

        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return trimmed
        }

        return "https://\(trimmed)"
    }
}
