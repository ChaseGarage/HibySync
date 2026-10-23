import QtQuick
import ".."

Item {
    id: indicator
    property bool playing: false
    property bool paused: false
    implicitWidth: 20; implicitHeight: 20
    // Static bars communicate activity without one continuous animation per row.
    Row {
        anchors.centerIn: parent; spacing: 3; height: 16
        visible: indicator.playing
        Repeater {
            model: [7, 15, 10]
            Rectangle { required property int modelData; width: 2; height: modelData; radius: 1; color: Theme.success; anchors.bottom: parent.bottom }
        }
    }
    Icon { anchors.centerIn: parent; name: indicator.paused ? "pause" : "music"; ink: Theme.success; visible: !indicator.playing }
}
