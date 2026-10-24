import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ScrollView {
    id: page
    required property var controller
    signal folderRequested(var field)
    contentWidth: availableWidth
    ScrollBar.vertical: ThinScrollBar {}
    ColumnLayout {
        width: page.availableWidth
        spacing: 24
        FlatButton { text: "←  Library"; quiet: true; onClicked: page.controller.navigate("library") }
        Type { text: "Settings"; font.pixelSize: Theme.title; font.weight: Font.DemiBold }
        ColumnLayout {
            Layout.fillWidth: true; Layout.maximumWidth: 700; spacing: 16
            Type { text: "Audio"; font.pixelSize: 19; font.weight: Font.DemiBold }
            Type { text: "Output device"; color: Theme.muted; font.pixelSize: Theme.small }
            RowLayout {
                Layout.fillWidth: true
                FlatButton {
                    id: deviceButton
                    objectName: "audioDeviceButton"
                    Layout.fillWidth: true
                    text: {
                        if (playback.audioDevice === "auto") return "System default · prefer PipeWire"
                        for (let i = 0; i < playback.audioDevices.length; ++i)
                            if (playback.audioDevices[i].name === playback.audioDevice) return playback.audioDevices[i].description
                        return playback.audioDevice
                    }
                    onClicked: { playback.refreshAudioDevices(); devices.open() }
                    Popup {
                        id: devices
                        y: deviceButton.height + 6; width: deviceButton.width; height: Math.min(300, deviceList.contentHeight + 16)
                        padding: 8; focus: true
                        background: Rectangle { color: Theme.surface; radius: Theme.radius; border.width: 1; border.color: Theme.divider }
                        contentItem: ListView {
                            id: deviceList
                            clip: true; model: playback.audioDevices
                            ScrollBar.vertical: ThinScrollBar {}
                            delegate: FlatButton {
                                required property var modelData
                                width: deviceList.width; quiet: true
                                text: (modelData.name === playback.audioDevice ? "•  " : "") + (modelData.name === "auto" ? "System default · prefer PipeWire" : modelData.description)
                                onClicked: { playback.selectAudioDevice(modelData.name); devices.close() }
                            }
                            Type { anchors.centerIn: parent; visible: deviceList.count === 0; text: "Discovering devices…"; color: Theme.muted }
                        }
                    }
                }
                FlatButton { objectName: "refreshAudioDevices"; text: "Refresh"; quiet: true; onClicked: playback.refreshAudioDevices() }
            }
            Type { text: "Changing output may briefly interrupt audio. System routing and DAC processing remain controlled by your audio stack."; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: Theme.small }
            Divider { Layout.fillWidth: true }
            Type { text: "Source file"; color: Theme.muted; font.pixelSize: Theme.small }
            Type { objectName: "audioSourceInfo"; text: playback.audioSource; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Type { text: "Decoded audio"; color: Theme.muted; font.pixelSize: Theme.small }
            Type { text: playback.decodedAudio; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Type { text: "Active output · mpv → audio API"; color: Theme.muted; font.pixelSize: Theme.small }
            Type { objectName: "audioOutputInfo"; text: playback.audioOutput; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Type { text: "Sample rate and format are negotiated, not forced. ReplayGain, normalization, equalization and crossfade are off. Volume below 100% attenuates samples. Output shown here does not verify the PipeWire graph or DAC; bit-perfect output is not established."; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Type { text: playback.mediaStatus; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Divider { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8 }
            Type { text: "Music folders"; font.pixelSize: 19; font.weight: Font.DemiBold }
            Type { text: "Folder changes take effect on your next scan."; color: Theme.muted; font.pixelSize: Theme.small }
            RowLayout {
                Field { id: inbox; label: "Incoming downloads"; text: page.controller.inbox; Layout.fillWidth: true }
                IconButton { glyph: "folder"; text: "Choose incoming folder"; Layout.alignment: Qt.AlignBottom; onClicked: page.folderRequested(inbox) }
            }
            RowLayout {
                Field { id: library; label: "Music library"; text: page.controller.library; Layout.fillWidth: true }
                IconButton { glyph: "folder"; text: "Choose library folder"; Layout.alignment: Qt.AlignBottom; onClicked: page.folderRequested(library) }
            }
            FlatButton { text: "Use these folders"; enabled: !page.controller.busy; onClicked: { page.controller.setPaths(inbox.text, library.text); page.controller.navigate("library") } }
        }
        Item { Layout.preferredHeight: 16 }
    }
}
