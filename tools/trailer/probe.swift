// swift probe.swift fichier.mp4 [dossier_png_sortie] : durée, pistes, dimensions, fps, extrait 3 images
import AVFoundation
import AppKit
let a = CommandLine.arguments
let asset = AVURLAsset(url: URL(fileURLWithPath: a[1]))
let sem = DispatchSemaphore(value: 0)
Task {
  defer { sem.signal() }
  do {
  let d = try await asset.load(.duration).seconds
  print("duree_conteneur \(d)")
  for t in try await asset.load(.tracks) {
    let r = try await t.load(.timeRange).duration.seconds
    if t.mediaType == .video {
      let s = try await t.load(.naturalSize); let f = try await t.load(.nominalFrameRate)
      print("video \(Int(s.width))x\(Int(s.height)) \(f) fps duree \(r)")
    } else { print("\(t.mediaType.rawValue) duree \(r)") }
  }
  if a.count > 2 {
    try FileManager.default.createDirectory(atPath: a[2], withIntermediateDirectories: true)
    let gen = AVAssetImageGenerator(asset: asset); gen.requestedTimeToleranceBefore = .zero; gen.requestedTimeToleranceAfter = .zero
    for (i, p) in [0.1, 0.5, 0.95].enumerated() {
      let img = try gen.copyCGImage(at: CMTime(seconds: d * p, preferredTimescale: 600), actualTime: nil)
      let rep = NSBitmapImageRep(cgImage: img)
      try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[2] + "/frame\(i).png"))
    }
    print("3 images extraites")
  }
  } catch { print("erreur: \(error)") }
}
sem.wait()
