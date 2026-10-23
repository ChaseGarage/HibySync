import QtQuick
import QtQuick.Controls.Basic
import ".."

AbstractButton {
    id: control
    property string number: ""
    property string trackTitle: ""
    property bool rowHovered: false
    property bool rowSelected: false
    property bool loaded: false
    property bool playing: false
    property bool paused: false
    readonly property bool showAction: hovered || rowHovered || activeFocus || (!loaded && rowSelected) || paused
    implicitWidth: Theme.hitTarget; implicitHeight: Theme.hitTarget
    hoverEnabled: true; activeFocusOnTab: true
    text: (playing ? "Pause " : "Play ") + trackTitle
    Accessible.name: text
    Accessible.role: Accessible.Button
    Keys.onReturnPressed: clicked()
    Keys.onEnterPressed: clicked()
    background: Rectangle { radius: Theme.radius; color: control.hovered || control.activeFocus ? Theme.hover : "transparent"; border.width: control.activeFocus ? 1 : 0; border.color: Theme.muted }
    contentItem: Item {
        Icon { anchors.centerIn: parent; name: control.playing ? "pause" : "play"; ink: control.loaded ? Theme.success : Theme.text; visible: control.showAction }
        PlaybackIndicator { anchors.centerIn: parent; playing: control.playing; paused: control.paused; visible: control.loaded && !control.showAction }
        Type { anchors.fill: parent; horizontalAlignment: Text.AlignHCenter; text: control.number; color: Theme.muted; font.pixelSize: Theme.small; visible: !control.loaded && !control.showAction }
    }
}
