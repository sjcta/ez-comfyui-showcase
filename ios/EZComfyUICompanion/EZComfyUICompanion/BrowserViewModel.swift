import Foundation
import Photos
import UIKit
import UserNotifications
import WebKit

@MainActor
final class BrowserViewModel: NSObject, ObservableObject {
    @Published private(set) var pageTitle = ""
    @Published private(set) var isLoading = false
    @Published private(set) var estimatedProgress = 0.0
    @Published private(set) var canGoBack = false
    @Published private(set) var canGoForward = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var serverURLString: String

    let webView: WKWebView

    private var didLoadInitialURL = false
    private var observations: [NSKeyValueObservation] = []
    private let settingsStore: SettingsStore
    private let saveImageMessageHandler = SaveImageMessageHandler()
    private var jobNotificationTimer: Timer?
    private var knownJobStatuses: [String: String] = [:]
    private var hasLoadedJobNotificationBaseline = false
    private var notifiedJobIDs: Set<String> = []

    init(settingsStore: SettingsStore = .shared) {
        self.settingsStore = settingsStore
        self.serverURLString = settingsStore.serverURLString

        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []

        if #available(iOS 14.0, *) {
            configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        }

        self.webView = WKWebView(frame: .zero, configuration: configuration)

        super.init()

        saveImageMessageHandler.delegate = self
        webView.configuration.userContentController.add(saveImageMessageHandler, name: "ezSaveImage")
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        UNUserNotificationCenter.current().delegate = self
        requestNotificationPermission()
        loadNotifiedJobIDs()
        observeWebViewState()
    }

    func loadHomeIfNeeded() {
        guard !didLoadInitialURL else { return }
        didLoadInitialURL = true
        load(serverURLString)
    }

    func updateServerURL(_ newValue: String) {
        let normalized = SettingsStore.normalizedURLString(from: newValue)
        serverURLString = normalized
        settingsStore.serverURLString = normalized
        resetJobNotificationState()
        load(normalized)
    }

    func reload() {
        errorMessage = nil
        if webView.url == nil {
            load(serverURLString)
        } else {
            webView.reload()
        }
    }

    func goBack() {
        guard webView.canGoBack else { return }
        webView.goBack()
    }

    func goForward() {
        guard webView.canGoForward else { return }
        webView.goForward()
    }

    private func load(_ urlString: String) {
        guard let url = URL(string: SettingsStore.normalizedURLString(from: urlString)) else {
            errorMessage = "The server URL is invalid."
            return
        }

        errorMessage = nil
        webView.load(URLRequest(url: url))
    }

    private func observeWebViewState() {
        observations = [
            webView.observe(\.title, options: [.initial, .new]) { [weak self] webView, _ in
                Task { @MainActor in
                    self?.pageTitle = webView.title ?? ""
                }
            },
            webView.observe(\.isLoading, options: [.initial, .new]) { [weak self] webView, _ in
                Task { @MainActor in
                    self?.isLoading = webView.isLoading
                }
            },
            webView.observe(\.estimatedProgress, options: [.initial, .new]) { [weak self] webView, _ in
                Task { @MainActor in
                    self?.estimatedProgress = webView.estimatedProgress
                }
            },
            webView.observe(\.canGoBack, options: [.initial, .new]) { [weak self] webView, _ in
                Task { @MainActor in
                    self?.canGoBack = webView.canGoBack
                }
            },
            webView.observe(\.canGoForward, options: [.initial, .new]) { [weak self] webView, _ in
                Task { @MainActor in
                    self?.canGoForward = webView.canGoForward
                }
            }
        ]
    }
}

private extension BrowserViewModel {
    struct NativeJobSnapshot {
        let id: String
        let status: String
        let title: String
        let message: String
    }

    func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    func startJobNotificationPolling() {
        guard jobNotificationTimer == nil else { return }
        pollJobsForNotifications()
        jobNotificationTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.pollJobsForNotifications()
            }
        }
    }

    func resetJobNotificationState() {
        jobNotificationTimer?.invalidate()
        jobNotificationTimer = nil
        knownJobStatuses.removeAll()
        hasLoadedJobNotificationBaseline = false
    }

    func pollJobsForNotifications() {
        guard let jobsURL = apiURL(path: "api/jobs") else { return }
        guard let urlLiteral = javascriptStringLiteral(jobsURL.absoluteString) else { return }
        let script = """
        (function() {
          return fetch(\(urlLiteral), { credentials: 'include', cache: 'no-store' })
            .then(function(response) {
              if (!response.ok) return { ok: false, status: response.status };
              return response.json().then(function(jobs) { return { ok: true, jobs: jobs }; });
            })
            .catch(function(error) { return { ok: false, error: String(error && error.message || error) }; });
        })();
        """

        webView.evaluateJavaScript(script) { [weak self] result, _ in
            Task { @MainActor in
                self?.handleJobsPollingResult(result)
            }
        }
    }

    func handleJobsPollingResult(_ result: Any?) {
        guard
            let payload = result as? [String: Any],
            (payload["ok"] as? Bool) == true,
            let rawJobs = payload["jobs"] as? [[String: Any]]
        else {
            return
        }

        let snapshots = rawJobs.compactMap(NativeJobSnapshot.init)
        let previousStatuses = knownJobStatuses
        for snapshot in snapshots {
            knownJobStatuses[snapshot.id] = snapshot.status
        }

        guard hasLoadedJobNotificationBaseline else {
            hasLoadedJobNotificationBaseline = true
            return
        }

        for snapshot in snapshots {
            guard isFinalNotificationStatus(snapshot.status) else { continue }
            guard previousStatuses[snapshot.id] != snapshot.status else { continue }
            guard !notifiedJobIDs.contains(snapshot.id) else { continue }
            notifiedJobIDs.insert(snapshot.id)
            persistNotifiedJobIDs()
            sendJobNotification(for: snapshot)
        }
    }

    func isFinalNotificationStatus(_ status: String) -> Bool {
        status == "done" || status == "history" || status == "error"
    }

    func sendJobNotification(for job: NativeJobSnapshot) {
        let content = UNMutableNotificationContent()
        if job.status == "error" {
            content.title = "EZ ComfyUI 任务失败"
            content.body = job.message.isEmpty ? job.title : job.message
            content.sound = .default
        } else {
            content.title = "EZ ComfyUI 任务完成"
            content.body = job.title.isEmpty ? "生成结果已准备好" : job.title
            content.sound = .default
        }

        let request = UNNotificationRequest(
            identifier: "ez-comfyui-job-\(job.id)-\(job.status)",
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    func apiURL(path: String) -> URL? {
        guard let baseURL = URL(string: SettingsStore.normalizedURLString(from: serverURLString)) else { return nil }
        return URL(string: path, relativeTo: baseURL)?.absoluteURL
    }

    func javascriptStringLiteral(_ value: String) -> String? {
        guard
            let data = try? JSONSerialization.data(withJSONObject: [value]),
            let encoded = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return String(encoded.dropFirst().dropLast())
    }

    func loadNotifiedJobIDs() {
        let ids = UserDefaults.standard.stringArray(forKey: "notifiedJobIDs") ?? []
        notifiedJobIDs = Set(ids)
    }

    func persistNotifiedJobIDs() {
        let trimmed = Array(notifiedJobIDs.suffix(200))
        notifiedJobIDs = Set(trimmed)
        UserDefaults.standard.set(trimmed, forKey: "notifiedJobIDs")
    }
}

private extension BrowserViewModel.NativeJobSnapshot {
    init?(_ raw: [String: Any]) {
        guard let id = raw["id"].map({ String(describing: $0) }), !id.isEmpty else { return nil }
        self.id = id
        self.status = (raw["status"] as? String ?? "").lowercased()
        let workflow = (raw["workflow"] as? String ?? "")
            .replacingOccurrences(of: ".json", with: "")
        self.title = (raw["prompt_preview"] as? String)
            ?? (raw["prompt"] as? String)
            ?? workflow
        self.message = raw["message"] as? String ?? ""
    }
}

private final class SaveImageMessageHandler: NSObject, WKScriptMessageHandler {
    weak var delegate: BrowserViewModel?

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "ezSaveImage" else { return }
        let body = message.body
        Task { @MainActor [weak self] in
            self?.delegate?.handleSaveImageMessage(body)
        }
    }
}

extension BrowserViewModel {
    private struct MediaPayload {
        let data: Data
        let mimeType: String
    }

    fileprivate func handleSaveImageMessage(_ body: Any) {
        guard
            let payload = body as? [String: Any],
            let dataURL = payload["dataUrl"] as? String
        else {
            notifyNativeSaveResult(ok: false, message: "保存失败：媒体数据无效")
            return
        }

        let filename = (payload["filename"] as? String) ?? "image.png"
        let mediaType = ((payload["mediaType"] as? String) ?? "").lowercased()
        guard let media = mediaPayload(from: dataURL) else {
            notifyNativeSaveResult(ok: false, message: "保存失败：无法读取媒体")
            return
        }

        if mediaType == "video" || media.mimeType.hasPrefix("video/") {
            saveVideoDataToPhotoLibrary(media.data, filename: filename, mimeType: media.mimeType)
        } else if media.mimeType.hasPrefix("image/") {
            saveImageDataToPhotoLibrary(media.data, filename: filename)
        } else {
            notifyNativeSaveResult(ok: false, message: "保存失败：不支持的媒体类型")
        }
    }

    private func mediaPayload(from dataURL: String) -> MediaPayload? {
        guard let comma = dataURL.firstIndex(of: ",") else { return nil }
        let meta = dataURL[..<comma].lowercased()
        guard meta.hasPrefix("data:"), meta.contains(";base64") else { return nil }
        let mimeType = meta
            .dropFirst("data:".count)
            .split(separator: ";", maxSplits: 1)
            .first
            .map(String.init) ?? ""
        let base64 = dataURL[dataURL.index(after: comma)...]
        guard let data = Data(base64Encoded: String(base64)) else { return nil }
        return MediaPayload(data: data, mimeType: mimeType)
    }

    private func saveImageDataToPhotoLibrary(_ data: Data, filename: String) {
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { [weak self] status in
            guard status == .authorized || status == .limited else {
                Task { @MainActor in
                    self?.notifyNativeSaveResult(ok: false, message: "保存失败：未授权访问相册")
                }
                return
            }

            PHPhotoLibrary.shared().performChanges {
                let request = PHAssetCreationRequest.forAsset()
                let options = PHAssetResourceCreationOptions()
                options.originalFilename = filename
                request.addResource(with: .photo, data: data, options: options)
            } completionHandler: { [weak self] success, error in
                Task { @MainActor in
                    self?.notifyNativeSaveResult(
                        ok: success,
                        message: success ? "已保存到相册" : (error?.localizedDescription ?? "保存到相册失败")
                    )
                }
            }
        }
    }

    private func saveVideoDataToPhotoLibrary(_ data: Data, filename: String, mimeType: String) {
        let tempURL: URL
        do {
            tempURL = try writeTemporaryVideo(data, filename: filename, mimeType: mimeType)
        } catch {
            notifyNativeSaveResult(ok: false, message: "保存失败：无法准备视频文件")
            return
        }

        PHPhotoLibrary.requestAuthorization(for: .addOnly) { [weak self] status in
            guard status == .authorized || status == .limited else {
                try? FileManager.default.removeItem(at: tempURL)
                Task { @MainActor in
                    self?.notifyNativeSaveResult(ok: false, message: "保存失败：未授权访问相册")
                }
                return
            }

            PHPhotoLibrary.shared().performChanges {
                let request = PHAssetCreationRequest.forAsset()
                let options = PHAssetResourceCreationOptions()
                options.originalFilename = filename
                request.addResource(with: .video, fileURL: tempURL, options: options)
            } completionHandler: { [weak self] success, error in
                try? FileManager.default.removeItem(at: tempURL)
                Task { @MainActor in
                    self?.notifyNativeSaveResult(
                        ok: success,
                        message: success ? "已保存到相册" : (error?.localizedDescription ?? "保存到相册失败")
                    )
                }
            }
        }
    }

    private func writeTemporaryVideo(_ data: Data, filename: String, mimeType: String) throws -> URL {
        let filenameExt = URL(fileURLWithPath: filename).pathExtension
        let ext = filenameExt.isEmpty ? videoExtension(for: mimeType) : filenameExt
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension(ext)
        try data.write(to: url, options: [.atomic])
        return url
    }

    private func videoExtension(for mimeType: String) -> String {
        switch mimeType.lowercased() {
        case "video/quicktime":
            return "mov"
        case "video/webm":
            return "webm"
        case "video/x-m4v":
            return "m4v"
        default:
            return "mp4"
        }
    }

    private func notifyNativeSaveResult(ok: Bool, message: String) {
        let payload: [String: Any] = [
            "ok": ok,
            "message": message
        ]
        guard
            let data = try? JSONSerialization.data(withJSONObject: payload),
            let json = String(data: data, encoding: .utf8)
        else {
            return
        }
        let script = "window.dispatchEvent(new CustomEvent('ezNativeSaveImageResult',{detail:\(json)}));"
        webView.evaluateJavaScript(script)
    }
}

extension BrowserViewModel: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        errorMessage = nil
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        handleNavigationError(error)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handleNavigationError(error)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        errorMessage = nil
        startJobNotificationPolling()
    }

    private func handleNavigationError(_ error: Error) {
        let nsError = error as NSError
        guard nsError.code != NSURLErrorCancelled else { return }
        errorMessage = nsError.localizedDescription
    }
}

extension BrowserViewModel: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}

extension BrowserViewModel: WKUIDelegate {
    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping () -> Void
    ) {
        guard let presenter = topViewController() else {
            completionHandler()
            return
        }

        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "确定", style: .default) { _ in
            completionHandler()
        })
        presenter.present(alert, animated: true)
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping (Bool) -> Void
    ) {
        guard let presenter = topViewController() else {
            completionHandler(false)
            return
        }

        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in
            completionHandler(false)
        })
        alert.addAction(UIAlertAction(title: "确定", style: .destructive) { _ in
            completionHandler(true)
        })
        presenter.present(alert, animated: true)
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if navigationAction.targetFrame == nil {
            webView.load(navigationAction.request)
        }
        return nil
    }

    private func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let root = scenes
            .flatMap { $0.windows }
            .first(where: { $0.isKeyWindow })?
            .rootViewController
        return topViewController(from: root)
    }

    private func topViewController(from controller: UIViewController?) -> UIViewController? {
        if let navigation = controller as? UINavigationController {
            return topViewController(from: navigation.visibleViewController)
        }
        if let tab = controller as? UITabBarController {
            return topViewController(from: tab.selectedViewController)
        }
        if let presented = controller?.presentedViewController {
            return topViewController(from: presented)
        }
        return controller
    }
}
