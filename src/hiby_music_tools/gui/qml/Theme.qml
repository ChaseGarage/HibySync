pragma Singleton
import QtQuick

QtObject {
    readonly property color background: "#101113"
    readonly property color surface: "#1B1D20"
    readonly property color hover: "#25282B"
    readonly property color divider: "#2C2F33"
    readonly property color text: "#F5F5F5"
    readonly property color muted: "#96999D"
    readonly property color success: "#86CA96"
    readonly property color warning: "#E8BA63"
    readonly property color error: "#E57E7E"
    // Pin the selected proportional family: platform theme plugins can reset
    // the global application font after startup (including to a monospace font).
    readonly property string family: interfaceFontFamily
    readonly property int body: 14
    readonly property int small: 13
    readonly property int title: 24
    readonly property int space: 8
    readonly property int section: 24
    readonly property int margin: 32
    readonly property int radius: 5
    readonly property int maxWidth: 1080
    readonly property int libraryMaxWidth: 1400
    readonly property int rowHeight: 52
    readonly property int hitTarget: 36
    readonly property color playingSurface: "#121A16"
    function outerMargin(width) { return width < 850 ? 20 : width < 1200 ? 24 : 32 }
    function countLabel(count, noun) { return count + " " + noun + (count === 1 ? "" : "s") }
}
