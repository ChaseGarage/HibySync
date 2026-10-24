import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

AbstractButton {
    id: control
    property bool selected: false
    implicitHeight: 36
    implicitWidth: contentItem.implicitWidth
    hoverEnabled: true; activeFocusOnTab: true
    Accessible.name: text
    contentItem: RowLayout {
        spacing: 10
        Rectangle {
            Layout.preferredWidth: 16; Layout.preferredHeight: 16
            radius: 3; color: control.selected ? Theme.text : Theme.surface
            border.width: 1; border.color: control.activeFocus || control.hovered ? Theme.text : Theme.muted
            Type { anchors.centerIn: parent; text: control.selected ? "✓" : ""; color: Theme.background; font.pixelSize: 12 }
        }
        Type { text: control.text; Layout.fillWidth: true; font.pixelSize: Theme.small; color: Theme.muted }
    }
    background: Item {}
}
