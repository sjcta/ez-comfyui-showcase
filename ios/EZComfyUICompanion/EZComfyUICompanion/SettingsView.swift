import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var serverURL: String

    let onSave: (String) -> Void

    init(currentServerURL: String, onSave: @escaping (String) -> Void) {
        self._serverURL = State(initialValue: currentServerURL)
        self.onSave = onSave
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("https://imdjj.cn:1313/comfy/", text: $serverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                }

                Section {
                    Button {
                        onSave(serverURL)
                        dismiss()
                    } label: {
                        Label("Save and Reload", systemImage: "arrow.clockwise.circle")
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}
