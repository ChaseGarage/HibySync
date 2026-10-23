import QtQuick
import ".."

PlayerSlider {
    id: seek
    property real playbackPosition: 0
    property real length: 0
    property string trackKey: ""
    property real targetPosition: 0
    property bool gesturing: false
    property bool awaitingPosition: false
    property string pressedTrack: ""
    readonly property real displayedPosition: pressed || gesturing || awaitingPosition ? value : playbackPosition
    signal seekRequested(real seconds)
    from: 0; to: Math.max(1, length)
    activeFocusOnTab: true
    Accessible.name: "Playback position"
    progressColor: hovered || pressed || activeFocus ? Theme.success : Theme.muted
    Binding {
        target: seek; property: "value"; value: seek.playbackPosition
        when: !seek.pressed && !seek.gesturing && !seek.awaitingPosition
        restoreMode: Binding.RestoreNone
    }
    function commit(seconds) {
        targetPosition = Math.max(0, Math.min(length, seconds))
        awaitingPosition = true
        value = targetPosition
        acknowledgement.start()
        seekRequested(targetPosition)
    }
    onMoved: {
        targetPosition = value
        if (!pressed && !gesturing) commit(value)
    }
    onPressedChanged: {
        if (pressed) { gesturing = true; pressedTrack = trackKey; targetPosition = value }
        else {
            if (gesturing && enabled && pressedTrack === trackKey) commit(targetPosition)
            gesturing = false
        }
    }
    onPlaybackPositionChanged: if (awaitingPosition && Math.abs(playbackPosition - targetPosition) < 0.75) { awaitingPosition = false; acknowledgement.stop() }
    onTrackKeyChanged: { gesturing = false; awaitingPosition = false; acknowledgement.stop() }
    onEnabledChanged: if (!enabled) { gesturing = false; awaitingPosition = false; acknowledgement.stop() }
    Timer { id: acknowledgement; interval: 1200; onTriggered: seek.awaitingPosition = false }
    Keys.onLeftPressed: commit(displayedPosition - 5)
    Keys.onRightPressed: commit(displayedPosition + 5)
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
            commit(event.key === Qt.Key_Home ? 0 : length)
            event.accepted = true
        }
    }
}
