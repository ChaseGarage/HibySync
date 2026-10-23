import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Item {
    id: header
    required property var browser
    readonly property real artworkSize: width < 760 ? 128 : width < 1000 ? 160 : 192
    implicitHeight: Math.max(artworkSize, metadata.implicitHeight)
    RowLayout {
        anchors.fill: parent; spacing: header.width < 760 ? 20 : 28
        LibraryCover { Layout.preferredWidth: header.artworkSize; Layout.preferredHeight: header.artworkSize; Layout.alignment: Qt.AlignTop; source: header.browser.album.image || "" }
        ColumnLayout {
            id: metadata
            Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter; spacing: 12
            TextLink { objectName: "albumHeaderArtist"; text: header.browser.album.artist || ""; font.pixelSize: 15; Layout.fillWidth: true; enabled: Boolean(header.browser.album.artist_id); onClicked: libraryBrowser.visitArtist(header.browser.album.artist_id, header.browser.album.artist) }
            TextLink {
                objectName: "albumHeaderTitle"
                text: header.browser.album.title || (header.browser.queryBusy ? "Loading album…" : "Album no longer indexed")
                color: Theme.text
                enabled: Boolean(header.browser.album.id)
                onClicked: libraryBrowser.visitAlbum(header.browser.album.id)
                font.pixelSize: header.width < 760 ? 26 : 30; font.weight: Font.DemiBold
                Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2
            }
            Type {
                text: (header.browser.album.year || "Year unknown") + "  ·  " + Theme.countLabel(header.browser.album.track_count || 0, "track") + "  ·  " + (header.browser.album.durationText || "—")
                color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true
            }
            RowLayout {
                spacing: 8; Layout.topMargin: 4
                enabled: Boolean(header.browser.album.id) && !playback.busy
                FlatButton { objectName: "playLibraryAlbum"; text: "Play"; onClicked: playback.albumAction(header.browser.album.id, "play") }
                FlatButton { objectName: "shuffleLibraryAlbum"; text: "Shuffle"; quiet: true; onClicked: playback.albumAction(header.browser.album.id, "shuffle") }
                FlatButton { visible: metadata.width >= 570; text: "Add to queue"; quiet: true; onClicked: playback.albumAction(header.browser.album.id, "append") }
                IconButton { objectName: "albumActionsButton"; glyph: "more"; text: "Album queue actions"; onClicked: actions.open() }
            }
        }
    }
    Popup {
        id: actions
        x: header.artworkSize + 24; y: header.height
        width: 180; padding: 8; focus: true
        background: Rectangle { color: Theme.surface; radius: Theme.radius; border.width: 1; border.color: Theme.divider }
        contentItem: Column {
            FlatButton { width: parent.width; text: "Add to queue"; quiet: true; onClicked: { playback.albumAction(header.browser.album.id, "append"); actions.close() } }
            FlatButton { width: parent.width; text: "Play next"; quiet: true; onClicked: { playback.albumAction(header.browser.album.id, "next"); actions.close() } }
        }
    }
}
