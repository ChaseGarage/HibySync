import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

Modal {
    id: dialog
    required property var manager
    property int tab: 0
    property int chosenCover: -1
    property bool optimize: false
    readonly property var edits: manager.current.values || ({})
    readonly property var original: manager.current.original || ({})
    objectName: "libraryMetadataDialog"
    width: Math.min(parent.width - 48, manager.scope === "track" ? 760 : 980)
    height: Math.min(parent.height - 48, 760)
    visible: manager.open
    closePolicy: Popup.NoAutoClose
    background: Rectangle { color: Theme.background; radius: 8; border.width: 1; border.color: Theme.divider }
    onVisibleChanged: if (visible) { tab = manager.artworkStart ? 1 : 0; chosenCover = -1; optimize = false }
    contentItem: ColumnLayout {
        spacing: 16
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Type { text: dialog.manager.mode === "results" ? "Library changes" : dialog.manager.mode === "preview" ? "Review changes" : "Edit " + dialog.manager.scope; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Type { text: dialog.manager.mode === "preview" ? Theme.countLabel(dialog.manager.affected, "file") + " will change" : Theme.countLabel(dialog.manager.included, "selected file"); color: Theme.muted; font.pixelSize: 12 }
            }
            IconButton { glyph: "close"; text: "Discard unsaved edits and close"; enabled: !dialog.manager.busy; onClicked: dialog.manager.dismiss() }
        }
        Type { text: dialog.manager.message; visible: text.length > 0; color: dialog.manager.error ? Theme.error : Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
        ColumnLayout {
            visible: dialog.manager.busy && !dialog.manager.artworkBusy; Layout.fillWidth: true; spacing: 6
            RowLayout {
                Type { text: dialog.manager.phase; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                FlatButton { text: "Cancel"; quiet: true; onClicked: dialog.manager.cancel() }
            }
            Rectangle {
                Layout.fillWidth: true; height: 2; color: Theme.divider
                Rectangle { height: 2; width: parent.width * Math.max(.03, dialog.manager.progress); color: Theme.muted }
            }
        }
        RowLayout {
            visible: dialog.manager.mode === "edit"
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 20
            ColumnLayout {
                visible: dialog.manager.scope !== "track"
                Layout.preferredWidth: dialog.width < 800 ? 150 : 200
                Layout.fillHeight: true; spacing: 8
                RowLayout {
                    visible: dialog.manager.scope !== "track"; enabled: !dialog.manager.busy
                    IconButton { glyph: "plus"; text: "Select all files"; onClicked: dialog.manager.setSelection("all", true) }
                    IconButton { glyph: "close"; text: "Clear file selection"; onClicked: dialog.manager.setSelection("all", false) }
                    IconButton { visible: dialog.manager.scope === "artist"; glyph: "folder"; text: "Select this track's album"; onClicked: dialog.manager.setSelection("album", true) }
                }
                ListView {
                    id: selection
                    objectName: "libraryEditSelection"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    model: dialog.manager.tracks
                    ScrollBar.vertical: ThinScrollBar {}
                    delegate: RowLayout {
                        required property var record
                        width: selection.width; height: 58; spacing: 4
                        ToggleRow { Layout.preferredWidth: 26; text: ""; selected: record.included; enabled: !dialog.manager.busy; onClicked: dialog.manager.toggleIncluded(record.index) }
                        FlatButton { text: record.title; quiet: !record.current; Layout.fillWidth: true; enabled: !dialog.manager.busy; onClicked: dialog.manager.select(record.index) }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                Type { text: dialog.manager.current.path || ""; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                RowLayout {
                    FlatButton { text: "Metadata"; quiet: dialog.tab !== 0; onClicked: dialog.tab = 0 }
                    FlatButton { text: "Artwork"; quiet: dialog.tab !== 1; onClicked: dialog.tab = 1 }
                }
                ScrollView {
                    id: fieldsScroll
                    visible: dialog.tab === 0
                    Layout.fillWidth: true; Layout.fillHeight: true
                    contentWidth: availableWidth
                    ScrollBar.vertical: ThinScrollBar {}
                    ColumnLayout {
                        width: fieldsScroll.availableWidth; spacing: 14
                        enabled: !dialog.manager.busy
                        Type { text: dialog.manager.current.error || ""; color: Theme.error; wrapMode: Text.Wrap; visible: text.length > 0; Layout.fillWidth: true }
                        ColumnLayout {
                            visible: dialog.manager.scope === "artist"
                            Layout.fillWidth: true; spacing: 8
                            Field { id: rename; editorName: "libraryRenameArtist"; label: "Correct artist name"; text: dialog.manager.artist; Layout.fillWidth: true }
                            ToggleRow { id: renameTrack; selected: true; text: "Track artist"; onClicked: selected = !selected }
                            ToggleRow { id: renameAlbum; selected: true; text: "Album artist"; onClicked: selected = !selected }
                            FlatButton { text: "Apply name to selected files"; onClicked: dialog.manager.renameArtist(rename.text, renameTrack.selected, renameAlbum.selected) }
                            Type { text: "Only matching artist values change. The preview shows any grouping with an existing name."; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Divider { Layout.fillWidth: true }
                        }
                        GridLayout {
                            Layout.fillWidth: true; columns: 2; columnSpacing: 16; rowSpacing: 14
                            Repeater {
                                model: [{key:"title",label:"Title"}, {key:"track_artist",label:"Artist"},
                                    {key:"album_artist",label:"Album artist"}, {key:"album",label:"Album"},
                                    {key:"year",label:"Release year"}, {key:"track_number",label:"Track number"},
                                    {key:"disc_number",label:"Disc number"}, {key:"genre",label:"Genre"}]
                                ColumnLayout {
                                    required property var modelData
                                    Layout.columnSpan: ["title", "track_artist", "album_artist", "album"].indexOf(modelData.key) >= 0 ? 2 : 1
                                    Layout.fillWidth: true; spacing: 5
                                    Field { editorName: "libraryEdit_" + modelData.key; label: modelData.label; text: dialog.edits[modelData.key] || ""; Layout.fillWidth: true; onEdited: function(value) { dialog.manager.setField(modelData.key, value) } }
                                    Type { text: "Original: " + (dialog.original[modelData.key] || "∅"); visible: (dialog.edits[modelData.key] || "") !== (dialog.original[modelData.key] || ""); color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                                }
                            }
                        }
                        FlatButton { visible: dialog.manager.scope !== "track"; text: "Apply album fields to selected files"; onClicked: dialog.manager.applyAlbum() }
                        Type { visible: dialog.manager.scope !== "track"; text: "Copies album artist, album, year, and genre; keeps individual titles, artists, and numbers."; wrapMode: Text.Wrap; font.pixelSize: 12; color: Theme.muted; Layout.fillWidth: true }
                    }
                }
                ColumnLayout {
                    visible: dialog.tab === 1
                    Layout.fillWidth: true; Layout.fillHeight: true; spacing: 10
                    RowLayout {
                        FlatButton { text: "Choose image…"; enabled: !dialog.manager.busy; onClicked: imageFile.open() }
                        FlatButton { objectName: "libraryAppleSearch"; Layout.preferredWidth: 134; text: dialog.manager.artworkBusy ? "Cancel search" : "Apple artwork"; enabled: !dialog.manager.busy || dialog.manager.artworkBusy; onClicked: dialog.manager.artworkBusy ? dialog.manager.cancel() : dialog.manager.searchApple(artArtist.text, artAlbum.text) }
                        Type { objectName: "libraryAppleMessage"; text: dialog.manager.appleMessage; color: Theme.error; font.pixelSize: 12; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                    }
                    RowLayout {
                        Field { id: artArtist; label: "Search artist"; text: dialog.edits.album_artist || dialog.edits.track_artist || ""; Layout.fillWidth: true }
                        Field { id: artAlbum; label: "Search album"; text: dialog.edits.album || ""; Layout.fillWidth: true }
                    }
                    ListView {
                        id: covers
                        objectName: "libraryEditorArtworkList"
                        Layout.fillWidth: true; Layout.fillHeight: true
                        clip: true; model: dialog.manager.artwork
                        ScrollBar.vertical: ThinScrollBar {}
                        delegate: AbstractButton {
                            required property var record
                            width: covers.width; height: 98; hoverEnabled: true
                            enabled: !dialog.manager.busy
                            background: Rectangle { color: dialog.chosenCover === record.index ? Theme.hover : parent.hovered ? Theme.surface : "transparent"; radius: Theme.radius }
                            contentItem: RowLayout {
                                spacing: 12
                                Artwork { Layout.preferredWidth: 80; Layout.preferredHeight: 80; source: record.image }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Type { text: record.label; Layout.fillWidth: true }
                                    Type { text: record.resolution + " · " + record.origin; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                                }
                            }
                            onClicked: dialog.chosenCover = record.index
                            onDoubleClicked: dialog.manager.showFullArtwork(record.index)
                        }
                    }
                    ToggleRow { selected: dialog.optimize; text: "Optimize for HiBy (600px JPEG, quality 88)"; onClicked: dialog.optimize = !dialog.optimize }
                    RowLayout {
                        enabled: dialog.chosenCover >= 0 && !dialog.manager.busy
                        FlatButton { text: "Preview"; quiet: true; onClicked: dialog.manager.showFullArtwork(dialog.chosenCover) }
                        FlatButton { text: "Use for track"; onClicked: dialog.manager.useArtwork(dialog.chosenCover, false, dialog.optimize) }
                        FlatButton { visible: dialog.manager.scope !== "track"; text: "Use for selected files"; onClicked: dialog.manager.useArtwork(dialog.chosenCover, true, dialog.optimize) }
                    }
                    Type { text: dialog.manager.current.artwork || ""; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                    FlatButton { text: "Keep original artwork"; quiet: true; onClicked: dialog.manager.keepArtwork() }
                }
            }
        }
        ColumnLayout {
            visible: dialog.manager.mode !== "edit"
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            Type {
                visible: dialog.manager.mode === "preview"
                text: "Save changes only after reviewing these files. Playback will stop to release open files. Originals will be backed up."
                color: Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            Type { visible: dialog.manager.mode === "preview" && dialog.manager.reorganize; text: "Only selected audio files move; folder images and other files stay in their original folders."; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Type {
                visible: dialog.manager.mode === "results"
                text: (dialog.manager.report.saved || 0) + " saved · " + (dialog.manager.report.failed || 0) + " failed · " + (dialog.manager.report.skipped || 0) + " skipped · " + (dialog.manager.report.unprocessed || 0) + " unprocessed"
                color: dialog.manager.report.failed ? Theme.error : dialog.manager.report.cancelled ? Theme.warning : Theme.success
                wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            Type { visible: dialog.manager.mode === "results"; text: "Recovery backups: " + (dialog.manager.report.recovery || "") + (dialog.manager.report.indexError ? "\nIndex refresh failed: " + dialog.manager.report.indexError : ""); color: dialog.manager.report.indexError ? Theme.error : Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ListView {
                id: changes
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                model: dialog.manager.mode === "preview" ? dialog.manager.preview : dialog.manager.results
                ScrollBar.vertical: ThinScrollBar {}
                delegate: Column {
                    required property var record
                    width: changes.width - 8; spacing: 8; height: implicitHeight + 20
                    Type { text: (record.status || record.action) + " · " + record.source; width: parent.width; color: record.error ? Theme.error : Theme.text; wrapMode: Text.Wrap }
                    Type { text: "→ " + record.destination; visible: record.source !== record.destination; width: parent.width; color: Theme.muted; wrapMode: Text.Wrap }
                    Type { text: record.changes; visible: text.length > 0; width: parent.width; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Type { text: record.artwork; visible: text.length > 0; width: parent.width; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Type { text: record.error; visible: text.length > 0; width: parent.width; color: Theme.error; wrapMode: Text.Wrap }
                    Type { text: record.warning || ""; visible: text.length > 0; width: parent.width; color: Theme.warning; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Divider { width: parent.width }
                }
            }
        }
        Divider { Layout.fillWidth: true }
        ToggleRow { visible: dialog.manager.mode === "edit"; selected: dialog.manager.reorganize; text: "Reorganize files using the library naming rules (preview paths first)"; enabled: !dialog.manager.busy; onClicked: dialog.manager.setReorganize(!selected) }
        RowLayout {
            Layout.fillWidth: true
            FlatButton { text: dialog.manager.mode === "results" ? "Close" : "Discard changes"; quiet: true; enabled: !dialog.manager.busy; onClicked: dialog.manager.dismiss() }
            Item { Layout.fillWidth: true }
            FlatButton { visible: dialog.manager.mode === "preview"; text: "Back to editing"; enabled: !dialog.manager.busy; onClicked: dialog.manager.back() }
            FlatButton { objectName: "libraryEditPreview"; visible: dialog.manager.mode === "edit"; text: "Preview changes"; enabled: !dialog.manager.busy && dialog.manager.included > 0; onClicked: dialog.manager.buildPreview() }
            FlatButton { objectName: "libraryEditSave"; visible: dialog.manager.mode === "preview"; text: "Save " + Theme.countLabel(dialog.manager.affected, "file"); primary: true; enabled: !dialog.manager.busy && dialog.manager.canSave; onClicked: dialog.manager.save() }
        }
    }
    FileDialog {
        id: imageFile
        title: "Choose cover artwork"
        nameFilters: ["Artwork (*.jpg *.jpeg *.png)"]
        onAccepted: dialog.manager.manualArtwork(selectedFile)
    }
    Modal {
        id: full
        property bool actualSize: false
        visible: dialog.manager.fullImage.length > 0
        width: Math.min(parent.width - 48, 1000); height: parent.height - 48
        closePolicy: Popup.NoAutoClose
        contentItem: ColumnLayout {
            spacing: 12
            RowLayout {
                Type { text: "Artwork preview"; font.pixelSize: 20; Layout.fillWidth: true }
                FlatButton { text: full.actualSize ? "Fit" : "Actual size"; onClicked: full.actualSize = !full.actualSize }
                IconButton { glyph: "close"; text: "Close full artwork"; onClicked: dialog.manager.closeFullArtwork() }
            }
            Flickable {
                id: fullViewport
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                contentWidth: Math.max(width, fullImage.width); contentHeight: Math.max(height, fullImage.height)
                ScrollBar.vertical: ThinScrollBar {}
                ScrollBar.horizontal: ThinScrollBar {}
                Image { id: fullImage; source: dialog.manager.fullImage; asynchronous: true; cache: false; width: full.actualSize ? implicitWidth : fullViewport.width; height: full.actualSize ? implicitHeight : fullViewport.height; fillMode: Image.PreserveAspectFit }
            }
        }
    }
}
