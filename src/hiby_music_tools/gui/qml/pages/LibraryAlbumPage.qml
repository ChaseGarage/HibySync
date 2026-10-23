import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ListView {
    id: tracks
    required property var browser
    objectName: "libraryAlbumTracks"
    clip: true
    model: browser.model
    activeFocusOnTab: true
    currentIndex: -1
    keyNavigationEnabled: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ThinScrollBar {}
    onContentYChanged: if (contentY + height > contentHeight - 300) browser.loadMore()
    header: Column {
        width: tracks.width
        spacing: tracks.width < 800 ? 20 : 24
        FlatButton { objectName: "libraryBackButton"; text: "←  Back to library"; quiet: true; onClicked: tracks.browser.back() }
        AlbumHeader { width: parent.width; height: implicitHeight; browser: tracks.browser }
        Divider { width: parent.width }
        Item {
            width: parent.width; height: 28
            SongColumns { id: columns; availableWidth: tracks.width; albumMode: true }
            RowLayout {
                x: columns.padding; width: parent.width - columns.padding * 2; height: parent.height; spacing: columns.gap
                Type { text: "#"; color: Theme.muted; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; Layout.preferredWidth: columns.leading }
                Type { text: "Tracks"; font.pixelSize: Theme.small; Layout.fillWidth: true }
                Type { text: "Artist"; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: columns.artist }
                Type { text: "Time"; color: Theme.muted; font.pixelSize: 12; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: columns.duration }
                Item { Layout.preferredWidth: columns.actions }
            }
        }
    }
    delegate: LibrarySongRow { width: tracks.width; height: implicitHeight; albumMode: true; onActivated: playback.toggleTrack(record.id) }
}
