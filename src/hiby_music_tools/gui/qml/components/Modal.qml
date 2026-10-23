import QtQuick
import QtQuick.Controls.Basic
import ".."

Popup {
    parent: Overlay.overlay
    anchors.centerIn: parent
    padding: 24
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    enter: null
    exit: null
    background: Rectangle { color: Theme.surface; radius: 8; border.color: Theme.divider; border.width: 1 }
    Overlay.modal: Rectangle { color: "#AA000000" }
}
