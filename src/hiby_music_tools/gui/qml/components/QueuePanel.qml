import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: panel
    required property var player
    signal closeRequested()
    spacing: 20
    RowLayout {
        Layout.fillWidth: true
        Type { text: "Queue"; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true }
        FlatButton { text: "Clear"; quiet: true; enabled: panel.player.count > 0; onClicked: panel.player.clear() }
        IconButton { glyph: "close"; text: "Close queue"; onClicked: panel.closeRequested() }
    }
    Type { text: Theme.countLabel(panel.player.count, "track"); color: Theme.muted; font.pixelSize: Theme.small }
    ListView {
        id: list
        objectName: "playbackQueueList"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; model: panel.player.model
        ScrollBar.vertical: ThinScrollBar {}
        delegate: Item {
            id: row
            required property var record
            required property int index
            objectName: "queueEntry_" + record.qid
            width: list.width; height: 90
            Rectangle { anchors.fill: parent; color: row.record.current ? Theme.surface : mouse.containsMouse ? Theme.hover : "transparent"; radius: Theme.radius }
            MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; onDoubleClicked: panel.player.playEntry(row.record.qid) }
            RowLayout {
                anchors.fill: parent; anchors.margins: 8; spacing: 12
                LibraryCover { Layout.preferredWidth: 44; Layout.preferredHeight: 44; source: row.record.image || "" }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 5
                    TextLink { objectName: "queueAlbum_" + row.record.qid; text: (row.record.current ? "•  " : "") + row.record.title; color: row.record.current ? Theme.success : Theme.text; Layout.fillWidth: true; onClicked: { libraryBrowser.visitTrack(row.record.id, "album"); panel.closeRequested() } }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        TextLink { objectName: "queueArtist_" + row.record.qid; text: row.record.artist; font.pixelSize: 12; Layout.fillWidth: true; onClicked: { libraryBrowser.visitTrack(row.record.id, "artist"); panel.closeRequested() } }
                        Type { text: row.record.durationText || "—"; color: Theme.muted; font.pixelSize: 12 }
                    }
                    RowLayout {
                        spacing: 2
                        IconButton { implicitHeight: 24; implicitWidth: 28; glyph: "play"; text: "Play this track"; onClicked: panel.player.playEntry(row.record.qid) }
                        IconButton { implicitHeight: 24; implicitWidth: 28; glyph: "up"; text: "Move earlier"; enabled: row.index > 0; onClicked: panel.player.move(row.record.qid, row.index - 1) }
                        IconButton { implicitHeight: 24; implicitWidth: 28; glyph: "down"; text: "Move later"; enabled: row.index < panel.player.count - 1; onClicked: panel.player.move(row.record.qid, row.index + 1) }
                    }
                }
                IconButton { glyph: "close"; text: "Remove from queue"; onClicked: panel.player.remove(row.record.qid) }
            }
            Divider { anchors.bottom: parent.bottom; width: parent.width }
        }
        Type { anchors.centerIn: parent; visible: panel.player.count === 0; text: "Your queue is empty"; color: Theme.muted }
    }
}
