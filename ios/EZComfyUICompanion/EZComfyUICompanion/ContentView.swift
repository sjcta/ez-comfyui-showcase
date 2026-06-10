import SwiftUI

struct ContentView: View {
    @StateObject private var browser = BrowserViewModel()
    @State private var isShowingSettings = false

    var body: some View {
        VStack(spacing: 0) {
            BrowserToolbar(
                title: browser.pageTitle.isEmpty ? "EZ ComfyUI" : browser.pageTitle,
                canGoBack: browser.canGoBack,
                canGoForward: browser.canGoForward,
                goBack: browser.goBack,
                goForward: browser.goForward,
                reload: browser.reload,
                showSettings: { isShowingSettings = true }
            )

            if browser.isLoading {
                ProgressView(value: browser.estimatedProgress)
                    .progressViewStyle(.linear)
                    .frame(height: 2)
            }

            ZStack {
                WebView(browser: browser)
                    .ignoresSafeArea(edges: .bottom)

                if let errorMessage = browser.errorMessage {
                    ConnectionErrorView(
                        message: errorMessage,
                        retryAction: browser.reload
                    )
                    .padding()
                }
            }
        }
        .background(Color.black)
        .sheet(isPresented: $isShowingSettings) {
            SettingsView(currentServerURL: browser.serverURLString) { newURL in
                browser.updateServerURL(newURL)
            }
        }
        .task {
            browser.loadHomeIfNeeded()
        }
    }
}

private struct BrowserToolbar: View {
    let title: String
    let canGoBack: Bool
    let canGoForward: Bool
    let goBack: () -> Void
    let goForward: () -> Void
    let reload: () -> Void
    let showSettings: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            HStack(spacing: 0) {
                toolbarButton(systemName: "chevron.left", action: goBack)
                    .disabled(!canGoBack)
                toolbarButton(systemName: "chevron.right", action: goForward)
                    .disabled(!canGoForward)
            }
            .padding(.horizontal, 8)
            .frame(height: 48)
            .background(toolbarBackground)
            .clipShape(Capsule())

            Text(title)
                .font(.headline)
                .lineLimit(1)
                .frame(maxWidth: .infinity)
                .foregroundStyle(.white)

            HStack(spacing: 0) {
                toolbarButton(systemName: "arrow.clockwise", action: reload)
                toolbarButton(systemName: "gearshape", action: showSettings)
            }
            .padding(.horizontal, 8)
            .frame(height: 48)
            .background(toolbarBackground)
            .clipShape(Capsule())
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .background(Color.black)
    }

    private var toolbarBackground: some ShapeStyle {
        Color.white.opacity(0.08)
    }

    private func toolbarButton(systemName: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 22, weight: .semibold))
                .frame(width: 40, height: 40)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
    }
}

private struct ConnectionErrorView: View {
    let message: String
    let retryAction: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(.orange)

            VStack(spacing: 6) {
                Text("Cannot reach EZ ComfyUI")
                    .font(.headline)
                Text(message)
                    .font(.footnote)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
            }

            Button(action: retryAction) {
                Label("Retry", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(20)
        .frame(maxWidth: 360)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
