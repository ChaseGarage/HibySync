import QtQuick
import ".."

Type {
    id: link
    signal clicked()
    readonly property bool hovered: mouse.containsMouse
    color: Theme.muted
    activeFocusOnTab: enabled
    font.underline: enabled && (hovered || activeFocus)
    Accessible.role: Accessible.Link
    Accessible.name: text
    Accessible.onPressAction: if (enabled) clicked()
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onEnterPressed: if (enabled) clicked()
    MouseArea {
        id: mouse
        width: Math.min(parent.width, parent.paintedWidth)
        height: parent.height
        hoverEnabled: true
        enabled: link.enabled
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton
        onClicked: link.clicked()
    }
}
