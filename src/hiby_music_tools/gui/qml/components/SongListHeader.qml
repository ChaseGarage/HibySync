import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Item {
    id: header
    required property var browser
    implicitHeight: 36
    SongColumns { id: columns; availableWidth: header.width }
    RowLayout {
        x: columns.padding; width: parent.width - columns.padding * 2; height: parent.height
        spacing: columns.gap
        Type { text: "#"; color: Theme.muted; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12; Layout.preferredWidth: columns.leading }
        LibrarySortHeader { objectName: "sortLibraryTitle"; text: "Title"; selected: header.browser.sort === "title"; descending: header.browser.descending; Layout.fillWidth: true; Layout.minimumWidth: 0; onClicked: header.browser.sortBy("title") }
        LibrarySortHeader { objectName: "sortLibraryArtist"; text: "Artist"; selected: header.browser.sort === "artist"; descending: header.browser.descending; Layout.preferredWidth: columns.artist; onClicked: header.browser.sortBy("artist") }
        LibrarySortHeader { objectName: "sortLibraryAlbum"; visible: columns.showAlbum; text: "Album"; selected: header.browser.sort === "album"; descending: header.browser.descending; Layout.preferredWidth: columns.album; onClicked: header.browser.sortBy("album") }
        LibrarySortHeader { objectName: "sortLibraryYear"; visible: columns.showYear; text: "Year"; selected: header.browser.sort === "year"; descending: header.browser.descending; Layout.preferredWidth: columns.year; onClicked: header.browser.sortBy("year") }
        LibrarySortHeader { objectName: "sortLibraryDuration"; text: "Time"; selected: header.browser.sort === "duration"; descending: header.browser.descending; alignRight: true; Layout.preferredWidth: columns.duration; onClicked: header.browser.sortBy("duration") }
        IconButton { glyph: "more"; text: "Sort songs"; Layout.preferredWidth: columns.actions; onClicked: sortMenu.open() }
    }
    Popup {
        id: sortMenu
        x: parent.width - width; y: header.height
        width: 180; padding: 8; focus: true
        background: Rectangle { color: Theme.surface; radius: Theme.radius; border.width: 1; border.color: Theme.divider }
        contentItem: Column {
            Repeater {
                model: ["title", "artist", "album", "year", "duration"]
                FlatButton { required property string modelData; width: parent.width; quiet: true; text: "Sort by " + modelData; onClicked: { header.browser.sortBy(modelData); sortMenu.close() } }
            }
        }
    }
}
