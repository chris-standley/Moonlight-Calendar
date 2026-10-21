import AVFoundation
import SwiftUI

/// A camera's picture, fetched again every couple of seconds while it's on screen.
struct CameraStill: View {
    @Environment(AppModel.self) private var model
    let path: String
    let width: Int
    var contentMode: ContentMode = .fill
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Color.black
            if let image { Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode) }
        }
        .task(id: path) {
            while !Task.isCancelled {
                if let api = model.api, let url = api.resolve("\(path)?width=\(width)"),
                   let data = try? await api.data(for: api.request(url)), let img = UIImage(data: data) {
                    image = img
                }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }
}

/// A muted live HLS video, sent with this screen's token (the add-on passes Home Assistant's stream through).
struct CameraVideo: UIViewRepresentable {
    let url: URL
    let token: String?

    final class PlayerView: UIView {
        override static var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }

    func makeUIView(context: Context) -> PlayerView {
        let view = PlayerView()
        let headers = token.map { ["Authorization": "Bearer \($0)"] } ?? [:]
        let asset = AVURLAsset(url: url, options: ["AVURLAssetHTTPHeaderFieldsKey": headers])
        let player = AVPlayer(playerItem: AVPlayerItem(asset: asset))
        player.isMuted = true
        player.automaticallyWaitsToMinimizeStalling = false
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect
        player.play()
        return view
    }

    func updateUIView(_ view: PlayerView, context: Context) {}

    static func dismantleUIView(_ view: PlayerView, coordinator: ()) {
        view.playerLayer.player?.pause()
        view.playerLayer.player = nil
    }
}
