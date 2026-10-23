import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

AbstractButton {
    id: tile
    required property var record
    objectName: "libraryAlbum_" + record.id
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: record.title + ", " + record.artist
    background: Item {}
    contentItem: ColumnLayout {
        spacing: 8
        LibraryCover {
            Layout.fillWidth: true
            Layout.preferredHeight: width
            source: tile.record.image
            Rectangle { anchors.fill: parent; color: tile.hovered || tile.activeFocus ? "#10FFFFFF" : "transparent"; radius: Theme.radius }
        }
        TextLink { objectName: "albumTitle_" + tile.record.id; text: tile.record.title; color: Theme.text; Layout.fillWidth: true; font.weight: Font.DemiBold; Layout.topMargin: 4; onClicked: libraryBrowser.visitAlbum(tile.record.id) }
        TextLink { objectName: "albumArtist_" + tile.record.id; text: tile.record.artist; Layout.fillWidth: true; font.pixelSize: Theme.small; onClicked: libraryBrowser.visitArtist(tile.record.artist_id, tile.record.artist) }
        Type { text: tile.record.year || "Year unknown"; Layout.fillWidth: true; color: Theme.muted; font.pixelSize: 12 }
    }
}
