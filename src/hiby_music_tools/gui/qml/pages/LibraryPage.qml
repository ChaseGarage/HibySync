import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    implicitWidth: 800
    implicitHeight: 600
    required property var browser
    required property var sourceController
    readonly property bool active: sourceController.page === "library"
    onActiveChanged: if (active) browser.activate()
    spacing: 20
    RowLayout {
        visible: page.browser.mode !== "album"
        Layout.fillWidth: true
        ColumnLayout {
            spacing: 8
            Type { text: page.browser.artistName || "Library"; font.pixelSize: Theme.title; font.weight: Font.DemiBold }
            Type {
                text: page.browser.artistName ? Theme.countLabel(page.browser.model.total, "album") : Theme.countLabel(page.browser.summary.albums, "album") + "  ·  " + Theme.countLabel(page.browser.summary.tracks, "track")
                color: Theme.muted; font.pixelSize: Theme.small
            }
        }
        Item { Layout.fillWidth: true }
        FlatButton { objectName: "libraryRebuildButton"; text: "Rebuild index"; quiet: true; enabled: !page.browser.indexing; onClicked: page.browser.refresh(true) }
        FlatButton { objectName: "libraryRefreshButton"; text: page.browser.indexing ? "Cancel" : "Refresh"; onClicked: page.browser.indexing ? page.browser.cancel() : page.browser.refresh(false) }
    }
    RowLayout {
        visible: page.browser.mode !== "album"
        Layout.fillWidth: true; spacing: 8
        FlatButton { objectName: "libraryAlbumsMode"; text: "Albums"; quiet: page.browser.mode !== "albums"; onClicked: page.browser.setMode("albums") }
        FlatButton { objectName: "libraryArtistsMode"; text: "Artists"; quiet: page.browser.mode !== "artists"; onClicked: page.browser.setMode("artists") }
        FlatButton { objectName: "librarySongsMode"; text: "Songs"; quiet: page.browser.mode !== "songs"; onClicked: page.browser.setMode("songs") }
        Item { Layout.fillWidth: true }
        Field {
            editorName: "librarySearchInput"
            Layout.fillWidth: true
            Layout.preferredWidth: 340
            Layout.minimumWidth: 180
            Layout.maximumWidth: 380
            placeholderText: "Search songs, artists, albums"
            text: page.browser.search
            onTextChanged: page.browser.setSearch(text)
        }
    }
    RowLayout {
        visible: page.browser.artistName.length > 0 && page.browser.mode === "albums"
        Layout.fillWidth: true
        FlatButton { text: "←  All artists"; quiet: true; onClicked: page.browser.back() }
        Item { Layout.fillWidth: true }
        FlatButton { text: "Play artist"; onClicked: playback.artistAction(page.browser.artistId, "play") }
        FlatButton { text: "Add to queue"; quiet: true; onClicked: playback.artistAction(page.browser.artistId, "append") }
    }
    ColumnLayout {
        visible: page.browser.indexing
        Layout.fillWidth: true; spacing: 10
        RowLayout {
            Type { text: page.browser.phase; color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
            FlatButton { text: "Cancel refresh"; quiet: true; visible: page.browser.mode === "album"; onClicked: page.browser.cancel() }
        }
        Rectangle {
            Layout.fillWidth: true; height: 2; color: Theme.divider
            Rectangle { width: parent.width * (page.browser.progress < 0 ? 0.2 : page.browser.progress); height: 2; color: Theme.muted }
        }
    }
    Type { text: page.browser.message; visible: text.length > 0; color: page.browser.error ? Theme.error : page.browser.summary.errors > 0 ? Theme.warning : Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 2 }
    Item {
        Layout.fillWidth: true; Layout.fillHeight: true
        Loader {
            anchors.fill: parent
            active: page.active
            sourceComponent: page.browser.mode === "album" ? albumDetail : page.browser.mode === "albums" ? albumsView : page.browser.mode === "artists" ? artistsView : songsView
        }
        EmptyState {
            anchors.fill: parent
            visible: page.browser.mode !== "album" && page.browser.model.total === 0 && !page.browser.queryBusy
            title: page.browser.indexing ? "Indexing your music" : !page.browser.summary.scanned ? "Your music, ready to explore" : page.browser.search.length > 0 ? "No matching music" : "No music indexed here"
            subtitle: page.browser.indexing ? "You can keep browsing while the index refreshes." : !page.browser.summary.scanned ? "Index your configured music library to begin." : "Try another search or refresh your library."
            actionText: !page.browser.indexing && !page.browser.summary.scanned ? "Index library" : ""
            onAction: page.browser.refresh(false)
        }
        Type { anchors.centerIn: parent; visible: page.browser.queryBusy && page.browser.model.total === 0; text: "Loading library…"; color: Theme.muted }
    }
    RowLayout {
        visible: page.browser.mode !== "album"
        Layout.fillWidth: true
        Type { text: page.sourceController.displayPath(page.browser.root); color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
        Type { text: Theme.countLabel(page.browser.model.total, page.browser.mode === "albums" ? "album" : page.browser.mode === "artists" ? "artist" : "track"); color: Theme.muted; font.pixelSize: Theme.small }
    }

    Component {
        id: albumsView
        GridView {
            id: grid
            objectName: "libraryAlbumGrid"
            clip: true
            model: page.browser.model
            property int columns: Math.max(2, Math.floor(width / 200))
            cellWidth: width / columns
            cellHeight: cellWidth + 88
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ThinScrollBar {}
            onContentYChanged: if (contentY + height > contentHeight - 400) page.browser.loadMore()
            delegate: LibraryAlbumTile {
                width: grid.cellWidth - 24
                height: grid.cellHeight - 24
                onClicked: page.browser.openAlbum(record.id)
            }
        }
    }
    Component {
        id: artistsView
        ListView {
            id: artists
            objectName: "libraryArtistList"
            clip: true
            model: page.browser.model
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ThinScrollBar {}
            onContentYChanged: if (contentY + height > contentHeight - 300) page.browser.loadMore()
            delegate: LibraryArtistRow { width: artists.width; onClicked: page.browser.openArtist(record.id, record.name) }
        }
    }
    Component {
        id: songsView
        ColumnLayout {
            spacing: 8
            SongListHeader { Layout.fillWidth: true; browser: page.browser }
            Divider { Layout.fillWidth: true }
            ListView {
                id: songs
                objectName: "librarySongList"
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                model: page.browser.model
                activeFocusOnTab: true
                currentIndex: -1
                keyNavigationEnabled: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ThinScrollBar {}
                onContentYChanged: if (contentY + height > contentHeight - 300) page.browser.loadMore()
                delegate: LibrarySongRow { width: songs.width; height: implicitHeight; onActivated: playback.toggleTrack(record.id) }
            }
        }
    }
    Component { id: albumDetail; LibraryAlbumPage { browser: page.browser } }
}
