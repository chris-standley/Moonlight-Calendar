import SwiftUI

/// A shop product found by its barcode, for the shopping list: the exact product and plain names for it.
struct Product: Codable, Hashable {
    let code: String
    /// False when no product database knows it: `exact` is nil and `options` empty.
    let found: Bool
    /// "Tesco Semi Skimmed Milk 2L"
    let exact: String?
    /// "Semi skimmed milk", "Milk": most to least specific.
    let options: [String]
    let image_url: String?
    /// What was added the last time this barcode was scanned.
    let last: String?
}

extension APIClient {
    /// The product with this barcode, looked up on Moonlight (Open Food Facts) the first time.
    func findProduct(_ code: String) async throws -> Product {
        try await get("/api/products/\(code.filter(\.isNumber))")
    }
}

/// Scan products onto a shopping list one after another: the camera finds the barcode, then a tap picks what to
/// call it, the exact product or the plain item, and the camera comes back for the next one.
struct ProductScanSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let list: TaskList
    @State private var code: String?
    @State private var product: Product?
    @State private var failed = false
    @State private var name = ""
    @State private var added = 0
    @State private var busy = false

    static var isAvailable: Bool { BarcodeCamera.isAvailable }

    /// A shop barcode: EAN-13 (the camera reads an American UPC-A as one too) or EAN-8 on small packs.
    static func shopCode(_ value: String) -> String? {
        value.allSatisfy(\.isNumber) && (value.count == 13 || value.count == 8) ? value : nil
    }

    var body: some View {
        NavigationStack {
            Group {
                if let code {
                    choices(code)
                } else {
                    BarcodeCamera(symbologies: [.ean13, .ean8], accept: Self.shopCode) { found in
                        code = found
                        Task { await look(found) }
                    }
                    .ignoresSafeArea(edges: .bottom)
                    .overlay(alignment: .bottom) {
                        Text(added == 0 ? "Point the camera at the barcode." : "\(added) added. Scan the next one, or tap Done.")
                            .font(Theme.text(.headline, .bold)).multilineTextAlignment(.center)
                            .foregroundStyle(.white)
                            .padding(20)
                            .frame(maxWidth: .infinity)
                            .background(.black.opacity(0.55))
                    }
                }
            }
            .navigationTitle("Scan onto \(list.name)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }

    @ViewBuilder private func choices(_ code: String) -> some View {
        Form {
            if let product {
                Section {
                    HStack(spacing: 12) {
                        // Not RemoteImage: that sends Moonlight's sign-in with the request, and this picture is
                        // on Open Food Facts.
                        AsyncImage(url: product.image_url.flatMap(URL.init(string:))) { img in
                            img.resizable().aspectRatio(contentMode: .fit)
                        } placeholder: {
                            Text("🛒").font(.system(size: 30))
                        }
                        .frame(width: 56, height: 56)
                        .background(Color.white)
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(product.found ? "Add it as" : "Not one we know").font(Theme.text(.body, .bold))
                            Text(product.found ? "Tap one" : "What is it? Moonlight remembers for next time.")
                                .font(Theme.text(.footnote)).foregroundStyle(Theme.muted)
                        }
                    }
                }
                let names = names(product)
                if !names.isEmpty {
                    Section {
                        ForEach(names, id: \.title) { n in
                            Button { Task { await add(n.title, code) } } label: {
                                HStack {
                                    Text(n.title).font(Theme.text(.body, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    if product.last?.lowercased() == n.title.lowercased() {
                                        Text("Last time").font(Theme.text(.caption, .heavy)).foregroundStyle(Color(hex: list.color))
                                    } else if !n.tag.isEmpty {
                                        Text(n.tag).font(Theme.text(.caption, .bold)).foregroundStyle(Theme.muted)
                                    }
                                }
                            }
                            .disabled(busy)
                        }
                    }
                }
                Section {
                    HStack {
                        TextField(product.found ? "Or call it something else" : "e.g. Kitchen roll", text: $name)
                            .submitLabel(.done)
                            .onSubmit { Task { await add(name, code) } }
                        Button("Add") { Task { await add(name, code) } }
                            .buttonStyle(.borderless)
                            .disabled(busy || name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                Section {
                    Button("Scan another") { reset() }
                }
            } else if failed {
                Section {
                    Text("Couldn't look that barcode up.").foregroundStyle(Theme.danger)
                    Button("Try again") { Task { await look(code) } }
                    Button("Scan another") { reset() }
                }
            } else {
                HStack { Spacer(); ProgressView("Looking it up…"); Spacer() }.listRowBackground(Color.clear)
            }
        }
    }

    private struct Choice: Hashable { let title: String; let tag: String }

    private func names(_ p: Product) -> [Choice] {
        var out = (p.exact.map { [Choice(title: $0, tag: "This product")] } ?? []) + p.options.map { Choice(title: $0, tag: "Any") }
        if let last = p.last, !out.contains(where: { $0.title.lowercased() == last.lowercased() }) {
            out.insert(Choice(title: last, tag: ""), at: 0)
        }
        return out
    }

    private func look(_ code: String) async {
        failed = false
        product = nil
        if let p = await model.call({ try await $0.findProduct(code) }) {
            product = p
            name = p.found ? "" : p.last ?? ""
        } else {
            failed = true
        }
    }

    private func add(_ title: String, _ code: String) async {
        let title = title.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty, !busy else { return }
        busy = true
        defer { busy = false }
        if await model.call({ try await $0.addItem(list.id, title: title, barcode: code) }) != nil {
            added += 1
            model.bump("lists")
            reset()
        }
    }

    private func reset() {
        code = nil
        product = nil
        failed = false
        name = ""
    }
}
