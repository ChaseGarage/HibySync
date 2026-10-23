import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

AbstractButton {
    id: row
    required property var record
    objectName: "albumRow" + record.albumIndex
    implicitHeight: 88
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: record.artist + ", " + record.title + ", " + record.status
    background: Rectangle { color: row.hovered || row.activeFocus ? Theme.hover : "transparent"; radius: Theme.radius }
    contentItem: RowLayout {
        spacing: 16
        Artwork { Layout.leftMargin: 12; Layout.preferredWidth: 48; Layout.preferredHeight: 48; source: row.record.image }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Type { Layout.fillWidth: true; text: row.record.artist; font.weight: Font.DemiBold }
            Type {
                Layout.fillWidth: true
                text: row.record.title + "  ·  " + Theme.countLabel(row.record.count, "track") + (row.record.skipped ? "  ·  Skipped" : "")
                font.pixelSize: Theme.small; color: Theme.muted
            }
        }
        Type { text: row.record.year; color: Theme.muted; font.pixelSize: Theme.small; visible: row.width > 700; Layout.rightMargin: 28 }
        Status { status: row.record.status; compact: row.width < 600; Layout.preferredWidth: row.width < 600 ? 12 : 110 }
        Icon { name: "chevron"; width: 16; height: 16; Layout.rightMargin: 12; Layout.leftMargin: 12 }
    }
    Divider { anchors.bottom: parent.bottom; width: parent.width - 24; x: 12 }
}
