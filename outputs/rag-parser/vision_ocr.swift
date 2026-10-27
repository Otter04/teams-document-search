import Foundation
import Vision
import ImageIO

// Local macOS baseline. Coordinates are normalized, origin at top-left.
// No language model calls or network requests are performed.
do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let supported = try request.supportedRecognitionLanguages()
    if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--languages" {
        let data = try JSONSerialization.data(withJSONObject: ["supported_languages": supported, "revision": request.revision], options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
        exit(0)
    }
    guard CommandLine.arguments.count == 2 else {
        throw NSError(domain: "ocr", code: 1, userInfo: [NSLocalizedDescriptionKey: "usage: vision-ocr IMAGE_PATH"])
    }
    guard supported.contains("ko-KR") else {
        throw NSError(domain: "ocr", code: 2, userInfo: [NSLocalizedDescriptionKey: "Korean OCR is not supported by this OS revision"])
    }
    request.recognitionLanguages = ["ko-KR", "en-US"]
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let handler = VNImageRequestHandler(url: url, options: [:])
    try handler.perform([request])
    let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": text.string, "confidence": Double(text.confidence),
                "bbox": [Double(b.minX), Double(1-b.maxY), Double(b.maxX), Double(1-b.minY)]]
    }
    let result: [String: Any] = ["engine": "Apple Vision", "revision": request.revision,
        "languages": request.recognitionLanguages, "language_correction": false, "lines": lines]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
} catch {
    fputs("OCR error: \(error)\n", stderr)
    exit(1)
}
