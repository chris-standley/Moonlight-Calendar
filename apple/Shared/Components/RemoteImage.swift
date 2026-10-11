import SwiftUI
import UIKit

/// Loads an image from the add-on with this Apple TV's token (photos and album art are behind `/api`).
@MainActor
final class ImageCache {
    static let shared = ImageCache()
    private let cache = NSCache<NSURL, UIImage>()

    init() { cache.countLimit = 40 }

    func image(_ url: URL, api: APIClient) async -> UIImage? {
        if let hit = cache.object(forKey: url as NSURL) { return hit }
        guard let data = try? await api.data(for: api.request(url)), let img = UIImage(data: data) else { return nil }
        cache.setObject(img, forKey: url as NSURL)
        return img
    }
}

struct RemoteImage: View {
    @Environment(AppModel.self) private var model
    let path: String?
    var contentMode: ContentMode = .fill
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode)
                    .transition(.opacity)
            }
        }
        .task(id: path) {
            guard let path, let api = model.api, let url = api.resolve(path) else { image = nil; return }
            let img = await ImageCache.shared.image(url, api: api)
            withAnimation(.easeInOut(duration: 0.6)) { image = img }
        }
    }
}
