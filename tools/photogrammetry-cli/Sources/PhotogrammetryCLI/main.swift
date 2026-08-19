//
//  photogrammetry-cli
//
//  Minimal Mac command line front end for RealityKit's PhotogrammetrySession.
//  Written for scan2cad WI-14: turn a folder of stills into a metric-scaled
//  mesh that `scan2cad describe` / `scan2cad draft` can read.
//
//  Assumes:
//    - macOS 14 or later on Apple silicon (PhotogrammetrySession.isSupported).
//    - The input folder holds only the capture images (HEIC or JPEG), one
//      object, reasonable overlap. The session reads the folder itself; this
//      tool does not filter or reorder the files.
//    - The output path names a FILE ending in .usdz or .obj. RealityKit
//      itself writes USDZ only: .usda, .usd, .obj and bare directory paths
//      are all rejected with invalidOutput on the macOS 26 SDK. Asking for
//      .obj therefore reconstructs to a sibling .usdz first and converts it
//      with Model I/O, which is what scan2cad reads.
//
//  All printed text is plain ASCII, one fact per line, no tables and no
//  progress bar art (scan2cad screen-reader rule).
//

import Foundation
import ModelIO
import RealityKit

// MARK: - Exit codes

/// Process exit codes. Kept small and stable so shell callers can branch.
enum ExitCode: Int32 {
    case success = 0
    case usage = 2
    case unsupportedHardware = 3
    case sessionFailure = 4
}

/// Writes a line to standard error and exits.
///
/// Assumes the message is a single short ASCII sentence with no trailing
/// newline.
func fail(_ message: String, _ code: ExitCode) -> Never {
    FileHandle.standardError.write(Data(("error: " + message + "\n").utf8))
    exit(code.rawValue)
}

/// Writes a line to standard output immediately.
///
/// Used instead of print() so output stays ordered when stdout is a pipe.
func say(_ message: String) {
    FileHandle.standardOutput.write(Data((message + "\n").utf8))
    fflush(stdout)
}

// MARK: - Options

/// Detail level names accepted on the command line.
///
/// These map one to one onto PhotogrammetrySession.Request.Detail. `custom`
/// is deliberately not exposed: it needs a CustomDetailSpecification that this
/// tool does not build.
let detailByName: [String: PhotogrammetrySession.Request.Detail] = [
    "preview": .preview,
    "reduced": .reduced,
    "medium": .medium,
    "full": .full,
    "raw": .raw,
]

/// Feature sensitivity names accepted on the command line.
let sensitivityByName: [String: PhotogrammetrySession.Configuration.FeatureSensitivity] = [
    "normal": .normal,
    "high": .high,
]

/// Sample ordering names accepted on the command line.
///
/// `sequential` is a speed hint: use it only when consecutive images in the
/// folder are spatially adjacent, which is true for a single steady orbit.
let orderingByName: [String: PhotogrammetrySession.Configuration.SampleOrdering] = [
    "unordered": .unordered,
    "sequential": .sequential,
]

/// Parsed command line options.
struct Options {
    var inputFolder: URL
    var output: URL
    var detail: PhotogrammetrySession.Request.Detail
    var sensitivity: PhotogrammetrySession.Configuration.FeatureSensitivity
    var ordering: PhotogrammetrySession.Configuration.SampleOrdering
}

let usageText = """
photogrammetry-cli: reconstruct a mesh from a folder of photos.

Usage:
  photogrammetry-cli <input-folder> <output-path> [options]

Arguments:
  input-folder   Folder holding the capture images (HEIC or JPEG).
  output-path    A file path ending in .usdz or .obj.
                 RealityKit writes USDZ only. Asking for .obj also
                 writes the .usdz beside it, then converts, and
                 leaves an .mtl sidecar. Give OBJ its own folder.

Options:
  --detail <level>       preview, reduced, medium, full, or raw.
                         Default is medium.
  --sensitivity <level>  normal or high. Default is normal.
                         Use high for low-texture or matte objects.
  --ordering <mode>      unordered or sequential. Default is unordered.
                         Use sequential only for a single steady orbit.
  -h, --help             Print this message.

Notes:
  Output is metric. RealityKit reports positions in meters.
  Run scan2cad with --units m on the resulting mesh.
"""

/// Parses the command line.
///
/// Assumes `arguments` excludes the executable path. Exits with the usage
/// code on any unknown flag, missing value, or wrong argument count, so the
/// caller never receives a half-built Options value.
func parseOptions(_ arguments: [String]) -> Options {
    if arguments.isEmpty || arguments.contains("-h") || arguments.contains("--help") {
        say(usageText)
        exit(arguments.isEmpty ? ExitCode.usage.rawValue : ExitCode.success.rawValue)
    }

    var positional: [String] = []
    var detail = PhotogrammetrySession.Request.Detail.medium
    var sensitivity = PhotogrammetrySession.Configuration.FeatureSensitivity.normal
    var ordering = PhotogrammetrySession.Configuration.SampleOrdering.unordered

    var index = 0
    while index < arguments.count {
        let argument = arguments[index]
        switch argument {
        case "--detail", "--sensitivity", "--ordering":
            guard index + 1 < arguments.count else {
                fail("option \(argument) needs a value", .usage)
            }
            let value = arguments[index + 1].lowercased()
            index += 2
            switch argument {
            case "--detail":
                guard let parsed = detailByName[value] else {
                    fail("unknown detail level: \(value)", .usage)
                }
                detail = parsed
            case "--sensitivity":
                guard let parsed = sensitivityByName[value] else {
                    fail("unknown sensitivity: \(value)", .usage)
                }
                sensitivity = parsed
            default:
                guard let parsed = orderingByName[value] else {
                    fail("unknown ordering: \(value)", .usage)
                }
                ordering = parsed
            }
        default:
            if argument.hasPrefix("-") {
                fail("unknown option: \(argument)", .usage)
            }
            positional.append(argument)
            index += 1
        }
    }

    guard positional.count == 2 else {
        fail("expected an input folder and an output path, got \(positional.count) arguments", .usage)
    }

    return Options(
        inputFolder: URL(fileURLWithPath: positional[0], isDirectory: true),
        output: URL(fileURLWithPath: positional[1]),
        detail: detail,
        sensitivity: sensitivity,
        ordering: ordering
    )
}

// MARK: - Filesystem preparation

/// Where the session writes, and where the user asked for the model.
///
/// `sessionURL` is always a `.usdz` path, because that is the only output
/// RealityKit accepts. `objURL` is non-nil only when the user asked for OBJ,
/// in which case it is filled in by a Model I/O conversion afterwards.
struct OutputPlan {
    var sessionURL: URL
    var objURL: URL?
}

/// Plans the output locations and creates the parent directory.
///
/// Assumes `output` names a FILE ending in `.usdz` or `.obj`; anything else
/// exits with the usage code. Only the parent directory is created. Creating
/// the output path itself as a directory makes RealityKit reject it with
/// invalidOutput, which is what a bare directory path does.
func planOutput(_ output: URL) throws -> OutputPlan {
    let suffix = output.pathExtension.lowercased()
    guard suffix == "usdz" || suffix == "obj" else {
        fail("output path must end in .usdz or .obj", .usage)
    }
    try FileManager.default.createDirectory(
        at: output.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    if suffix == "usdz" {
        return OutputPlan(sessionURL: output, objURL: nil)
    }
    let usdz = output.deletingPathExtension().appendingPathExtension("usdz")
    return OutputPlan(sessionURL: usdz, objURL: output)
}

/// Converts a reconstructed USDZ into an OBJ plus its MTL sidecar.
///
/// Assumes `usdz` exists and `obj`'s parent directory exists; Model I/O
/// reports a bare "could not save" error otherwise. Vertex units are carried
/// through unchanged, so the OBJ is still in meters.
func convertToOBJ(usdz: URL, obj: URL) {
    guard MDLAsset.canExportFileExtension("obj") else {
        fail("this system's Model I/O cannot write OBJ", .sessionFailure)
    }
    let asset = MDLAsset(url: usdz)
    guard asset.count > 0 else {
        fail("reconstructed USDZ holds no objects, so OBJ conversion was skipped", .sessionFailure)
    }
    do {
        try asset.export(to: obj)
    } catch {
        fail("OBJ conversion failed: \(error.localizedDescription)", .sessionFailure)
    }
    say("OBJ written to: \(obj.path)")
    sanitizeMaterialFile(besides: obj)
}

/// Rewrites the MTL sidecar next to `obj` using only standard OBJ material keys.
///
/// Assumes Model I/O has just written the pair. Model I/O emits physically
/// based keys (ao, subsurface, metallic, roughness, sheen and friends) and a
/// map_Kd that points inside the USDZ archive. Open3D reads OBJ through
/// ASSIMP, whose MTL parser aborts on those keys and then returns an EMPTY
/// mesh with only a warning -- the OBJ geometry itself is fine. Rewriting the
/// sidecar with Ka/Kd/Ks/d/illum keeps every reader happy. Material names are
/// preserved so the OBJ's usemtl lines still resolve. Texture maps are
/// dropped: they are unreachable inside the USDZ, and scan2cad measures
/// geometry, not color.
func sanitizeMaterialFile(besides obj: URL) {
    let mtl = obj.deletingPathExtension().appendingPathExtension("mtl")
    guard let original = try? String(contentsOf: mtl, encoding: .utf8) else {
        return
    }

    var names: [String] = []
    for line in original.split(separator: "\n") {
        let fields = line.split(separator: " ", omittingEmptySubsequences: true)
        if fields.count >= 2, fields[0] == "newmtl" {
            names.append(String(fields[1]))
        }
    }
    guard !names.isEmpty else {
        return
    }

    var rewritten = "# Rewritten by photogrammetry-cli for portable OBJ readers.\n"
    rewritten += "# Texture maps are dropped; geometry is unaffected.\n"
    for name in names {
        rewritten += "newmtl \(name)\n"
        rewritten += "Ka 0 0 0\n"
        rewritten += "Kd 0.18 0.18 0.18\n"
        rewritten += "Ks 0 0 0\n"
        rewritten += "d 1\n"
        rewritten += "illum 2\n"
    }

    do {
        try rewritten.write(to: mtl, atomically: true, encoding: .utf8)
        say("Material file simplified for portable readers: \(mtl.path)")
    } catch {
        say("Warning: could not simplify \(mtl.path); Open3D may read the OBJ as empty.")
    }
}

/// Counts the image files directly inside `folder`.
///
/// Assumes a flat capture folder. Used only for a pre-flight message; the
/// session does its own scan and may accept or reject files this misses.
func countImages(in folder: URL) -> Int {
    let extensions: Set<String> = ["heic", "heif", "jpg", "jpeg", "png", "tif", "tiff", "dng"]
    guard let names = try? FileManager.default.contentsOfDirectory(atPath: folder.path) else {
        return 0
    }
    return names.filter { extensions.contains(($0 as NSString).pathExtension.lowercased()) }.count
}

// MARK: - Run

/// Drives one PhotogrammetrySession to completion.
///
/// Assumes the caller has already validated the input folder and prepared the
/// output location. Returns normally only after `.processingComplete`; any
/// `.requestError` exits with the session failure code.
func run(_ options: Options) async {
    guard PhotogrammetrySession.isSupported else {
        fail(
            "PhotogrammetrySession is not supported on this Mac; Apple silicon with 4 GB or more of memory is required",
            .unsupportedHardware
        )
    }

    var isDirectory: ObjCBool = false
    let inputExists = FileManager.default.fileExists(
        atPath: options.inputFolder.path,
        isDirectory: &isDirectory
    )
    guard inputExists, isDirectory.boolValue else {
        fail("input folder does not exist or is not a folder: \(options.inputFolder.path)", .usage)
    }

    let plan: OutputPlan
    do {
        plan = try planOutput(options.output)
    } catch {
        fail("cannot prepare output path: \(error.localizedDescription)", .sessionFailure)
    }
    let outputURL = plan.sessionURL

    let imageCount = countImages(in: options.inputFolder)
    say("Input folder: \(options.inputFolder.path)")
    say("Images found: \(imageCount)")
    say("Output: \(outputURL.path)")
    if let objURL = plan.objURL {
        say("OBJ will be converted to: \(objURL.path)")
    }
    say("Maximum input images supported: \(PhotogrammetrySession.limits.maximumNumberOfInputImages)")

    var configuration = PhotogrammetrySession.Configuration()
    configuration.featureSensitivity = options.sensitivity
    configuration.sampleOrdering = options.ordering

    let session: PhotogrammetrySession
    do {
        session = try PhotogrammetrySession(input: options.inputFolder, configuration: configuration)
    } catch {
        fail("cannot create session: \(error.localizedDescription)", .sessionFailure)
    }

    let request = PhotogrammetrySession.Request.modelFile(url: outputURL, detail: options.detail)

    // Start reading outputs before submitting, so no early output is lost.
    let reader = Task {
        var lastReportedPercent = -1
        do {
            for try await output in session.outputs {
                switch output {
                case .inputComplete:
                    say("All input images read.")
                case .requestProgress(_, let fractionComplete):
                    // Report every 10 percent only. A per-sample progress bar
                    // is noise for a screen reader.
                    let percent = Int(fractionComplete * 10) * 10
                    if percent > lastReportedPercent {
                        lastReportedPercent = percent
                        say("Progress: \(percent) percent.")
                    }
                case .requestComplete(_, let result):
                    if case .modelFile(let url) = result {
                        say("Model written to: \(url.path)")
                    }
                case .requestError(_, let error):
                    fail("request failed: \(error.localizedDescription)", .sessionFailure)
                case .processingComplete:
                    say("Processing complete.")
                    return
                case .processingCancelled:
                    fail("processing was cancelled", .sessionFailure)
                case .invalidSample(let id, let reason):
                    say("Skipped image \(id): \(reason)")
                case .skippedSample(let id):
                    say("Skipped image \(id).")
                case .automaticDownsampling:
                    say("Note: images were downsampled automatically.")
                case .stitchingIncomplete:
                    say("Warning: stitching incomplete. Some views did not join; expect holes.")
                default:
                    break
                }
            }
        } catch {
            fail("session stream failed: \(error.localizedDescription)", .sessionFailure)
        }
    }

    do {
        try session.process(requests: [request])
    } catch {
        fail("cannot start processing: \(error.localizedDescription)", .sessionFailure)
    }

    await reader.value

    if let objURL = plan.objURL {
        say("Converting to OBJ.")
        convertToOBJ(usdz: outputURL, obj: objURL)
    }
    say("Units are meters. Pass --units m to scan2cad.")
}

// MARK: - Entry point

let options = parseOptions(Array(CommandLine.arguments.dropFirst()))

// Top-level await is not available in a synchronous main, so the async work
// runs on a detached task and the main thread blocks on a semaphore.
let done = DispatchSemaphore(value: 0)
Task {
    await run(options)
    done.signal()
}
done.wait()
exit(ExitCode.success.rawValue)
