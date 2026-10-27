import Foundation
import Vision
import ImageIO

// Accurate recognition twice: raw characters plus conservative spacing correction.
// A corrected line is accepted only when its non-whitespace characters equal raw.
func compact(_ s: String) -> String { s.filter { !$0.isWhitespace } }
func lines(_ request: VNRecognizeTextRequest) -> [[String: Any]] {
    (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": text.string, "confidence": Double(text.confidence),
                "bbox": [Double(b.minX), Double(1-b.maxY), Double(b.maxX), Double(1-b.minY)]]
    }
}
func overlap(_ a: [Double], _ b: [Double]) -> Double {
    let intersection = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection / max(0.0000001,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)
}
do {
    let raw = VNRecognizeTextRequest()
    raw.recognitionLevel = .accurate
    raw.usesLanguageCorrection = false
    let supported = try raw.supportedRecognitionLanguages()
    if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--languages" {
        let data = try JSONSerialization.data(withJSONObject: ["supported_languages": supported, "revision": raw.revision], options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
        exit(0)
    }
    guard CommandLine.arguments.count == 2, supported.contains("ko-KR") else {
        throw NSError(domain: "ocr", code: 1, userInfo: [NSLocalizedDescriptionKey: "usage: vision-ocr IMAGE_PATH; Korean support required"])
    }
    raw.recognitionLanguages = ["ko-KR", "en-US"]
    let corrected = VNRecognizeTextRequest()
    corrected.recognitionLevel = .accurate
    corrected.revision = raw.revision
    corrected.usesLanguageCorrection = true
    corrected.recognitionLanguages = raw.recognitionLanguages
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]), options: [:])
    try handler.perform([raw,corrected])
    let alternatives = lines(corrected)
    let output = lines(raw).map { line -> [String: Any] in
        var value = line
        let original = line["text"] as! String
        value["raw_text"] = original
        let box = line["bbox"] as! [Double]
        let matched = alternatives.max { overlap(box,$0["bbox"] as! [Double]) < overlap(box,$1["bbox"] as! [Double]) }
        if let candidate = matched, overlap(box,candidate["bbox"] as! [Double]) > 0.7 {
            let text = candidate["text"] as! String
            if compact(original) == compact(text) {
                value["text"] = text
                value["spacing_correction_applied"] = original != text
            } else if original != text {
                value["unaccepted_language_alternative"] = text
            }
        }
        return value
    }
    let result: [String: Any] = ["engine": "Apple Vision", "revision": raw.revision,
        "languages": raw.recognitionLanguages, "correction_policy": "spacing_only_if_nonspace_characters_equal", "lines": output]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
} catch {
    fputs("OCR error: \(error)\n", stderr)
    exit(1)
}
