import QtQuick
import QtQuick.Layouts
import ".."

RowLayout {
    id: controls
    required property var player
    property bool compact: false
    spacing: compact ? 4 : 8
    IconButton { objectName: "playerShuffle"; visible: !controls.compact; glyph: "shuffle"; text: controls.player.shuffle ? "Turn shuffle off" : "Shuffle"; active: controls.player.shuffle; onClicked: controls.player.toggleShuffle() }
    IconButton { objectName: "playerPrevious"; glyph: "previous"; text: "Previous"; enabled: controls.player.count > 0; onClicked: controls.player.previous() }
    IconButton {
        objectName: "playerPlayPause"
        implicitWidth: 42; implicitHeight: 42; prominent: true
        glyph: controls.player.state === "playing" || controls.player.state === "buffering" ? "pause" : "play"
        text: glyph === "pause" ? "Pause" : "Play"; enabled: controls.player.count > 0 && controls.player.state !== "loading"
        onClicked: controls.player.togglePause()
    }
    IconButton { objectName: "playerNext"; glyph: "next"; text: "Next"; enabled: controls.player.count > 0; onClicked: controls.player.next() }
    IconButton { objectName: "playerRepeat"; visible: !controls.compact; glyph: controls.player.repeat === "one" ? "repeatOne" : "repeat"; text: "Repeat: " + controls.player.repeat; active: controls.player.repeat !== "off"; onClicked: controls.player.cycleRepeat() }
}
