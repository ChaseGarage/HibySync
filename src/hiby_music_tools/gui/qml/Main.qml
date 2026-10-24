import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "."
import "components"
import "pages"

ApplicationWindow {
    id: window
    objectName: "hibysyncWindow"
    width: 1200
    height: 800
    minimumWidth: 700
    minimumHeight: 600
    visible: true
    title: "HibySync"
    color: Theme.background
    font.family: Theme.family
    font.pixelSize: Theme.body
    property var controller: reviewController
    property var folderTarget: null
    property int chosenArtwork: -1
    property bool artForTrack: false
    readonly property string currentSection: controller.page === "settings" ? "settings" : controller.page === "library" ? "library" : controller.page === "device" ? "device" : "import"
    readonly property real outerMargin: Theme.outerMargin(width)
    readonly property real sectionMaxWidth: currentSection === "library" ? Theme.libraryMaxWidth : Theme.maxWidth
    function playbackShortcutAllowed() {
        let item = activeFocusItem
        while (item) {
            if (item instanceof TextInput || item instanceof TextEdit || item instanceof AbstractButton || item instanceof Slider)
                return false
            item = item.parent
        }
        return !deviceDashboard.sync.confirmationOpen && !deviceDashboard.previewOpen && !libraryPlaylists.choosing && !libraryDeletion.open && !libraryEditor.open && !artDialog.opened && !trackDrawer.opened && !queueDrawer.opened && !importDialog.opened && !rescanDialog.opened
    }
    Shortcut {
        sequence: "Space"
        context: Qt.WindowShortcut
        enabled: window.playbackShortcutAllowed()
        onActivated: playback.togglePause()
    }
    function navigateBack() {
        if (deviceDashboard.sync.confirmationOpen) { deviceDashboard.sync.invalidate(); return }
        if (deviceDashboard.previewOpen) { deviceDashboard.closePreview(); return }
        // Editing and destructive confirmations keep their explicit actions.
        if (libraryEditor.open || libraryDeletion.open || importDialog.opened || rescanDialog.opened) return
        if (libraryPlaylists.choosing) { if (!libraryPlaylists.busy) libraryPlaylists.dismiss(); return }
        if (artDialog.opened) { if (!controller.artworkBusy) artDialog.close(); return }
        if (trackDrawer.opened) { trackDrawer.close(); return }
        if (queueDrawer.opened) { queueDrawer.close(); return }
        uiNavigation.back()
    }
    function navigateForward() {
        if (!deviceDashboard.sync.confirmationOpen && !deviceDashboard.previewOpen && !libraryEditor.open && !libraryDeletion.open && !libraryPlaylists.choosing &&
                !artDialog.opened && !trackDrawer.opened && !queueDrawer.opened &&
                !importDialog.opened && !rescanDialog.opened) uiNavigation.forward()
    }
    Connections {
        target: uiNavigation
        function onBackRequested() { window.navigateBack() }
        function onForwardRequested() { window.navigateForward() }
    }
    Shortcut { sequence: "Alt+Left"; onActivated: window.navigateBack() }
    Shortcut { sequence: "Alt+Right"; onActivated: window.navigateForward() }
    onClosing: function(close) {
        const deviceReady = deviceDashboard.requestClose()
        const playlistsReady = libraryPlaylists.requestClose()
        const deletionReady = libraryDeletion.requestClose()
        const editorReady = libraryEditor.requestClose()
        const importReady = controller.requestClose()
        const libraryReady = libraryBrowser.requestClose()
        const playerReady = playback.requestClose()
        close.accepted = importReady && libraryReady && playerReady && editorReady && deletionReady && playlistsReady && deviceReady
    }

    Connections {
        target: window.controller
        function onSafeToClose() { window.close() }
        function onScanConfirmationRequired() { rescanDialog.open() }
        function onImportConfirmationRequired() { importDialog.open() }
    }
    Connections {
        target: libraryBrowser
        function onSafeToClose() { window.close() }
    }
    Connections { target: deviceDashboard; function onSafeToClose() { window.close() } }
    Connections { target: playback; function onSafeToClose() { window.close() } }
    Connections { target: libraryEditor; function onSafeToClose() { window.close() } }
    LibraryMetadataEditor { manager: libraryEditor }
    Connections { target: libraryDeletion; function onSafeToClose() { window.close() } }
    LibraryDeleteDialog { manager: libraryDeletion }
    Connections { target: libraryPlaylists; function onSafeToClose() { window.close() } }
    PlaylistPicker {}

    Item {
        id: header
        height: 76
        width: Math.min(parent.width - window.outerMargin * 2, Theme.libraryMaxWidth)
        anchors.horizontalCenter: parent.horizontalCenter
        RowLayout {
            anchors.fill: parent
            spacing: 0
            Type { text: "HibySync"; font.pixelSize: 20; font.weight: Font.DemiBold; Layout.rightMargin: 48 }
            Repeater {
                model: [{title: "Import", page: "import"}, {title: "Library", page: "library"}, {title: "Device", page: "device"}]
                NavButton {
                    required property var modelData
                    objectName: "navigation_" + modelData.page
                    text: modelData.title
                    selected: window.currentSection === modelData.page
                    Layout.alignment: Qt.AlignBottom
                    onClicked: window.controller.navigate(modelData.page)
                }
            }
            Item { Layout.fillWidth: true }
            IconButton { text: "Settings"; glyph: "settings"; enabled: !window.controller.busy; onClicked: { playback.refreshAudioDevices(); window.controller.navigate("settings") } }
        }
    }
    Divider { y: header.height; width: parent.width }

    ColumnLayout {
        id: content
        anchors.top: header.bottom
        anchors.bottom: playerBar.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: window.width < 1000 ? 24 : 32
        anchors.bottomMargin: 24
        width: Math.min(parent.width - window.outerMargin * 2, window.sectionMaxWidth)
        spacing: 20
        Type { text: libraryDeletion.notice; visible: text.length > 0; color: Theme.success; font.pixelSize: Theme.small; Layout.fillWidth: true }
        ColumnLayout {
            visible: window.controller.busy
            Layout.fillWidth: true
            spacing: 10
            RowLayout {
                Type { text: window.controller.operationLabel; color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
                FlatButton { text: "Cancel"; quiet: true; onClicked: window.controller.cancel(); visible: window.controller.page !== "import" }
            }
            Rectangle {
                Layout.fillWidth: true
                height: 2
                color: Theme.divider
                Rectangle { width: parent.width * (window.controller.progress < 0 ? 0.2 : window.controller.progress); height: 2; color: Theme.muted }
            }
        }
        Type {
            objectName: "notification"
            visible: text.length > 0
            Layout.fillWidth: true
            text: window.controller.message
            color: window.controller.messageKind === "error" ? Theme.error : window.controller.messageKind === "warning" ? Theme.warning : Theme.muted
            font.pixelSize: Theme.small
            wrapMode: Text.Wrap
            maximumLineCount: 3
        }
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: ({"import": 0, "review": 1, "preview": 2, "settings": 3, "library": 4, "device": 5, "complete": 6})[window.controller.page]
            ImportPage { controller: window.controller; onSettingsRequested: window.controller.navigate("settings") }
            ReviewPage {
                controller: window.controller
                enabled: !window.controller.busy
                onTrackRequested: function(index) { window.controller.selectTrack(index); trackDrawer.open() }
                onArtworkRequested: function(index) { window.openArtwork(index) }
            }
            PreviewPage { controller: window.controller }
            SettingsPage {
                controller: window.controller
                enabled: !window.controller.busy
                onFolderRequested: function(field) {
                    window.folderTarget = field
                    folderDialog.currentFolder = window.controller.folderUrl(field.text)
                    folderDialog.open()
                }
            }
            LibraryPage { browser: libraryBrowser; sourceController: window.controller }
            DevicePage { manager: deviceDashboard; sourceController: window.controller }
            CompletePage { controller: window.controller }
        }
    }

    PlayerBar {
        id: playerBar
        objectName: "playerBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        player: playback
        onQueueRequested: queueDrawer.open()
    }
    SideSheet {
        id: queueDrawer
        objectName: "queueDrawer"
        width: Math.min(window.width - 40, 480)
        height: window.height
        QueuePanel { anchors.fill: parent; player: playback; onCloseRequested: queueDrawer.close() }
    }

    FolderDialog {
        id: folderDialog
        title: "Choose music folder"
        onAccepted: { if (window.folderTarget) window.folderTarget.text = window.controller.folderPath(selectedFolder) }
    }

    SideSheet {
        id: trackDrawer
        objectName: "trackDrawer"
        width: Math.min(window.width - 48, 400)
        height: window.height
        contentItem: ScrollView {
            id: trackScroll
            contentWidth: availableWidth
            contentHeight: trackEditor.implicitHeight
            ScrollBar.vertical: ThinScrollBar {}
            TrackEditor {
                id: trackEditor
                controller: window.controller
                width: trackScroll.availableWidth
                height: Math.max(implicitHeight, trackScroll.availableHeight)
                onCloseRequested: trackDrawer.close()
                onArtworkRequested: function(index) { window.openArtwork(index) }
            }
        }
    }

    function openArtwork(index) {
        controller.prepareArtwork(index)
        chosenArtwork = -1
        artForTrack = index >= 0
        artDialog.open()
    }
    Modal {
        id: artDialog
        objectName: "artworkDialog"
        width: Math.min(window.width - 64, 760)
        height: Math.min(window.height - 64, window.controller.artworkMode === "apple" ? 600 : 480)
        contentItem: ColumnLayout {
            spacing: 16
            RowLayout {
                Type { text: "Choose artwork"; font.pixelSize: 20; font.weight: Font.DemiBold; Layout.fillWidth: true }
                IconButton { glyph: "close"; text: "Close artwork selection"; onClicked: artDialog.close() }
            }
            RowLayout {
                spacing: 8
                NavButton {
                    text: "Embedded & folder"
                    implicitHeight: 36
                    selected: window.controller.artworkMode === "local"
                    onClicked: { window.chosenArtwork = -1; window.controller.setArtworkMode("local") }
                }
                NavButton {
                    objectName: "appleArtworkTab"
                    text: "Apple artwork"
                    implicitHeight: 36
                    selected: window.controller.artworkMode === "apple"
                    onClicked: {
                        window.chosenArtwork = -1
                        window.controller.setArtworkMode("apple")
                        window.controller.searchApple(appleArtist.text, appleAlbum.text)
                    }
                }
            }
            RowLayout {
                visible: window.controller.artworkMode === "apple"
                Layout.fillWidth: true
                spacing: 12
                Field { id: appleArtist; editorName: "appleArtistInput"; label: "Artist"; text: window.controller.album.artist || ""; Layout.fillWidth: true; enabled: !window.controller.busy }
                Field { id: appleAlbum; editorName: "appleAlbumInput"; label: "Album"; text: window.controller.album.title || ""; Layout.fillWidth: true; enabled: !window.controller.busy }
                FlatButton {
                    objectName: "searchAppleButton"
                    text: window.controller.artworkBusy ? "Cancel" : "Refresh"
                    Layout.alignment: Qt.AlignBottom
                    enabled: !window.controller.busy || window.controller.artworkBusy
                    onClicked: {
                        if (window.controller.artworkBusy) window.controller.cancel()
                        else { window.chosenArtwork = -1; window.controller.searchApple(appleArtist.text, appleAlbum.text) }
                    }
                }
            }
            Type {
                visible: text.length > 0
                text: window.controller.artworkMessage
                color: window.controller.artworkError ? Theme.error : Theme.muted
                font.pixelSize: Theme.small
                wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true
            }
            ListView {
                id: artworkList
                Layout.fillWidth: true; Layout.fillHeight: true
                orientation: ListView.Horizontal
                spacing: 16
                clip: true
                model: window.controller.artwork
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.horizontal: ThinScrollBar {}
                delegate: AbstractButton {
                    id: candidate
                    required property var record
                    objectName: "artCandidate" + record.candidateIndex
                    width: 168; height: artworkList.height - 8
                    hoverEnabled: true
                    background: Rectangle {
                        color: candidate.hovered ? Theme.hover : "transparent"
                        radius: Theme.radius
                        border.width: window.chosenArtwork === candidate.record.candidateIndex ? 1 : 0
                        border.color: Theme.muted
                    }
                    contentItem: ColumnLayout {
                        spacing: 8
                        Artwork { Layout.preferredWidth: 152; Layout.preferredHeight: 152; Layout.alignment: Qt.AlignHCenter; source: candidate.record.image }
                        Type { Layout.fillWidth: true; Layout.leftMargin: 8; text: candidate.record.label; font.pixelSize: Theme.small }
                        Type { Layout.fillWidth: true; Layout.leftMargin: 8; text: candidate.record.dimensions + " · " + candidate.record.origin; color: Theme.muted; font.pixelSize: 12 }
                        Type { Layout.leftMargin: 8; text: candidate.record.selected ? "Currently selected" : ""; color: Theme.muted; font.pixelSize: 12 }
                        Item { Layout.fillHeight: true }
                    }
                    enabled: !window.controller.busy
                    onClicked: window.chosenArtwork = record.candidateIndex
                }
                Type {
                    anchors.centerIn: parent; visible: artworkList.count === 0 && !window.controller.artworkBusy
                    text: window.controller.artworkMode === "apple" ? "No Apple covers found. Refresh to search again." : "No local artwork available."
                    color: Theme.muted
                }
            }
            RowLayout {
                Type { text: "Choose a cover to apply. Originals stay unchanged."; font.pixelSize: 12; color: Theme.muted; Layout.fillWidth: true }
                FlatButton {
                    objectName: "useTrackArtworkButton"
                    visible: window.artForTrack
                    text: "Use for track"
                    enabled: window.chosenArtwork >= 0 && !window.controller.busy
                    onClicked: { window.controller.applyArtwork(window.chosenArtwork, false); artDialog.close() }
                }
                FlatButton {
                    objectName: "useAlbumArtworkButton"
                    text: "Use for album"; primary: true
                    enabled: window.chosenArtwork >= 0 && !window.controller.busy
                    onClicked: { window.controller.applyArtwork(window.chosenArtwork, true); artDialog.close() }
                }
            }
        }
    }
    Modal {
        id: importDialog
        objectName: "importConfirmationDialog"
        width: Math.min(window.width - 64, 540)
        contentItem: ColumnLayout {
            spacing: 20
            Type { text: "Import reviewed music?"; font.pixelSize: 20; font.weight: Font.DemiBold }
            Type {
                text: "Verified copies will be added to " + window.controller.displayPath(window.controller.library) + ". Successfully imported originals will then be removed from the incoming folder. Skipped and failed files will stay."
                color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            Type {
                visible: window.controller.replacementCount > 0
                text: window.controller.replacementCount + " existing file(s) will be replaced. Verified backups will be kept."
                color: Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            RowLayout {
                Item { Layout.fillWidth: true }
                FlatButton { text: "Keep reviewing"; quiet: true; onClicked: importDialog.close() }
                FlatButton { objectName: "confirmImportButton"; text: "Import files"; primary: true; enabled: window.controller.canImport; onClicked: { importDialog.close(); window.controller.confirmImport() } }
            }
        }
    }
    Modal {
        id: rescanDialog
        objectName: "rescanDialog"
        width: 420
        contentItem: ColumnLayout {
            spacing: 20
            Type { text: "Replace this review?"; font.pixelSize: 20; font.weight: Font.DemiBold }
            Type { text: "Scanning again discards your pending edits."; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                Item { Layout.fillWidth: true }
                FlatButton { text: "Keep review"; quiet: true; onClicked: rescanDialog.close() }
                FlatButton { text: "Scan again"; primary: true; onClicked: { rescanDialog.close(); window.controller.confirmScan() } }
            }
        }
    }
}
