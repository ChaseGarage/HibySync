import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Rectangle {
    id: bar
    required property var player
    signal queueRequested()
    readonly property bool compact: body.width < 1000
    readonly property real errorHeight: player.error.length ? 28 : 0
    height: (compact ? 108 : 88) + errorHeight
    color: Theme.background
    function time(value) {
        const s = Math.max(0, Math.floor(value))
        const m = Math.floor(s / 60)
        const h = Math.floor(m / 60)
        return (h ? h + ":" + (m % 60 < 10 ? "0" : "") + m % 60 : m) + ":" + (s % 60 < 10 ? "0" : "") + s % 60
    }
    Divider { width: parent.width }
    RowLayout {
        visible: bar.errorHeight > 0
        x: Theme.outerMargin(bar.width); y: 1
        width: parent.width - x * 2; height: bar.errorHeight
        Type { text: bar.player.error; color: Theme.warning; font.pixelSize: 12; Layout.fillWidth: true }
        IconButton { implicitWidth: 28; implicitHeight: 28; glyph: "close"; text: "Dismiss playback error"; onClicked: bar.player.dismissError() }
    }
    Item {
        id: body
        x: Theme.outerMargin(bar.width); y: bar.errorHeight
        width: parent.width - x * 2; height: parent.height - y
        RowLayout {
            id: track
            objectName: "playerTrackRegion"
            x: 0; y: bar.compact ? 8 : 22
            width: Math.max(100, (bar.compact ? transport.x : timeline.x) - 20)
            height: bar.compact ? 42 : 44
            spacing: 12
            LibraryCover { Layout.preferredWidth: bar.compact ? 38 : 44; Layout.preferredHeight: width; source: bar.player.current.image || "" }
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
                TextLink { objectName: "playerAlbumLink"; text: bar.player.current.title || "Nothing playing"; color: Theme.text; Layout.fillWidth: true; font.weight: Font.DemiBold; enabled: Boolean(bar.player.current.id); onClicked: libraryBrowser.visitTrack(bar.player.current.id, "album") }
                RowLayout {
                    id: artistLine
                    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 8
                    TextLink {
                        id: artistLink
                        objectName: "playerArtistLink"; text: bar.player.current.artist || "Choose music from your Library"
                        font.pixelSize: 12; Layout.minimumWidth: 0
                        Layout.preferredWidth: Math.min(implicitWidth, Math.max(0, artistLine.width - (stream.visible ? stream.implicitWidth + artistLine.spacing : 0)))
                        Layout.fillWidth: !stream.visible
                        enabled: Boolean(bar.player.current.id)
                        onClicked: libraryBrowser.visitTrack(bar.player.current.id, "artist")
                    }
                    Type {
                        id: stream
                        objectName: "playerSourceStream"
                        text: bar.player.sourceStream
                        color: Theme.success; font.pixelSize: 12
                        visible: text.length > 0
                        Layout.preferredWidth: implicitWidth; Layout.minimumWidth: implicitWidth
                        Accessible.name: "Source audio " + text
                    }
                    Item { visible: stream.visible; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                }
            }
        }
        TransportControls {
            id: transport
            objectName: "playerTransport"
            player: bar.player; compact: bar.compact
            x: bar.compact ? utilities.x - width - 12 : (body.width - width) / 2
            y: bar.compact ? 8 : 4
            width: implicitWidth; height: 42
        }
        RowLayout {
            id: timeline
            objectName: "playerTimeline"
            x: (body.width - width) / 2; y: bar.compact ? 65 : 49
            width: bar.compact ? body.width : Math.min(520, body.width * 0.44)
            height: 28; spacing: 8
            Type { text: bar.time(seek.displayedPosition); color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 48 }
            SeekBar {
                id: seek
                objectName: "playerSeek"
                Layout.fillWidth: true
                playbackPosition: bar.player.position; length: bar.player.duration; trackKey: bar.player.currentQueueId
                enabled: length > 0 && (bar.player.state === "playing" || bar.player.state === "paused" || bar.player.state === "buffering")
                onSeekRequested: function(seconds) { bar.player.seek(seconds) }
            }
            Type { text: bar.time(bar.player.duration); color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 48; horizontalAlignment: Text.AlignRight }
        }
        RowLayout {
            id: utilities
            objectName: "playerUtilities"
            x: body.width - width; y: bar.compact ? 11 : 26
            width: implicitWidth; height: 36; spacing: 8
            Icon { visible: !bar.compact; name: "volume"; ink: Theme.muted; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
            PlayerSlider { visible: !bar.compact; objectName: "playerVolume"; Layout.preferredWidth: 90; from: 0; to: 100; value: bar.player.volume; Accessible.name: "Volume"; onMoved: bar.player.setVolume(value) }
            IconButton { objectName: "playerQueue"; glyph: "queue"; text: "Queue · " + bar.player.count + " tracks"; onClicked: bar.queueRequested() }
            IconButton { objectName: "playerOptions"; glyph: "more"; text: "Playback options"; onClicked: options.open() }
        }
    }
    Popup {
        id: options
        objectName: "playerOptionsMenu"
        parent: Overlay.overlay
        x: parent.width - width - Theme.outerMargin(bar.width)
        y: parent.height - bar.height - height - 8
        width: 230; padding: 12; focus: true
        background: Rectangle { color: Theme.surface; radius: Theme.radius; border.width: 1; border.color: Theme.divider }
        contentItem: ColumnLayout {
            spacing: 8
            FlatButton { Layout.fillWidth: true; quiet: true; text: "Shuffle: " + (bar.player.shuffle ? "on" : "off"); onClicked: { bar.player.toggleShuffle(); options.close() } }
            FlatButton { Layout.fillWidth: true; quiet: true; text: "Repeat: " + bar.player.repeat; onClicked: { bar.player.cycleRepeat(); options.close() } }
            FlatButton { Layout.fillWidth: true; quiet: true; text: "Audio details & output"; onClicked: { options.close(); playback.refreshAudioDevices(); reviewController.navigate("settings") } }
            FlatButton { objectName: "playerStop"; Layout.fillWidth: true; quiet: true; text: "Stop"; enabled: bar.player.count > 0; onClicked: { bar.player.stop(); options.close() } }
            Divider { Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Icon { name: "volume"; ink: Theme.muted; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                PlayerSlider { objectName: "playerVolumeCompact"; Layout.fillWidth: true; from: 0; to: 100; value: bar.player.volume; Accessible.name: "Volume"; onMoved: bar.player.setVolume(value) }
                Type { text: Math.round(bar.player.volume) + "%"; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 34 }
            }
        }
    }
}
