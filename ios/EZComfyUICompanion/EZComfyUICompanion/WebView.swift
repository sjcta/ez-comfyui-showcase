import SwiftUI
import WebKit

struct WebView: UIViewRepresentable {
    @ObservedObject var browser: BrowserViewModel

    func makeUIView(context: Context) -> WKWebView {
        browser.webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
    }
}
