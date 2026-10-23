import QtQuick

QtObject {
    property real availableWidth: 700
    property bool albumMode: false
    readonly property bool showAlbum: !albumMode && availableWidth >= 880
    readonly property bool showYear: !albumMode && availableWidth >= 1100
    readonly property real padding: availableWidth < 800 ? 8 : 12
    readonly property real gap: availableWidth < 880 ? 12 : 16
    readonly property real leading: 36
    readonly property real actions: 36
    readonly property real duration: availableWidth < 880 ? 56 : 64
    readonly property real artist: Math.min(260, Math.max(128, availableWidth * (albumMode ? 0.24 : 0.21)))
    readonly property real album: Math.min(300, availableWidth * 0.24)
    readonly property real year: 56
}
