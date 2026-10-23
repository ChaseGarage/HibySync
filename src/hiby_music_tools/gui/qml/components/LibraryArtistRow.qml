import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

AbstractButton {
    id: row
    required property var record
    objectName: "libraryArtist_" + record.id
    implicitHeight: 80
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: record.name
    background: Rectangle { color: row.hovered || row.activeFocus ? Theme.hover : "transparent"; radius: Theme.radius }
    contentItem: RowLayout {
        spacing: 16
        LibraryCover { Layout.leftMargin: 12; Layout.preferredWidth: 48; Layout.preferredHeight: 48; source: row.record.image }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 6
            TextLink { objectName: "artistName_" + row.record.id; text: row.record.name; color: Theme.text; Layout.fillWidth: true; font.weight: Font.DemiBold; onClicked: libraryBrowser.visitArtist(row.record.id, row.record.name) }
            Type { text: Theme.countLabel(row.record.album_count, "album"); color: Theme.muted; font.pixelSize: Theme.small }
        }
        Icon { name: "chevron"; Layout.rightMargin: 12; width: 16; height: 16 }
    }
    Divider { width: parent.width - 24; x: 12; anchors.bottom: parent.bottom }
}
