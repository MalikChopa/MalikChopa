// swift mux.swift <dossier_png> <audio.wav> <sortie.mp4> [fps=30]
import AVFoundation
import CoreVideo
import CoreImage
import AppKit

let a = CommandLine.arguments
guard a.count >= 4 else { print("usage: mux.swift frames_dir audio.wav out.mp4 [fps]"); exit(2) }
let dir = a[1], wav = a[2], outPath = a[3]
let fps: Int32 = a.count > 4 ? Int32(a[4])! : 30
let files = try! FileManager.default.contentsOfDirectory(atPath: dir).filter { $0.hasPrefix("f") && $0.hasSuffix(".png") && $0.count == 10 }.sorted()
let W = 1280, H = 720
try? FileManager.default.removeItem(atPath: outPath)
let writer = try! AVAssetWriter(outputURL: URL(fileURLWithPath: outPath), fileType: .mp4)
writer.shouldOptimizeForNetworkUse = true
let vin = AVAssetWriterInput(mediaType: .video, outputSettings: [
  AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: W, AVVideoHeightKey: H,
  AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 8_000_000,
    AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    AVVideoMaxKeyFrameIntervalKey: 60, AVVideoExpectedSourceFrameRateKey: 30]])
vin.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: vin, sourcePixelBufferAttributes: [
  kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
  kCVPixelBufferWidthKey as String: W, kCVPixelBufferHeightKey as String: H])
var ch: [String: Any] = [:]
var cl = AudioChannelLayout(); cl.mChannelLayoutTag = kAudioChannelLayoutTag_Stereo
let ain = AVAssetWriterInput(mediaType: .audio, outputSettings: [
  AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 48000, AVNumberOfChannelsKey: 2,
  AVEncoderBitRateKey: 192000,
  AVChannelLayoutKey: Data(bytes: &cl, count: MemoryLayout<AudioChannelLayout>.size)])
ain.expectsMediaDataInRealTime = false
writer.add(vin); writer.add(ain)

let reader = try! AVAssetReader(asset: AVURLAsset(url: URL(fileURLWithPath: wav)))
let rout = AVAssetReaderTrackOutput(track: reader.asset.tracks(withMediaType: .audio)[0], outputSettings: [
  AVFormatIDKey: kAudioFormatLinearPCM, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false,
  AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false,
  AVSampleRateKey: 48000, AVNumberOfChannelsKey: 2])
reader.add(rout)
guard reader.startReading(), writer.startWriting() else { print("erreur", reader.error as Any, writer.error as Any); exit(1) }
writer.startSession(atSourceTime: .zero)

func buffer(_ path: String) -> CVPixelBuffer {
  let img = NSImage(contentsOfFile: path)!.cgImage(forProposedRect: nil, context: nil, hints: nil)!
  var pb: CVPixelBuffer?
  CVPixelBufferCreate(nil, W, H, kCVPixelFormatType_32BGRA, nil, &pb)
  CVPixelBufferLockBaseAddress(pb!, [])
  let ctx = CGContext(data: CVPixelBufferGetBaseAddress(pb!), width: W, height: H, bitsPerComponent: 8,
    bytesPerRow: CVPixelBufferGetBytesPerRow(pb!), space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
  ctx.interpolationQuality = .none
  ctx.draw(img, in: CGRect(x: 0, y: 0, width: W, height: H))
  CVPixelBufferUnlockBaseAddress(pb!, [])
  return pb!
}
let g = DispatchGroup()
g.enter()
var idx = 0
let vq = DispatchQueue(label: "v")
vin.requestMediaDataWhenReady(on: vq) {
  while vin.isReadyForMoreMediaData {
    if idx >= files.count { vin.markAsFinished(); g.leave(); return }
    adaptor.append(buffer(dir + "/" + files[idx]), withPresentationTime: CMTime(value: CMTimeValue(idx), timescale: fps))
    idx += 1
  }
}
g.enter()
let aq = DispatchQueue(label: "a")
ain.requestMediaDataWhenReady(on: aq) {
  while ain.isReadyForMoreMediaData {
    if let s = rout.copyNextSampleBuffer() { ain.append(s) } else { ain.markAsFinished(); g.leave(); return }
  }
}
g.wait()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
print(writer.status == .completed ? "ok \(files.count) images" : "echec \(String(describing: writer.error))")
