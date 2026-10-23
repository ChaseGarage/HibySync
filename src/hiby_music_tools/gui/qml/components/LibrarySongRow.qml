import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

FocusScope {
    id: row
    required property var record
    required property int index
    objectName: "librarySong_" + record.id
    property bool albumMode: false
    readonly property var view: ListView.view
    readonly property bool selected: view !== null && view.currentIndex === index
    readonly property bool currentTrack: record.id === playback.currentTrackId
    readonly property bool loaded: currentTrack && playback.state !== "stopped" && playback.state !== "error"
    readonly property bool playing: loaded && (playback.state === "playing" || playback.state === "buffering")
    readonly property bool paused: loaded && playback.state === "paused"
    readonly property bool discHeader: albumMode && Boolean(record.discHeader)
    readonly property bool menuOpen: actions.opened
    readonly property real bodyY: discHeader ? 34 : 0
    signal activated()
    implicitHeight: (record.error ? 68 : Theme.rowHeight) + bodyY
    SongColumns { id: columns; availableWidth: row.width; albumMode: row.albumMode }

    function selectRow(takeFocus) {
        if (view) view.currentIndex = index
        if (takeFocus) forceActiveFocus(Qt.MouseFocusReason)
    }
    function step(direction) {
        if (!view) return
        view.currentIndex = Math.max(0, Math.min(view.count - 1, index + direction))
        view.positionViewAtIndex(view.currentIndex, ListView.Contain)
        if (view.currentItem) view.currentItem.forceActiveFocus(Qt.TabFocusReason)
    }
    Keys.onUpPressed: step(-1)
    Keys.onDownPressed: step(1)
    Keys.onReturnPressed: { selectRow(false); playback.toggleTrack(record.id) }
    Keys.onEnterPressed: { selectRow(false); playback.toggleTrack(record.id) }

    Type { x: columns.padding + columns.leading + columns.gap; y: 8; visible: row.discHeader; text: "Disc " + row.record.disc_sort; color: Theme.muted; font.pixelSize: 12 }
    Rectangle {
        y: row.bodyY; width: row.width; height: row.height - y
        radius: Theme.radius
        color: row.selected ? Theme.surface : rowMouse.containsMouse ? Theme.hover : row.loaded ? Theme.playingSurface : "transparent"
    }
    MouseArea {
        id: rowMouse
        x: 0; y: row.bodyY; width: parent.width; height: parent.height - y
        hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
        onDoubleClicked: function(mouse) { if (mouse.button === Qt.LeftButton) row.activated() }
        onClicked: function(mouse) {
            row.selectRow(mouse.button === Qt.LeftButton)
            if (mouse.button === Qt.RightButton) actions.open()
        }
    }
    RowLayout {
        x: columns.padding; y: row.bodyY; width: parent.width - columns.padding * 2
        height: parent.height - y; spacing: columns.gap
        HoverPlayButton {
            objectName: "playSong_" + row.record.id
            Layout.preferredWidth: columns.leading
            number: row.albumMode ? row.record.number : String(row.index + 1)
            trackTitle: row.record.title
            rowHovered: rowMouse.containsMouse
            rowSelected: row.selected || row.activeFocus
            loaded: row.loaded; playing: row.playing; paused: row.paused
            onClicked: { row.selectRow(false); playback.toggleTrack(row.record.id) }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 4
            Type { text: row.record.title; Layout.fillWidth: true; color: row.loaded ? Theme.success : Theme.text; font.weight: row.loaded ? Font.DemiBold : Font.Normal }
            Type { text: row.record.error || ""; visible: text.length > 0; color: Theme.error; font.pixelSize: 12; Layout.fillWidth: true }
        }
        TextLink { objectName: "songArtist_" + row.record.id; text: row.record.artist; Layout.preferredWidth: columns.artist; Layout.minimumWidth: 0; onClicked: libraryBrowser.visitTrack(row.record.id, "artist") }
        TextLink { objectName: "songAlbum_" + row.record.id; text: row.record.album_title || ""; visible: columns.showAlbum; Layout.preferredWidth: columns.album; Layout.minimumWidth: 0; onClicked: libraryBrowser.visitAlbum(row.record.album_id) }
        Type { objectName: "songYear_" + row.record.id; text: row.record.year || "—"; visible: columns.showYear; color: Theme.muted; Layout.preferredWidth: columns.year }
        Type { text: row.record.durationText; color: Theme.muted; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: columns.duration }
        IconButton { objectName: "songMenu_" + row.record.id; Layout.preferredWidth: columns.actions; glyph: "more"; text: "Actions for " + row.record.title; onClicked: { row.selectRow(false); actions.open() } }
    }
    Popup {
        id: actions
        objectName: "songActions_" + row.record.id
        x: row.width - width - columns.padding; y: row.height - 4
        padding: 8; width: 190; focus: true
        background: Rectangle { color: Theme.surface; radius: Theme.radius; border.width: 1; border.color: Theme.divider }
        contentItem: Column {
            FlatButton { width: parent.width; text: row.playing ? "Pause" : "Play"; quiet: true; onClicked: { playback.toggleTrack(row.record.id); actions.close() } }
            FlatButton { width: parent.width; text: "Play next"; quiet: true; onClicked: { playback.trackAction(row.record.id, "next"); actions.close() } }
            FlatButton { width: parent.width; text: "Add to queue"; quiet: true; onClicked: { playback.trackAction(row.record.id, "append"); actions.close() } }
        }
    }
    Divider { width: parent.width - columns.padding * 2; x: columns.padding; anchors.bottom: parent.bottom; opacity: 0.55 }
}
