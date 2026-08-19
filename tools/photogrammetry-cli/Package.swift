// swift-tools-version:5.9
//
// Standalone Swift package for the scan2cad photogrammetry front end.
//
// Assumes: Xcode command line tools with a macOS 14+ SDK, Apple silicon.
// No external package dependencies, so `swift build` works with no network.

import PackageDescription

let package = Package(
    name: "photogrammetry-cli",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "photogrammetry-cli", targets: ["PhotogrammetryCLI"])
    ],
    targets: [
        .executableTarget(
            name: "PhotogrammetryCLI",
            path: "Sources/PhotogrammetryCLI"
        )
    ]
)
