import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: window
    width: 1200; height: 760; minimumWidth: 960; minimumHeight: 640
    visible: true; title: "New Launcher"; color: "#101419"
    flags: Qt.FramelessWindowHint | Qt.Window
    property color bg: "#101419"; property color sidebar: "#171D24"; property color surface: "#1B242C"
    property color raised: "#222B35"; property color outline: "#33414D"; property color primary: launcher.accentColor; property color primaryTint: Qt.rgba(bg.r * 0.8 + primary.r * 0.2, bg.g * 0.8 + primary.g * 0.2, bg.b * 0.8 + primary.b * 0.2, 1)
    property color focus: Qt.lighter(primary, 1.18); property color ink: "#F3F7FA"; property color muted: "#AEB9C5"; property color error: "#FF6B6B"
    property string iconFont: Qt.platform.os === "windows" ? "Segoe Fluent Icons" : "Noto Sans Symbols 2"
    property string currentPage: "Play"; property string lockerTab: "Skin"; property string profileDraft: ""; property string skinDraft: ""; property string accountProvider: ""; property bool accountModalOpen: false; property string elyUsernameDraft: ""; property string elyPasswordDraft: ""
    property string modrinthTab: "Browse"; property string modrinthCategory: "mods"; property string modrinthSearchDraft: ""; property bool modrinthDetailsOpen: false
    property bool installationModalOpen: false; property int installationModalIndex: -1; property string installationModalName: ""; property string installationModalVersion: "latest-release"; property string installationModalLoader: "Vanilla"; property string installationModalJava: ""; property string installationModalWidth: ""; property string installationModalHeight: ""; property bool installationModalForceUpdate: false; property bool installationDeleteArmed: false
    property bool modpackModalOpen: false; property bool modListModalOpen: false; property string modpackModalMode: "create"; property int modpackModalIndex: -1; property string modpackModalName: ""; property string modpackModalVersion: "1.21.1"; property string modpackModalLoader: "Fabric"; property string modpackModalPath: ""; property int modpackLinkIndex: 0; property bool modpackDeleteArmed: false
    property string curseForgeArchiveDraft: ""; property string installationNameDraft: ""; property string installationVersionDraft: "latest-release"; property string installationLoaderDraft: "Vanilla"
    property bool rpcDraft: launcher.settings.rpcEnabled; property bool updatesDraft: launcher.settings.autoUpdates; property bool titlebarDraft: launcher.settings.customTitlebar; property bool neoDraft: launcher.settings.neoStyle; property string accentDraft: launcher.settings.accentColor
    property int installationEditorIndex: launcher.selectedIndex; property bool installationForceUpdateDraft: launcher.selectedInstallation.forceUpdate; property int modpackEditorIndex: 0; property int ramDraft: Number(launcher.settings.ramAllocation)
    function navigate(page) { currentPage = page; if (page === "Modrinth") { launcher.requestMods(); if (launcher.modrinthResults.length === 0) launcher.searchModrinth("", modrinthCategory) } if (page === "Locker") launcher.requestSkinPreview() }
    function openAccountModal() { accountModalOpen = false; Qt.callLater(function() { accountModalOpen = true }) }
    function icon(fileName) { return Qt.resolvedUrl("../../icons/" + fileName) }
    ListModel { id: nav; ListElement { label: "Play"; iconFile: "diamond_sword.png" } ListElement { label: "Installations"; iconFile: "book.png" } ListElement { label: "Modpacks"; iconFile: "shulker_box.png" } ListElement { label: "Modrinth"; iconFile: "turtle_helmet.png" } ListElement { label: "Locker"; iconFile: "diamond_chestplate.png" } }

    Image { anchors.fill: parent; source: launcher.wallpaperUrl; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: true; opacity: 0.42 }
    Rectangle { anchors.fill: parent; color: window.bg; opacity: 0.72 }
    ColumnLayout {
        anchors.fill: parent; spacing: 0
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 34; color: "#141A20"; border.color: "#2B3742"; border.width: 1
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton; onPressed: function(mouse) { window.startSystemMove() }; onDoubleClicked: { if (window.visibility === Window.Maximized) window.showNormal(); else window.showMaximized() } }
            RowLayout { anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 0; spacing: 10
                Text { text: "NLC"; color: window.primary; font.pixelSize: 16; font.weight: Font.DemiBold }
                Text { text: "NEW LAUNCHER"; color: window.muted; font.pixelSize: 11; font.letterSpacing: 1.1 }
                Item { Layout.fillWidth: true } Text { text: "2.8 · QML"; color: window.muted; font.pixelSize: 11; Layout.rightMargin: 8 }
                Rectangle { Layout.preferredWidth: 42; Layout.fillHeight: true; property bool hovered: false; color: hovered ? "#26313B" : "transparent"; Behavior on color { ColorAnimation { duration: 140 } } Text { anchors.centerIn: parent; text: "−"; color: window.ink; font.pixelSize: 18 } MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.parent.hovered = true; onExited: parent.parent.hovered = false; onClicked: window.showMinimized() } }
                Rectangle { Layout.preferredWidth: 42; Layout.fillHeight: true; property bool hovered: false; color: hovered ? "#26313B" : "transparent"; Behavior on color { ColorAnimation { duration: 140 } } Text { anchors.centerIn: parent; text: window.visibility === Window.Maximized ? "❐" : "□"; color: window.ink; font.pixelSize: 14 } MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.parent.hovered = true; onExited: parent.parent.hovered = false; onClicked: { if (window.visibility === Window.Maximized) window.showNormal(); else window.showMaximized() } } }
                Rectangle { Layout.preferredWidth: 46; Layout.fillHeight: true; property bool hovered: false; color: hovered ? "#C42B3A" : "transparent"; Behavior on color { ColorAnimation { duration: 140 } } Text { anchors.centerIn: parent; text: "×"; color: window.ink; font.pixelSize: 19 } MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.parent.hovered = true; onExited: parent.parent.hovered = false; onClicked: window.close() } }
            }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                Layout.fillHeight: true; Layout.preferredWidth: 236; color: window.sidebar; border.color: "#2B3742"; border.width: 1
                ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 8
                    Rectangle { id: accountShortcut; Layout.fillWidth: true; Layout.preferredHeight: 68; radius: 6; color: accountMouse.containsMouse ? "#202A33" : "transparent"
                        RowLayout { anchors.fill: parent; spacing: 12
                            Rectangle { Layout.preferredWidth: 42; Layout.preferredHeight: 42; radius: 6; color: "#2B3742"; clip: true
                                Image { anchors.fill: parent; visible: launcher.profileAvatarUrl !== ""; source: launcher.profileAvatarUrl; sourceClipRect: Qt.rect(8, 8, 8, 8); fillMode: Image.Stretch; smooth: false }
                                Text { anchors.centerIn: parent; visible: launcher.profileAvatarUrl === ""; text: launcher.profileName.slice(0, 1).toUpperCase(); color: window.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
                            }
                            ColumnLayout { Layout.fillWidth: true; spacing: 3
                                Text { text: launcher.profileName; color: window.ink; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { text: launcher.accountLabel; color: window.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                            }
                        }
                        MouseArea { id: accountMouse; anchors.fill: parent; hoverEnabled: true; onClicked: window.navigate("Accounts") }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#2B3742"; Layout.bottomMargin: 12 }
                    Repeater { model: nav; delegate: Rectangle { required property string label; required property string iconFile; property bool selected: label === window.currentPage; property bool hovered: false; Layout.fillWidth: true; Layout.preferredHeight: 44; radius: 6; color: selected ? window.primaryTint : (hovered ? "#202A33" : "transparent"); Behavior on color { ColorAnimation { duration: 140 } } border.width: selected ? 1 : 0; border.color: selected ? window.primary : "transparent"
                        RowLayout { anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10; Image { source: window.icon(parent.parent.iconFile); sourceSize.width: 20; sourceSize.height: 20; Layout.preferredWidth: 20; Layout.preferredHeight: 20; smooth: false; mipmap: false } Text { text: parent.parent.label; color: parent.parent.selected ? window.ink : window.muted; font.pixelSize: 14; font.weight: parent.parent.selected ? Font.DemiBold : Font.Medium; Layout.fillWidth: true } }
                        MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.hovered = true; onExited: parent.hovered = false; onClicked: window.navigate(parent.label) }
                    } }
                    Item { Layout.fillHeight: true }
                    Text { text: "Privacy-first offline play"; color: window.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Rectangle { property bool selected: window.currentPage === "Settings"; property bool hovered: false; Layout.fillWidth: true; Layout.preferredHeight: 44; radius: 6; color: selected ? window.primaryTint : (hovered ? "#202A33" : "transparent"); Behavior on color { ColorAnimation { duration: 140 } } border.width: selected ? 1 : 0; border.color: selected ? window.primary : "transparent"
                        RowLayout { anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10; Image { source: window.icon("redstone_torch.png"); sourceSize.width: 20; sourceSize.height: 20; Layout.preferredWidth: 20; Layout.preferredHeight: 20; smooth: false; mipmap: false } Text { text: "Settings"; color: parent.parent.selected ? window.ink : window.muted; font.pixelSize: 14; font.weight: parent.parent.selected ? Font.DemiBold : Font.Medium; Layout.fillWidth: true } }
                        MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.hovered = true; onExited: parent.hovered = false; onClicked: window.navigate("Settings") }
                    }
                }
            }
            Item { Layout.fillWidth: true; Layout.fillHeight: true
                ColumnLayout { anchors.fill: parent; anchors.leftMargin: Math.max(40, parent.width * 0.07); anchors.rightMargin: Math.max(40, parent.width * 0.07); anchors.topMargin: 38; anchors.bottomMargin: 26; spacing: 0
                    Text { text: window.currentPage; color: window.muted; font.pixelSize: 13; font.weight: Font.DemiBold; font.letterSpacing: 0.7 } Item { Layout.preferredHeight: 16 }
                    RowLayout { visible: window.currentPage === "Play"; Layout.fillWidth: true; Layout.fillHeight: true; spacing: Math.max(28, parent.width * 0.06)
                        Rectangle { Layout.preferredWidth: 560; Layout.fillWidth: true; Layout.fillHeight: true; Layout.maximumHeight: 460; Layout.alignment: Qt.AlignVCenter; radius: 6; color: window.surface; border.color: window.outline; border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 38; spacing: 0
                                Text { text: "SELECTED INSTALLATION"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1.1 } Item { Layout.preferredHeight: 30 }
                                Rectangle { Layout.preferredWidth: 58; Layout.preferredHeight: 58; radius: 6; color: "#2B3742"; Image { anchors.centerIn: parent; width: 34; height: 34; source: window.icon("grass_block_top.png"); smooth: false } } Item { Layout.preferredHeight: 20 }
                                Text { text: launcher.selectedInstallation.name; color: window.ink; font.pixelSize: 32; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Item { Layout.preferredHeight: 8 }
                                Text { text: launcher.selectedInstallation.loader + "  •  " + launcher.selectedInstallation.version; color: window.muted; font.pixelSize: 16 } Item { Layout.fillHeight: true }
                                Rectangle { id: playButton; property bool enabled: launcher.selectedInstallation.name !== "No installation selected" && !launcher.isLaunching; property bool hovered: false; Layout.fillWidth: true; Layout.preferredHeight: 68; radius: 6; color: enabled ? (hovered ? window.focus : window.primary) : "#42505B"; Behavior on color { ColorAnimation { duration: 140 } } Text { anchors.centerIn: parent; text: launcher.isLaunching ? "PREPARING…" : "PLAY"; color: window.bg; font.pixelSize: 20; font.weight: Font.Bold; font.letterSpacing: 1.3 } MouseArea { anchors.fill: parent; enabled: playButton.enabled; hoverEnabled: true; onEntered: playButton.hovered = true; onExited: playButton.hovered = false; onClicked: launcher.requestLaunch() } }
                            }
                        }
                        ColumnLayout { Layout.preferredWidth: 270; Layout.maximumWidth: 320; Layout.alignment: Qt.AlignVCenter; spacing: 0
                            Text { text: "Installation activity"; color: window.ink; font.pixelSize: 18; font.weight: Font.DemiBold } Item { Layout.preferredHeight: 22 } Text { text: "PLAYTIME"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1.0 } Item { Layout.preferredHeight: 6 } Text { text: launcher.selectedInstallation.playtime; color: window.ink; font.pixelSize: 29; font.weight: Font.DemiBold } Text { text: launcher.selectedInstallation.launches + " launches"; color: window.muted; font.pixelSize: 13 } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: window.outline; Layout.topMargin: 24; Layout.bottomMargin: 20 } Text { text: "LAST PLAYED"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1.0 } Item { Layout.preferredHeight: 6 } Text { text: launcher.selectedInstallation.lastPlayed; color: window.ink; font.pixelSize: 15; elide: Text.ElideRight; Layout.fillWidth: true } Item { Layout.preferredHeight: 26 } RowLayout { spacing: 9; Rectangle { Layout.preferredWidth: 10; Layout.preferredHeight: 10; radius: 5; color: launcher.isLaunching ? "#63B8FF" : window.primary } Text { text: launcher.launchStatus; color: window.muted; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true } } }
                    }
                    Flickable { visible: window.currentPage === "Modrinth" || window.currentPage === "Locker" || window.currentPage === "Accounts"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: width; contentHeight: content.implicitHeight + 16; boundsBehavior: Flickable.StopAtBounds; flickableDirection: Flickable.VerticalFlick
                        ColumnLayout { id: content; width: parent.width; spacing: 12
                            ColumnLayout { visible: false; Layout.preferredHeight: 0; Layout.maximumHeight: 0; Layout.fillWidth: true; spacing: 10
                                Text { text: "Choose an installation"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Select one to return to Play, or create a focused new setup."; color: window.muted; font.pixelSize: 14 }
                                RowLayout { Layout.fillWidth: true; spacing: 8
                                    Rectangle { Layout.preferredWidth: 190; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.installationNameDraft; onTextChanged: window.installationNameDraft = text; clip: true } }
                                    Rectangle { Layout.preferredWidth: 150; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.installationVersionDraft; onTextChanged: window.installationVersionDraft = text; clip: true } }
                                    Rectangle { Layout.preferredWidth: 84; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: window.installationLoaderDraft; color: window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: window.installationLoaderDraft = window.installationLoaderDraft === "Vanilla" ? "Fabric" : (window.installationLoaderDraft === "Fabric" ? "Forge" : "Vanilla") } }
                                    Rectangle { Layout.preferredWidth: 92; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "CREATE"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { launcher.createInstallation(window.installationNameDraft, window.installationVersionDraft, window.installationLoaderDraft); window.installationNameDraft = ""; window.installationVersionDraft = "latest-release" } } } Item { Layout.fillWidth: true }
                                }
                                Repeater { model: launcher.installations; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 72; radius: 6; color: window.surface; border.color: window.outline; border.width: 1; RowLayout { anchors.fill: parent; anchors.margins: 16; Rectangle { Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 6; color: "#2B3742"; Image { anchors.centerIn: parent; width: 24; height: 24; source: window.icon("grass_block_top.png"); smooth: false } } ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: modelData.name; color: window.ink; font.pixelSize: 15; font.weight: Font.DemiBold } Text { text: modelData.loader + "  •  " + modelData.version; color: window.muted; font.pixelSize: 12 } } Text { text: "Select"; color: window.primary; font.pixelSize: 12; font.weight: Font.DemiBold } } MouseArea { anchors.fill: parent; onClicked: { launcher.selectInstallation(modelData.index); window.navigate("Play") } } } }
                            }
                            ColumnLayout { visible: false; Layout.preferredHeight: 0; Layout.maximumHeight: 0; Layout.fillWidth: true; spacing: 10
                                Text { text: "Your modpacks"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Import a CurseForge export or launch a linked pack directly from Play."; color: window.muted; font.pixelSize: 14 }
                                RowLayout { Layout.fillWidth: true; spacing: 8; Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.curseForgeArchiveDraft; onTextChanged: window.curseForgeArchiveDraft = text; clip: true } } Rectangle { Layout.preferredWidth: 168; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "IMPORT CURSEFORGE"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.importCurseForge(window.curseForgeArchiveDraft) } } }
                                Text { text: launcher.modpackStatus; color: window.muted; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                                Repeater { model: launcher.modpacks; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 72; radius: 6; color: window.surface; border.color: window.outline; border.width: 1; RowLayout { anchors.fill: parent; anchors.margins: 16; Rectangle { Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 6; color: "#2B3742"; Image { anchors.centerIn: parent; width: 24; height: 24; source: window.icon("crafting_table_top.png"); smooth: false } } ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: modelData.name; color: window.ink; font.pixelSize: 15; font.weight: Font.DemiBold } Text { text: modelData.loader + "  •  " + modelData.version; color: window.muted; font.pixelSize: 12 } } Text { text: modelData.source; color: window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } } } }
                            }
                            ColumnLayout { visible: false; Layout.preferredHeight: 0; Layout.maximumHeight: 0; Layout.fillWidth: true; spacing: 10
                                Text { text: "Installed mods"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } RowLayout { Layout.fillWidth: true; Text { text: launcher.modsStatus; color: window.muted; font.pixelSize: 13; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 86; Layout.preferredHeight: 32; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: launcher.modsScanning ? "SCANNING" : "REFRESH"; color: window.muted; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.modsScanning; onClicked: launcher.requestMods() } } }
                                ListView { Layout.fillWidth: true; Layout.preferredHeight: 410; clip: true; spacing: 6; model: launcher.mods; delegate: Rectangle { required property var modelData; width: ListView.view.width; height: 58; radius: 6; color: window.surface; border.color: window.outline; border.width: 1; RowLayout { anchors.fill: parent; anchors.margins: 12; spacing: 10; Rectangle { Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 6; color: "#2B3742"; Image { anchors.centerIn: parent; width: 20; height: 20; source: window.icon("crafting_table_top.png"); smooth: false } } ColumnLayout { Layout.fillWidth: true; spacing: 2; Text { text: modelData.name; color: window.ink; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: modelData.id ? modelData.id + "  ·  " + modelData.file : modelData.file; color: window.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true } } Text { text: modelData.loader; color: window.muted; font.pixelSize: 11 } } } }
                            }
                            ColumnLayout {
                                visible: window.currentPage === "Modrinth"
                                Layout.fillWidth: true
                                spacing: 12
                                Text { text: "Modrinth"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold }
                                Text { text: "Browse compatible content for " + launcher.selectedInstallation.name + ". Downloads never block the launcher."; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                RowLayout {
                                    visible: false
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Repeater { model: ["Browse", "Installed"]; delegate: Rectangle { required property string modelData; property bool selected: window.modrinthTab === modelData; Layout.preferredWidth: modelData === "Installed" ? 90 : 78; Layout.preferredHeight: 34; radius: 6; color: selected ? window.primaryTint : window.raised; border.color: selected ? window.primary : window.outline; border.width: 1; Text { anchors.centerIn: parent; text: modelData; color: selected ? window.ink : window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: { window.modrinthTab = parent.modelData; if (parent.modelData === "Installed") launcher.requestMods() } } } }
                                    Item { Layout.fillWidth: true }
                                }
                                ColumnLayout {
                                    visible: window.modrinthTab === "Browse"
                                    Layout.fillWidth: true
                                    spacing: 10
                                    RowLayout { Layout.fillWidth: true; spacing: 8
                                        Repeater { model: ["mods", "textures", "shaders", "modpacks"]; delegate: Rectangle { required property string modelData; property bool selected: window.modrinthCategory === modelData; Layout.preferredWidth: modelData === "textures" ? 86 : 76; Layout.preferredHeight: 32; radius: 6; color: selected ? window.primaryTint : window.raised; border.color: selected ? window.primary : window.outline; border.width: 1; Text { anchors.centerIn: parent; text: modelData === "textures" ? "Textures" : modelData.charAt(0).toUpperCase() + modelData.slice(1); color: selected ? window.ink : window.muted; font.pixelSize: 11; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: { window.modrinthCategory = parent.modelData; launcher.searchModrinth(window.modrinthSearchDraft, window.modrinthCategory) } } } }
                                        Item { Layout.fillWidth: true }
                                    }
                                    RowLayout { Layout.fillWidth: true; spacing: 8
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: modrinthSearchInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.modrinthSearchDraft; onTextChanged: window.modrinthSearchDraft = text; onAccepted: launcher.searchModrinth(text, window.modrinthCategory); clip: true } }
                                        Rectangle { property bool hovered: false; Layout.preferredWidth: 92; Layout.preferredHeight: 40; radius: 6; color: launcher.modrinthBusy ? "#42505B" : (hovered ? window.focus : window.primary); Behavior on color { ColorAnimation { duration: 140 } } Text { anchors.centerIn: parent; text: launcher.modrinthBusy ? "SEARCHING" : "SEARCH"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.modrinthBusy; hoverEnabled: true; onEntered: parent.hovered = true; onExited: parent.hovered = false; onClicked: launcher.searchModrinth(modrinthSearchInput.text, window.modrinthCategory) } }
                                    }
                                    Text { text: launcher.modrinthStatus; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                    ColumnLayout { visible: launcher.modrinthBusy && launcher.modrinthResults.length === 0; Layout.fillWidth: true; spacing: 8
                                        Repeater { model: 4; delegate: Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 82; radius: 6; color: window.raised; opacity: 0.48; SequentialAnimation on opacity { running: parent.parent.visible; loops: Animation.Infinite; NumberAnimation { to: 0.78; duration: 760 } NumberAnimation { to: 0.38; duration: 760 } } RowLayout { anchors.fill: parent; anchors.margins: 12; spacing: 12; Rectangle { Layout.preferredWidth: 48; Layout.preferredHeight: 48; radius: 6; color: "#33414D" } ColumnLayout { Layout.fillWidth: true; spacing: 8; Rectangle { Layout.fillWidth: true; Layout.preferredWidth: Math.min(260, parent.width * 0.55); Layout.preferredHeight: 12; radius: 3; color: "#3A4753" } Rectangle { Layout.fillWidth: true; Layout.preferredWidth: Math.min(420, parent.width * 0.82); Layout.preferredHeight: 9; radius: 3; color: "#33414D" } } Rectangle { Layout.preferredWidth: 78; Layout.preferredHeight: 32; radius: 6; color: "#3A4753" } } } }
                                    }
                                    Repeater { model: launcher.modrinthResults; delegate: Rectangle { objectName: "modrinthResultCard"; required property var modelData; property bool hovered: false; Layout.fillWidth: true; Layout.preferredHeight: 82; radius: 6; color: hovered ? window.raised : window.surface; Behavior on color { ColorAnimation { duration: 140 } } border.color: window.outline; border.width: 1
                                        MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.hovered = true; onExited: parent.hovered = false; onClicked: { launcher.openModrinthDetails(modelData); window.modrinthDetailsOpen = true } }
                                        RowLayout { anchors.fill: parent; anchors.margins: 12; spacing: 12
                                            Rectangle { Layout.preferredWidth: 48; Layout.preferredHeight: 48; radius: 6; color: "#2B3742"; clip: true; Image { anchors.fill: parent; source: modelData.iconUrl; fillMode: Image.PreserveAspectCrop; asynchronous: true } }
                                            ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: modelData.title; color: window.ink; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: modelData.description; color: window.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: modelData.author + " · " + modelData.downloads.toLocaleString() + " downloads"; color: window.muted; font.pixelSize: 10 } }
                                            Rectangle { objectName: "modrinthAddButton"; visible: !modelData.installed; property bool hovered: false; Layout.preferredWidth: modelData.projectType === "modpack" ? 92 : 78; Layout.preferredHeight: 32; radius: 6; color: launcher.modrinthBusy ? "#42505B" : (hovered ? window.focus : window.primary); Behavior on color { ColorAnimation { duration: 140 } } Text { anchors.centerIn: parent; text: modelData.projectType === "modpack" ? "INSTALL" : "ADD"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.modrinthBusy; hoverEnabled: true; onEntered: parent.hovered = true; onExited: parent.hovered = false; onClicked: launcher.installModrinth(modelData, window.modrinthCategory) } }
                                        }
                                    } }
                                }
                                ColumnLayout {
                                    visible: window.modrinthTab === "Installed"
                                    Layout.fillWidth: true
                                    spacing: 10
                                    RowLayout { Layout.fillWidth: true; Text { text: "Installed mods"; color: window.ink; font.pixelSize: 18; font.weight: Font.DemiBold; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 86; Layout.preferredHeight: 32; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: launcher.modsScanning ? "SCANNING" : "REFRESH"; color: window.muted; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.modsScanning; onClicked: launcher.requestMods() } } }
                                    Text { text: launcher.modsStatus; color: window.muted; font.pixelSize: 12 }
                                    Repeater { model: launcher.mods; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 56; radius: 6; color: window.surface; border.color: window.outline; border.width: 1; RowLayout { anchors.fill: parent; anchors.margins: 11; spacing: 10; Image { Layout.preferredWidth: 22; Layout.preferredHeight: 22; source: window.icon("crafting_table_top.png"); smooth: false } ColumnLayout { Layout.fillWidth: true; spacing: 1; Text { text: modelData.name; color: window.ink; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: modelData.id ? modelData.id + " · " + modelData.file : modelData.file; color: window.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true } } Text { text: modelData.loader; color: window.muted; font.pixelSize: 11 } } } }
                                }
                            }
                            ColumnLayout { visible: window.currentPage === "Locker"; Layout.fillWidth: true; spacing: 10
                                Text { text: "Locker"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Keep your appearance and launcher space personal."; color: window.muted; font.pixelSize: 14 }
                                RowLayout { spacing: 8; Repeater { model: ["Skin", "Background"]; delegate: Rectangle { required property string modelData; property bool selected: modelData === window.lockerTab; Layout.preferredWidth: modelData === "Background" ? 116 : 72; Layout.preferredHeight: 34; radius: 6; color: selected ? window.primaryTint : window.raised; border.color: selected ? window.primary : window.outline; border.width: 1; Text { anchors.centerIn: parent; text: modelData; color: selected ? window.ink : window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: window.lockerTab = parent.modelData } } } }
                                ColumnLayout { visible: false; Layout.fillWidth: true; spacing: 10; Text { text: "Offline skin"; color: window.ink; font.pixelSize: 17; font.weight: Font.DemiBold } Text { text: "Paste a local PNG path. It is served only to your own game session through offline injection."; color: window.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true } RowLayout { Layout.fillWidth: true; spacing: 8; Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.skinDraft; onTextChanged: window.skinDraft = text; clip: true } } Rectangle { Layout.preferredWidth: 104; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "SET SKIN"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.setOfflineSkin(window.skinDraft) } } } Text { text: launcher.accountStatus; color: window.primary; font.pixelSize: 12 } }
                                ColumnLayout { visible: window.lockerTab === "Background"; Layout.fillWidth: true; spacing: 8; Text { text: "Launcher background"; color: window.ink; font.pixelSize: 17; font.weight: Font.DemiBold } Text { text: "Choose from your existing wallpaper library."; color: window.muted; font.pixelSize: 12 } Repeater { model: launcher.wallpapers; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 64; radius: 6; color: modelData.selected ? window.primaryTint : window.surface; border.color: modelData.selected ? window.primary : window.outline; border.width: 1; RowLayout { anchors.fill: parent; anchors.margins: 10; spacing: 12; Image { Layout.preferredWidth: 72; Layout.preferredHeight: 42; source: modelData.url; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: true } Text { text: modelData.name; color: window.ink; font.pixelSize: 13; font.weight: Font.Medium; Layout.fillWidth: true } Text { text: modelData.selected ? "Selected" : "Use"; color: modelData.selected ? window.primary : window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } } MouseArea { anchors.fill: parent; onClicked: launcher.selectWallpaper(modelData.path) } } } }
                            }
                            ColumnLayout {
                                visible: window.currentPage === "Locker" && window.lockerTab === "Skin"
                                Layout.fillWidth: true
                                spacing: 12
                                Text { text: "Skin preview"; color: window.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 28
                                    Rectangle {
                                        Layout.preferredWidth: 270
                                        Layout.preferredHeight: 350
                                        radius: 6
                                        color: window.surface
                                        border.color: window.outline
                                        border.width: 1
                                        Image { anchors.centerIn: parent; width: Math.min(parent.width - 32, implicitWidth); height: Math.min(parent.height - 28, implicitHeight); source: launcher.skinPreviewUrl; fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false }
                                        Text { anchors.centerIn: parent; visible: launcher.skinPreviewUrl === ""; text: "No skin preview"; color: window.muted; font.pixelSize: 13 }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 10
                                        Text { text: "Offline skin"; color: window.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
                                        Text { text: "Rendered with the same skinpy isometric renderer as the previous launcher. The skin is served only to your local game session."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        RowLayout { Layout.fillWidth: true; Text { text: "Inject offline skin at launch"; color: window.ink; font.pixelSize: 12; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 42; Layout.preferredHeight: 24; radius: 12; color: launcher.offlineSkinInjectionEnabled ? window.primary : "#46535F"; Rectangle { width: 16; height: 16; radius: 8; anchors.verticalCenter: parent.verticalCenter; x: launcher.offlineSkinInjectionEnabled ? 22 : 4; color: launcher.offlineSkinInjectionEnabled ? window.bg : window.ink; Behavior on x { NumberAnimation { duration: 150 } } } MouseArea { anchors.fill: parent; onClicked: launcher.setOfflineSkinInjectionEnabled(!launcher.offlineSkinInjectionEnabled) } } }
                                        Text { text: "SKIN PNG PATH"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.8 }
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                            TextInput { id: lockerSkinPath; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.skinDraft; onTextChanged: window.skinDraft = text; clip: true }
                                        }
                                        RowLayout { spacing: 8
                                            Rectangle { Layout.preferredWidth: 104; Layout.preferredHeight: 38; radius: 6; color: window.primary
                                                Text { anchors.centerIn: parent; text: "SET SKIN"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold }
                                                MouseArea { anchors.fill: parent; onClicked: launcher.setOfflineSkin(lockerSkinPath.text) }
                                            }
                                            Rectangle { Layout.preferredWidth: 98; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                                Text { anchors.centerIn: parent; text: "REFRESH"; color: window.muted; font.pixelSize: 11; font.weight: Font.Bold }
                                                MouseArea { anchors.fill: parent; onClicked: launcher.requestSkinPreview() }
                                            }
                                        }
                                        Text { text: launcher.skinPreviewStatus; color: launcher.skinPreviewUrl === "" ? window.muted : window.primary; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        Item { Layout.fillHeight: true }
                                        Text { text: launcher.accountStatus; color: window.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    }
                                }
                            }
                            ColumnLayout { visible: window.currentPage === "Accounts"; Layout.fillWidth: true; spacing: 10
                                Text { text: "Account manager"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Add, switch, or remove accounts without leaving the launcher."; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                RowLayout {
                                    visible: false
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Repeater {
                                        model: ["Offline", "Microsoft", "Ely.by"]
                                        delegate: Rectangle {
                                            required property string modelData
                                            Layout.preferredWidth: modelData === "Microsoft" ? 108 : 84
                                            Layout.preferredHeight: 34
                                            radius: 6
                                            property bool selected: window.accountProvider === modelData
                                            color: selected ? window.primaryTint : window.raised
                                            border.color: selected ? window.primary : window.outline
                                            border.width: 1
                                            Text { anchors.centerIn: parent; text: parent.modelData; color: parent.selected ? window.ink : window.muted; font.pixelSize: 12; font.weight: Font.DemiBold }
                                            MouseArea { anchors.fill: parent; onClicked: window.accountProvider = parent.modelData }
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                ColumnLayout {
                                    visible: false
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Text { text: "Microsoft account"; color: window.ink; font.pixelSize: 17; font.weight: Font.DemiBold }
                                    Text { text: "Sign in securely with Microsoft’s device flow. Your browser handles credentials; the launcher only receives your Minecraft session."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    RowLayout {
                                        spacing: 8
                                        Rectangle { Layout.preferredWidth: 124; Layout.preferredHeight: 38; radius: 6; color: launcher.accountAuth.busy ? "#42505B" : window.primary
                                            Text { anchors.centerIn: parent; text: launcher.accountAuth.busy ? "WAITING…" : "START SIGN-IN"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold }
                                            MouseArea { anchors.fill: parent; enabled: !launcher.accountAuth.busy; onClicked: launcher.startMicrosoftLogin() }
                                        }
                                        Rectangle { visible: launcher.accountAuth.deviceCode !== ""; Layout.preferredWidth: 148; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                            Text { anchors.centerIn: parent; text: "OPEN SIGN-IN PAGE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold }
                                            MouseArea { anchors.fill: parent; onClicked: Qt.openUrlExternally(launcher.accountAuth.verificationUrl) }
                                        }
                                        Rectangle { visible: launcher.accountAuth.busy; Layout.preferredWidth: 76; Layout.preferredHeight: 38; radius: 6; color: "transparent"; border.color: window.error; border.width: 1
                                            Text { anchors.centerIn: parent; text: "CANCEL"; color: window.error; font.pixelSize: 10; font.weight: Font.Bold }
                                            MouseArea { anchors.fill: parent; onClicked: launcher.cancelMicrosoftLogin() }
                                        }
                                    }
                                    Text { visible: launcher.accountAuth.deviceCode !== ""; text: "CODE  " + launcher.accountAuth.deviceCode; color: window.primary; font.pixelSize: 20; font.weight: Font.Bold; font.letterSpacing: 1.5 }
                                }
                                ColumnLayout {
                                    visible: false
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Text { text: "Ely.by account"; color: window.ink; font.pixelSize: 17; font.weight: Font.DemiBold }
                                    Text { text: "Sign in with your Ely.by username/email and password. Your password is used only for this request and is never saved."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                            TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.elyUsernameDraft; onTextChanged: window.elyUsernameDraft = text; clip: true }
                                        }
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                            TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.elyPasswordDraft; onTextChanged: window.elyPasswordDraft = text; echoMode: TextInput.Password; clip: true }
                                        }
                                        Rectangle { Layout.preferredWidth: 82; Layout.preferredHeight: 38; radius: 6; color: launcher.accountAuth.busy ? "#42505B" : window.primary
                                            Text { anchors.centerIn: parent; text: "SIGN IN"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold }
                                            MouseArea { anchors.fill: parent; enabled: !launcher.accountAuth.busy; onClicked: { launcher.loginElyBy(window.elyUsernameDraft, window.elyPasswordDraft); window.elyPasswordDraft = "" } }
                                        }
                                    }
                                }
                                RowLayout { visible: false; Layout.fillWidth: true; spacing: 8; Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.profileDraft; onTextChanged: window.profileDraft = text; clip: true } } Rectangle { Layout.preferredWidth: 124; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "ADD OFFLINE"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { launcher.createOfflineProfile(window.profileDraft); window.profileDraft = "" } } } } Text { text: launcher.accountStatus; color: window.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Repeater { model: launcher.profiles; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 68; radius: 6; color: modelData.selected ? window.primaryTint : window.surface; border.color: modelData.selected ? window.primary : window.outline; border.width: 1; RowLayout { anchors.fill: parent; anchors.margins: 12; spacing: 10; Rectangle { Layout.preferredWidth: 40; Layout.preferredHeight: 40; radius: 6; color: "#2B3742"; clip: true; Image { anchors.fill: parent; visible: modelData.avatarUrl !== ""; source: modelData.avatarUrl; sourceClipRect: Qt.rect(8, 8, 8, 8); fillMode: Image.Stretch; smooth: false } Text { anchors.centerIn: parent; visible: modelData.avatarUrl === ""; text: modelData.name.slice(0, 1).toUpperCase(); color: window.ink; font.pixelSize: 16; font.weight: Font.DemiBold } } ColumnLayout { Layout.fillWidth: true; spacing: 2; Text { text: modelData.name; color: window.ink; font.pixelSize: 14; font.weight: Font.DemiBold } Text { text: modelData.type === "offline" ? "Offline account" : modelData.type; color: window.muted; font.pixelSize: 12 } } Text { text: modelData.selected ? "ACTIVE" : "SWITCH"; color: modelData.selected ? window.primary : window.muted; font.pixelSize: 11; font.weight: Font.DemiBold } Rectangle { Layout.preferredWidth: 62; Layout.preferredHeight: 28; radius: 6; color: "transparent"; border.color: window.error; border.width: 1; Text { anchors.centerIn: parent; text: "DELETE"; color: window.error; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.deleteProfile(modelData.index) } } } MouseArea { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.rightMargin: 74; onClicked: launcher.selectProfile(modelData.index) } } }
                            }
                            Rectangle { objectName: "addAccountButton"; visible: window.currentPage === "Accounts"; Layout.fillWidth: true; Layout.preferredHeight: 42; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                Text { anchors.centerIn: parent; text: "ADD ACCOUNT"; color: window.ink; font.pixelSize: 11; font.weight: Font.Bold }
                                MouseArea { anchors.fill: parent; onClicked: { window.accountProvider = ""; window.profileDraft = ""; window.elyUsernameDraft = ""; window.elyPasswordDraft = ""; window.openAccountModal() } }
                            }
                            ColumnLayout { visible: false; Layout.preferredHeight: 0; Layout.maximumHeight: 0; Layout.fillWidth: true; spacing: 10
                                Text { text: "Settings"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Performance, game files, and launcher behaviour."; color: window.muted; font.pixelSize: 14 } Text { text: "MINECRAFT DIRECTORY"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.8 }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: minecraftDirectoryInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: launcher.settings.minecraftDirectory; clip: true } }
                                RowLayout { Layout.fillWidth: true; spacing: 12; ColumnLayout { Layout.fillWidth: true; spacing: 5; Text { text: "MEMORY (MB)"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: ramInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; inputMethodHints: Qt.ImhDigitsOnly; text: launcher.settings.ramAllocation; clip: true } } } ColumnLayout { Layout.fillWidth: true; spacing: 5; Text { text: "JAVA ARGUMENTS"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: javaArgumentsInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: launcher.settings.javaArguments; clip: true } } } }
                                Repeater { model: [ {"label": "Discord Rich Presence", "key": "rpc"}, {"label": "Check for launcher updates", "key": "updates"}, {"label": "Custom Windows title bar", "key": "titlebar"}, {"label": "Neo dark interface", "key": "neo"} ]; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 44; radius: 6; color: window.surface; border.color: window.outline; border.width: 1; Text { anchors.left: parent.left; anchors.leftMargin: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: window.ink; font.pixelSize: 13 } Rectangle { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 22; radius: 11; property bool on: modelData.key === "rpc" ? window.rpcDraft : (modelData.key === "updates" ? window.updatesDraft : (modelData.key === "titlebar" ? window.titlebarDraft : window.neoDraft)); color: on ? window.primary : "#46535F"; Rectangle { width: 16; height: 16; radius: 8; anchors.verticalCenter: parent.verticalCenter; x: parent.on ? 18 : 4; color: parent.on ? window.bg : window.ink; Behavior on x { NumberAnimation { duration: 160 } } } MouseArea { anchors.fill: parent; onClicked: { if (modelData.key === "rpc") window.rpcDraft = !window.rpcDraft; else if (modelData.key === "updates") window.updatesDraft = !window.updatesDraft; else if (modelData.key === "titlebar") window.titlebarDraft = !window.titlebarDraft; else window.neoDraft = !window.neoDraft } } } } }
                                RowLayout { Layout.fillWidth: true; spacing: 8; Text { text: "ACCENT"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold } Rectangle { Layout.preferredWidth: 108; Layout.preferredHeight: 32; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: window.accentDraft; color: window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: window.accentDraft = window.accentDraft === "Green" ? "Blue" : (window.accentDraft === "Blue" ? "Orange" : (window.accentDraft === "Orange" ? "Purple" : (window.accentDraft === "Purple" ? "Red" : "Green"))) } } Item { Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 102; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "SAVE"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.saveSettings(minecraftDirectoryInput.text, Number(ramInput.text), javaArgumentsInput.text, window.rpcDraft, window.updatesDraft, window.titlebarDraft, window.neoDraft, window.accentDraft) } } }
                            }
                        }
                    }
                    Flickable {
                        visible: window.currentPage === "Installations" || window.currentPage === "Modpacks" || window.currentPage === "Settings"
                        Layout.fillWidth: true; Layout.fillHeight: true
                        clip: true; contentWidth: width; contentHeight: managerContent.implicitHeight + 16
                        boundsBehavior: Flickable.StopAtBounds; flickableDirection: Flickable.VerticalFlick
                        ColumnLayout {
                            id: managerContent
                            width: parent.width
                            spacing: 14

                            ColumnLayout {
                                id: installationManager
                                visible: false
                                Layout.preferredWidth: 0
                                Layout.maximumWidth: 0
                                Layout.preferredHeight: 0
                                Layout.maximumHeight: 0
                                Layout.fillWidth: true
                                spacing: 10
                                property var edit: launcher.installations[window.installationEditorIndex] || ({})
                                Text { text: "Installations"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold }
                                Text { text: "Create, tune, and select a launch target without leaving the page."; color: window.muted; font.pixelSize: 14 }
                                Text { text: "NEW INSTALLATION  ·  NAME  /  MINECRAFT VERSION  /  LOADER"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.7 }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    Rectangle { Layout.preferredWidth: 190; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                        TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; text: window.installationNameDraft; onTextChanged: window.installationNameDraft = text; clip: true }
                                    }
                                    Rectangle { Layout.preferredWidth: 140; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                        TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; text: window.installationVersionDraft; onTextChanged: window.installationVersionDraft = text; clip: true }
                                    }
                                    Rectangle { Layout.preferredWidth: 88; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                                        Text { anchors.centerIn: parent; text: window.installationLoaderDraft; color: window.muted; font.pixelSize: 12; font.weight: Font.DemiBold }
                                        MouseArea { anchors.fill: parent; onClicked: window.installationLoaderDraft = window.installationLoaderDraft === "Vanilla" ? "Fabric" : (window.installationLoaderDraft === "Fabric" ? "Forge" : "Vanilla") }
                                    }
                                    Rectangle { Layout.preferredWidth: 92; Layout.preferredHeight: 38; radius: 6; color: window.primary
                                        Text { anchors.centerIn: parent; text: "CREATE"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold }
                                        MouseArea { anchors.fill: parent; onClicked: { launcher.createInstallation(window.installationNameDraft, window.installationVersionDraft, window.installationLoaderDraft); window.installationNameDraft = "" } }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: window.outline }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 18
                                    ColumnLayout {
                                        Layout.preferredWidth: 300; spacing: 6
                                        Repeater {
                                            model: launcher.installations
                                            delegate: Rectangle {
                                                required property var modelData
                                                Layout.fillWidth: true; Layout.preferredHeight: 64; radius: 6
                                                color: modelData.index === window.installationEditorIndex ? window.primaryTint : window.surface
                                                border.color: modelData.index === window.installationEditorIndex ? window.primary : window.outline; border.width: 1
                                                RowLayout { anchors.fill: parent; anchors.margins: 12; spacing: 9
                                                    Image { Layout.preferredWidth: 26; Layout.preferredHeight: 26; source: window.icon("grass_block_top.png"); smooth: false }
                                                    ColumnLayout { Layout.fillWidth: true; spacing: 2
                                                        Text { text: modelData.name; color: window.ink; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                                        Text { text: modelData.loader + " · " + modelData.version; color: window.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                                                    }
                                                }
                                                MouseArea { anchors.fill: parent; onClicked: { window.installationEditorIndex = modelData.index; window.installationForceUpdateDraft = modelData.forceUpdate; window.installationDeleteArmed = false; launcher.selectInstallation(modelData.index) } }
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 10
                                        Text { text: installationManager.edit.name || "Select an installation"; color: window.ink; font.pixelSize: 20; font.weight: Font.DemiBold }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            ColumnLayout { Layout.fillWidth: true; Text { text: "NAME"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: editInstallationName; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: installationManager.edit.name || "" } } }
                                            ColumnLayout { Layout.fillWidth: true; Text { text: "MINECRAFT VERSION"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: editInstallationVersion; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: installationManager.edit.version || "" } } }
                                        }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            ColumnLayout { Layout.fillWidth: true; Text { text: "LOADER"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { id: editInstallationLoader; Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; property string value: installationManager.edit.loader || "Vanilla"; Text { anchors.centerIn: parent; text: parent.value; color: window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: parent.value = parent.value === "Vanilla" ? "Fabric" : (parent.value === "Fabric" ? "Forge" : "Vanilla") } } }
                                            ColumnLayout { Layout.fillWidth: true; Text { text: "CUSTOM JAVA (OPTIONAL)"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: editInstallationJava; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: installationManager.edit.java || ""; clip: true } } }
                                        }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            ColumnLayout { Layout.fillWidth: true; Text { text: "WIDTH (OPTIONAL)"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 36; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: editWidth; anchors.fill: parent; anchors.margins: 10; color: window.ink; inputMethodHints: Qt.ImhDigitsOnly; text: installationManager.edit.resolutionWidth || "" } } }
                                            ColumnLayout { Layout.fillWidth: true; Text { text: "HEIGHT (OPTIONAL)"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 36; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: editHeight; anchors.fill: parent; anchors.margins: 10; color: window.ink; inputMethodHints: Qt.ImhDigitsOnly; text: installationManager.edit.resolutionHeight || "" } } }
                                            Rectangle { Layout.preferredWidth: 126; Layout.preferredHeight: 36; radius: 6; color: window.installationForceUpdateDraft ? "#392D1D" : window.raised; border.color: window.installationForceUpdateDraft ? "#FFAE57" : window.outline; border.width: 1; Text { anchors.centerIn: parent; text: window.installationForceUpdateDraft ? "FORCE UPDATE" : "NORMAL UPDATE"; color: window.muted; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: window.installationForceUpdateDraft = !window.installationForceUpdateDraft } }
                                        }
                                        Text { text: launcher.installationStatus; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true }
                                        RowLayout { Layout.fillWidth: true
                                            Rectangle { Layout.preferredWidth: 100; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "SAVE"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.updateInstallation(window.installationEditorIndex, editInstallationName.text, editInstallationVersion.text, editInstallationLoader.value, editInstallationJava.text, editWidth.text, editHeight.text, window.installationForceUpdateDraft) } }
                                            Item { Layout.fillWidth: true }
                                            Rectangle { Layout.preferredWidth: 104; Layout.preferredHeight: 38; radius: 6; color: "transparent"; border.color: window.error; border.width: 1; Text { anchors.centerIn: parent; text: window.installationDeleteArmed ? "CONFIRM" : "DELETE"; color: window.error; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { if (window.installationDeleteArmed) { launcher.deleteInstallation(window.installationEditorIndex); window.installationEditorIndex = launcher.selectedIndex; window.installationDeleteArmed = false } else window.installationDeleteArmed = true } } }
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                visible: false
                                Layout.preferredWidth: 0
                                Layout.maximumWidth: 0
                                Layout.preferredHeight: 0
                                Layout.maximumHeight: 0
                                Layout.fillWidth: true; spacing: 10
                                Text { text: "Modpacks"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold }
                                Text { text: "Create a local pack, import CurseForge, then link it to the exact installation it should launch with."; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Text { text: "NEW LOCAL PACK  ·  NAME  /  MINECRAFT VERSION  /  LOADER"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.7 }
                                RowLayout { Layout.fillWidth: true; spacing: 8
                                    Rectangle { Layout.preferredWidth: 190; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: newPackName; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: ""; clip: true } }
                                    Rectangle { Layout.preferredWidth: 140; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: newPackVersion; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: "1.21.1"; clip: true } }
                                    Rectangle { id: newPackLoader; property string value: "Fabric"; Layout.preferredWidth: 88; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: parent.value; color: window.muted; font.pixelSize: 12; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; onClicked: newPackLoader.value = newPackLoader.value === "Fabric" ? "Forge" : (newPackLoader.value === "Forge" ? "Vanilla" : "Fabric") } }
                                    Rectangle { Layout.preferredWidth: 110; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "NEW PACK"; color: window.bg; font.pixelSize: 11; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.createModpack(newPackName.text, newPackVersion.text, newPackLoader.value) } }
                                }
                                RowLayout { Layout.fillWidth: true; spacing: 8
                                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: curseForgePath; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: window.curseForgeArchiveDraft; onTextChanged: window.curseForgeArchiveDraft = text; clip: true } }
                                    Rectangle { Layout.preferredWidth: 168; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.primary; border.width: 1; Text { anchors.centerIn: parent; text: "IMPORT CURSEFORGE"; color: window.primary; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.importCurseForge(curseForgePath.text) } }
                                }
                                Text { text: launcher.modpackStatus; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                Repeater {
                                    model: launcher.modpacks
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true; Layout.preferredHeight: 82; radius: 6
                                        color: modelData.index === window.modpackEditorIndex ? window.primaryTint : window.surface
                                        border.color: modelData.index === window.modpackEditorIndex ? window.primary : window.outline; border.width: 1
                                        RowLayout { anchors.fill: parent; anchors.margins: 14; spacing: 10
                                            Image { Layout.preferredWidth: 30; Layout.preferredHeight: 30; source: window.icon("crafting_table_top.png"); smooth: false }
                                            ColumnLayout { Layout.fillWidth: true; spacing: 3
                                                Text { text: modelData.name; color: window.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                                                Text { text: modelData.loader + " · " + modelData.version + " · " + modelData.modCount + " mods"; color: window.muted; font.pixelSize: 11 }
                                                Text { text: "Launch link: " + modelData.linkedInstallationName; color: modelData.linkedInstallationId ? window.primary : window.error; font.pixelSize: 11 }
                                            }
                                            Rectangle { Layout.preferredWidth: 132; Layout.preferredHeight: 30; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "LINK SELECTED"; color: window.muted; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.linkModpack(modelData.index, launcher.selectedIndex) } }
                                            Rectangle { Layout.preferredWidth: 64; Layout.preferredHeight: 30; radius: 6; color: "transparent"; border.color: window.error; border.width: 1; Text { anchors.centerIn: parent; text: window.modpackDeleteArmed && window.modpackEditorIndex === modelData.index ? "CONFIRM" : "DELETE"; color: window.error; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { if (window.modpackDeleteArmed && window.modpackEditorIndex === modelData.index) { launcher.deleteModpack(modelData.index); window.modpackEditorIndex = 0; window.modpackDeleteArmed = false } else { window.modpackEditorIndex = modelData.index; window.modpackDeleteArmed = true } } } }
                                        }
                                        MouseArea { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.rightMargin: 216; onClicked: { window.modpackEditorIndex = modelData.index; window.modpackDeleteArmed = false } }
                                    }
                                }
                            }

                            ColumnLayout {
                                visible: window.currentPage === "Installations"
                                Layout.fillWidth: true
                                Layout.preferredWidth: parent.width
                                Layout.maximumWidth: parent.width
                                spacing: 12
                                RowLayout { Layout.fillWidth: true
                                    ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: "Installations"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Choose a launch target or open one focused editor at a time."; color: window.muted; font.pixelSize: 14 } }
                                    Rectangle { Layout.preferredWidth: 130; Layout.preferredHeight: 40; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "NEW INSTALL"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { window.installationModalIndex = -1; window.installationModalName = ""; window.installationModalVersion = "latest-release"; window.installationModalLoader = "Vanilla"; window.installationModalJava = ""; window.installationModalWidth = ""; window.installationModalHeight = ""; window.installationModalForceUpdate = false; window.installationDeleteArmed = false; window.installationModalOpen = true } }
                                    }
                                }
                                Text { text: launcher.installationStatus; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true }
                                Repeater { model: launcher.installations; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 74; radius: 6; color: modelData.selected ? window.primaryTint : window.surface; border.color: modelData.selected ? window.primary : window.outline; border.width: 1
                                    RowLayout { anchors.fill: parent; anchors.margins: 13; spacing: 12
                                        Image { Layout.preferredWidth: 30; Layout.preferredHeight: 30; source: window.icon("grass_block_top.png"); smooth: false }
                                        ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: modelData.name; color: window.ink; font.pixelSize: 14; font.weight: Font.DemiBold } Text { text: modelData.loader + " · " + modelData.version + " · " + modelData.resolution; color: window.muted; font.pixelSize: 11 } }
                                        RowLayout { Layout.preferredWidth: 140; Layout.alignment: Qt.AlignRight | Qt.AlignVCenter; spacing: 6
                                            Rectangle { Layout.preferredWidth: 76; Layout.preferredHeight: 32; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: modelData.selected ? "SELECTED" : "SELECT"; color: modelData.selected ? window.primary : window.muted; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.selectInstallation(modelData.index) } }
                                            Rectangle { Layout.preferredWidth: 58; Layout.preferredHeight: 32; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "EDIT"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { window.installationModalIndex = modelData.index; window.installationModalName = modelData.name; window.installationModalVersion = modelData.version; window.installationModalLoader = modelData.loader; window.installationModalJava = modelData.java; var split = modelData.resolution.split(" × "); window.installationModalWidth = split.length === 2 ? split[0] : ""; window.installationModalHeight = split.length === 2 ? split[1] : ""; window.installationModalForceUpdate = modelData.forceUpdate; window.installationDeleteArmed = false; window.installationModalOpen = true } }
                                            }
                                        }
                                    }
                                } }
                            }

                            ColumnLayout {
                                visible: window.currentPage === "Modpacks"
                                Layout.fillWidth: true
                                Layout.preferredWidth: parent.width
                                Layout.maximumWidth: parent.width
                                spacing: 12
                                RowLayout { Layout.fillWidth: true
                                    ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: "Modpacks"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold } Text { text: "Pack files stay isolated until launch, then sync automatically."; color: window.muted; font.pixelSize: 14 } }
                                    Rectangle { Layout.preferredWidth: 116; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "IMPORT PACK"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { window.modpackModalMode = "import"; window.modpackModalPath = ""; window.modpackModalOpen = true } }
                                    }
                                    Rectangle { Layout.preferredWidth: 104; Layout.preferredHeight: 40; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "NEW PACK"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { window.modpackModalMode = "create"; window.modpackModalName = ""; window.modpackModalVersion = "1.21.1"; window.modpackModalLoader = "Fabric"; window.modpackModalOpen = true } }
                                    }
                                }
                                Text { text: launcher.modpackStatus; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true }
                                Repeater { model: launcher.modpacks; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 82; radius: 6; color: window.surface; border.color: window.outline; border.width: 1
                                    RowLayout { anchors.fill: parent; anchors.margins: 13; spacing: 12
                                        Image { Layout.preferredWidth: 32; Layout.preferredHeight: 32; source: window.icon("crafting_table_top.png"); smooth: false }
                                        ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: modelData.name; color: window.ink; font.pixelSize: 14; font.weight: Font.DemiBold } Text { text: modelData.loader + " · " + modelData.version + " · " + modelData.modCount + " mods"; color: window.muted; font.pixelSize: 11 } Text { text: modelData.linkedInstallationId ? "Linked to " + modelData.linkedInstallationName : "Not linked"; color: modelData.linkedInstallationId ? window.primary : window.error; font.pixelSize: 11 } }
                                        RowLayout { Layout.preferredWidth: 68; Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                                            Rectangle { Layout.preferredWidth: 68; Layout.preferredHeight: 32; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "MANAGE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { window.modpackModalMode = "manage"; window.modpackModalIndex = modelData.index; window.modpackLinkIndex = launcher.selectedIndex; window.modpackDeleteArmed = false; window.modpackModalOpen = true } }
                                            }
                                        }
                                    }
                                } }
                            }

                            ColumnLayout {
                                visible: window.currentPage === "Settings"
                                Layout.fillWidth: true; spacing: 10
                                Text { text: "Settings"; color: window.ink; font.pixelSize: 28; font.weight: Font.DemiBold }
                                Text { text: "These settings persist immediately and your launch preferences are used on the next Play."; color: window.muted; font.pixelSize: 14 }
                                Text { text: "MINECRAFT DIRECTORY"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.8 }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: settingsDirectory; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: launcher.settings.minecraftDirectory; clip: true } }
                                RowLayout { Layout.fillWidth: true; spacing: 14
                                    ColumnLayout { Layout.fillWidth: true; spacing: 7
                                        RowLayout { Layout.fillWidth: true; Text { text: "MEMORY"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Item { Layout.fillWidth: true } Text { text: window.ramDraft + " MB"; color: window.primary; font.pixelSize: 12; font.weight: Font.DemiBold } }
                                        Rectangle { id: ramTrack; Layout.fillWidth: true; Layout.preferredHeight: 28; color: "transparent"; property real ratio: (window.ramDraft - 512) / (16384 - 512)
                                            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 5; radius: 3; color: "#46535F" }
                                            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width * parent.ratio; height: 5; radius: 3; color: window.primary }
                                            Rectangle { anchors.verticalCenter: parent.verticalCenter; x: Math.max(0, Math.min(parent.width - width, parent.width * parent.ratio - width / 2)); width: 18; height: 18; radius: 9; color: window.primary }
                                            function setRam(position) { var raw = 512 + (Math.max(0, Math.min(width, position)) / width) * (16384 - 512); window.ramDraft = Math.max(512, Math.min(16384, Math.round(raw / 256) * 256)); settingsRamInput.text = window.ramDraft }
                                            MouseArea { anchors.fill: parent; onPressed: ramTrack.setRam(mouse.x); onPositionChanged: if (pressed) ramTrack.setRam(mouse.x) }
                                        }
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: settingsRamInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; inputMethodHints: Qt.ImhDigitsOnly; text: window.ramDraft; onEditingFinished: { var value = Number(text); if (value >= 512 && value <= 16384) window.ramDraft = Math.round(value / 256) * 256; text = window.ramDraft } } }
                                    }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 7
                                        Text { text: "JAVA ARGUMENTS"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold }
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: settingsJavaArgs; anchors.fill: parent; anchors.margins: 10; color: window.ink; text: launcher.settings.javaArguments; clip: true } }
                                        Text { text: "Example: -XX:+UseG1GC"; color: window.muted; font.pixelSize: 11 }
                                    }
                                }
                                Repeater { model: [ {"label": "Discord Rich Presence", "key": "rpc"}, {"label": "Check for launcher updates", "key": "updates"}, {"label": "Custom Windows title bar", "key": "titlebar"}, {"label": "Neo dark interface", "key": "neo"} ]; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 44; radius: 6; color: window.surface; border.color: window.outline; border.width: 1
                                    Text { anchors.left: parent.left; anchors.leftMargin: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: window.ink; font.pixelSize: 13 }
                                    Rectangle { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 22; radius: 11; property bool on: modelData.key === "rpc" ? window.rpcDraft : (modelData.key === "updates" ? window.updatesDraft : (modelData.key === "titlebar" ? window.titlebarDraft : window.neoDraft)); color: on ? window.primary : "#46535F"; Rectangle { width: 16; height: 16; radius: 8; anchors.verticalCenter: parent.verticalCenter; x: parent.on ? 18 : 4; color: parent.on ? window.bg : window.ink } MouseArea { anchors.fill: parent; onClicked: { if (modelData.key === "rpc") window.rpcDraft = !window.rpcDraft; else if (modelData.key === "updates") window.updatesDraft = !window.updatesDraft; else if (modelData.key === "titlebar") window.titlebarDraft = !window.titlebarDraft; else window.neoDraft = !window.neoDraft } } }
                                } }
                                RowLayout { Layout.fillWidth: true; spacing: 8
                                    Text { text: "ACCENT"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold }
                                    ComboBox { Layout.preferredWidth: 120; Layout.preferredHeight: 34; model: ["Green", "Blue", "Orange", "Purple", "Red"]; currentIndex: model.indexOf(window.accentDraft); onActivated: window.accentDraft = currentText; contentItem: Text { leftPadding: 10; verticalAlignment: Text.AlignVCenter; text: parent.displayText; color: window.ink; font.pixelSize: 12; font.weight: Font.DemiBold } background: Rectangle { radius: 6; color: window.raised; border.color: window.outline; border.width: 1 } }
                                    Item { Layout.fillWidth: true }
                                    Rectangle { Layout.preferredWidth: 110; Layout.preferredHeight: 40; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "SAVE SETTINGS"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.saveSettings(settingsDirectory.text, window.ramDraft, settingsJavaArgs.text, window.rpcDraft, window.updatesDraft, window.titlebarDraft, window.neoDraft, window.accentDraft) } }
                                }
                                Text { text: launcher.settingsStatus; color: window.primary; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                    }
                    RowLayout { visible: window.currentPage === "Modrinth"; Layout.fillWidth: true; Text { text: "Content installs into the selected installation"; color: window.muted; font.pixelSize: 11 } Item { Layout.fillWidth: true } ComboBox { id: selector; objectName: "modrinthInstallationSelector"; Layout.preferredWidth: 240; Layout.preferredHeight: 34; model: launcher.installations; textRole: "name"; currentIndex: launcher.selectedIndex; onActivated: launcher.selectInstallation(currentIndex); contentItem: Text { leftPadding: 12; rightPadding: 30; verticalAlignment: Text.AlignVCenter; text: selector.displayText; color: window.ink; font.pixelSize: 12; elide: Text.ElideRight } background: Rectangle { radius: 6; color: window.raised; border.color: window.outline; border.width: 1 } indicator: Text { x: parent.width - 23; anchors.verticalCenter: parent.verticalCenter; text: "\uE70D"; color: window.muted; font.family: window.iconFont; font.pixelSize: 14 } } }
                }
            }
        }
    }


    Item {
        visible: window.installationModalOpen
        anchors.fill: parent
        z: 20
        Rectangle { anchors.fill: parent; color: "#070A0D"; opacity: 0.72; MouseArea { anchors.fill: parent; onClicked: window.installationModalOpen = false } }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 72, 660)
            height: 520
            radius: 8
            color: window.surface
            border.color: window.outline
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12
                RowLayout { Layout.fillWidth: true; Text { text: window.installationModalIndex < 0 ? "New installation" : "Edit installation"; color: window.ink; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 6; color: window.raised; Text { anchors.centerIn: parent; text: "×"; color: window.muted; font.pixelSize: 20 } MouseArea { anchors.fill: parent; onClicked: window.installationModalOpen = false } } }
                Text { text: "Set the game, loader, and launch behaviour. Downloads happen only when you press Play."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                RowLayout { Layout.fillWidth: true; spacing: 10
                    ColumnLayout { Layout.fillWidth: true; spacing: 5; Text { text: "NAME"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: installationModalNameInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.installationModalName; onTextChanged: window.installationModalName = text } } }
                    ColumnLayout { Layout.fillWidth: true; spacing: 5; Text { text: "MINECRAFT VERSION"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: installationModalVersionInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.installationModalVersion; onTextChanged: window.installationModalVersion = text } } }
                }
                RowLayout { Layout.fillWidth: true; spacing: 10
                    ColumnLayout { Layout.fillWidth: true; spacing: 5; Text { text: "LOADER"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } ComboBox { Layout.fillWidth: true; Layout.preferredHeight: 40; model: ["Vanilla", "Fabric", "Forge"]; currentIndex: model.indexOf(window.installationModalLoader); onActivated: window.installationModalLoader = currentText; contentItem: Text { leftPadding: 10; verticalAlignment: Text.AlignVCenter; text: parent.displayText; color: window.ink; font.pixelSize: 13 } background: Rectangle { radius: 6; color: window.raised; border.color: window.outline; border.width: 1 } } }
                    ColumnLayout { Layout.fillWidth: true; spacing: 5; Text { text: "CUSTOM JAVA (OPTIONAL)"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: installationModalJavaInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.installationModalJava; onTextChanged: window.installationModalJava = text; clip: true } } }
                }
                Text { text: "Resolution"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold }
                RowLayout { Layout.fillWidth: true; spacing: 8
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: installationModalWidthInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; inputMethodHints: Qt.ImhDigitsOnly; text: window.installationModalWidth; onTextChanged: window.installationModalWidth = text } }
                    Text { text: "×"; color: window.muted; font.pixelSize: 16 }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { id: installationModalHeightInput; anchors.fill: parent; anchors.margins: 10; color: window.ink; inputMethodHints: Qt.ImhDigitsOnly; text: window.installationModalHeight; onTextChanged: window.installationModalHeight = text } }
                    Rectangle { Layout.preferredWidth: 132; Layout.preferredHeight: 38; radius: 6; color: window.installationModalForceUpdate ? "#392D1D" : window.raised; border.color: window.installationModalForceUpdate ? "#FFAE57" : window.outline; border.width: 1; Text { anchors.centerIn: parent; text: window.installationModalForceUpdate ? "FORCE UPDATE" : "NORMAL UPDATE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: window.installationModalForceUpdate = !window.installationModalForceUpdate } }
                }
                Text { text: "Leave both resolution fields blank for automatic sizing. Force update reinstalls the selected game version on the next launch."; color: window.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Item { Layout.fillHeight: true }
                RowLayout { Layout.fillWidth: true; spacing: 8
                    Rectangle { visible: window.installationModalIndex >= 0; Layout.preferredWidth: 96; Layout.preferredHeight: 38; radius: 6; color: "transparent"; border.color: window.error; border.width: 1; Text { anchors.centerIn: parent; text: window.installationDeleteArmed ? "CONFIRM" : "DELETE"; color: window.error; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { if (window.installationDeleteArmed) { launcher.deleteInstallation(window.installationModalIndex); window.installationModalOpen = false; window.installationDeleteArmed = false } else window.installationDeleteArmed = true } } }
                    Item { Layout.fillWidth: true }
                    Rectangle { Layout.preferredWidth: 84; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "CANCEL"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: window.installationModalOpen = false } }
                    Rectangle { Layout.preferredWidth: 94; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: window.installationModalIndex < 0 ? "CREATE" : "SAVE"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { if (window.installationModalIndex < 0) launcher.createInstallation(window.installationModalName, window.installationModalVersion, window.installationModalLoader, window.installationModalJava, window.installationModalWidth, window.installationModalHeight, window.installationModalForceUpdate); else launcher.updateInstallation(window.installationModalIndex, window.installationModalName, window.installationModalVersion, window.installationModalLoader, window.installationModalJava, window.installationModalWidth, window.installationModalHeight, window.installationModalForceUpdate); window.installationModalOpen = false } }
                }
            }
        }
    }
    }

    Item {
        visible: window.modpackModalOpen
        anchors.fill: parent
        z: 21
        Rectangle { anchors.fill: parent; color: "#070A0D"; opacity: 0.72; MouseArea { anchors.fill: parent; onClicked: window.modpackModalOpen = false } }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 72, 600)
            height: window.modpackModalMode === "manage" ? 420 : 330
            radius: 8
            color: window.surface
            border.color: window.outline
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12
                RowLayout { Layout.fillWidth: true; Text { text: window.modpackModalMode === "create" ? "New local modpack" : (window.modpackModalMode === "import" ? "Import CurseForge modpack" : "Manage modpack"); color: window.ink; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 6; color: window.raised; Text { anchors.centerIn: parent; text: "×"; color: window.muted; font.pixelSize: 20 } MouseArea { anchors.fill: parent; onClicked: window.modpackModalOpen = false } } }
                ColumnLayout { visible: window.modpackModalMode === "create"; Layout.fillWidth: true; spacing: 10
                    Text { text: "A matching installation is created and linked automatically."; color: window.muted; font.pixelSize: 13 }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; text: window.modpackModalName; onTextChanged: window.modpackModalName = text; clip: true } }
                    RowLayout { Layout.fillWidth: true; spacing: 8; Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; text: window.modpackModalVersion; onTextChanged: window.modpackModalVersion = text } } ComboBox { Layout.preferredWidth: 110; Layout.preferredHeight: 40; model: ["Fabric", "Forge", "Vanilla"]; currentIndex: model.indexOf(window.modpackModalLoader); onActivated: window.modpackModalLoader = currentText; contentItem: Text { leftPadding: 10; verticalAlignment: Text.AlignVCenter; text: parent.displayText; color: window.ink; font.pixelSize: 12 } background: Rectangle { radius: 6; color: window.raised; border.color: window.outline; border.width: 1 } } }
                }
                ColumnLayout { visible: window.modpackModalMode === "import"; Layout.fillWidth: true; spacing: 10; Text { text: "Choose a local CurseForge .zip export. Safe overrides are imported into isolated pack storage."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true } Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; text: window.modpackModalPath; onTextChanged: window.modpackModalPath = text; clip: true } } }
                ColumnLayout { visible: window.modpackModalMode === "manage"; Layout.fillWidth: true; spacing: 10
                    Text { text: (launcher.modpacks[window.modpackModalIndex] || ({})).name || "Modpack"; color: window.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
                    Text { text: ((launcher.modpacks[window.modpackModalIndex] || ({})).modCount || 0) + " installed mods · " + ((launcher.modpacks[window.modpackModalIndex] || ({})).linkedInstallationName || "Not linked"); color: window.muted; font.pixelSize: 12 }
                    RowLayout { Layout.fillWidth: true; spacing: 8; ComboBox { Layout.fillWidth: true; Layout.preferredHeight: 38; model: launcher.installations; textRole: "name"; currentIndex: window.modpackLinkIndex; onActivated: window.modpackLinkIndex = currentIndex; contentItem: Text { leftPadding: 10; verticalAlignment: Text.AlignVCenter; text: parent.displayText; color: window.ink; font.pixelSize: 12; elide: Text.ElideRight } background: Rectangle { radius: 6; color: window.raised; border.color: window.outline; border.width: 1 } } Rectangle { Layout.preferredWidth: 62; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "LINK"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.linkModpack(window.modpackModalIndex, window.modpackLinkIndex) } } }
                    RowLayout { spacing: 8; Rectangle { Layout.preferredWidth: 108; Layout.preferredHeight: 36; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "SHOW MODS"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { launcher.requestModpackMods(window.modpackModalIndex); window.modpackModalOpen = false; window.modListModalOpen = true } } } Rectangle { Layout.preferredWidth: 110; Layout.preferredHeight: 36; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "OPEN FOLDER"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.openModpackFolder(window.modpackModalIndex) } } Rectangle { Layout.preferredWidth: 78; Layout.preferredHeight: 36; radius: 6; color: window.primaryTint; border.color: window.primary; border.width: 1; Text { anchors.centerIn: parent; text: "BROWSE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { launcher.linkModpack(window.modpackModalIndex, window.modpackLinkIndex); launcher.selectInstallation(window.modpackLinkIndex); window.modpackModalOpen = false; window.modrinthTab = "Browse"; window.modrinthCategory = "mods"; window.navigate("Modrinth") } } } }
                    Item { Layout.fillHeight: true }
                    Rectangle { Layout.preferredWidth: 104; Layout.preferredHeight: 36; radius: 6; color: "transparent"; border.color: window.error; border.width: 1; Text { anchors.centerIn: parent; text: window.modpackDeleteArmed ? "CONFIRM DELETE" : "DELETE PACK"; color: window.error; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { if (window.modpackDeleteArmed) { launcher.deleteModpack(window.modpackModalIndex); window.modpackModalOpen = false; window.modpackDeleteArmed = false } else window.modpackDeleteArmed = true } } }
                }
                Item { Layout.fillHeight: true }
                RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 84; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "CANCEL"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: window.modpackModalOpen = false } } Rectangle { visible: window.modpackModalMode !== "manage"; Layout.preferredWidth: 96; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: window.modpackModalMode === "import" ? "IMPORT" : "CREATE"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { if (window.modpackModalMode === "import") launcher.importCurseForge(window.modpackModalPath); else launcher.createModpack(window.modpackModalName, window.modpackModalVersion, window.modpackModalLoader); window.modpackModalOpen = false } } } }
            }
        }
    }

    Item {
        visible: window.modListModalOpen
        anchors.fill: parent
        z: 23
        Rectangle { anchors.fill: parent; color: "#070A0D"; opacity: 0.72; MouseArea { anchors.fill: parent; onClicked: window.modListModalOpen = false } }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 72, 720)
            height: Math.min(parent.height - 72, 560)
            radius: 8
            color: window.surface
            border.color: window.outline
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 22
                spacing: 10
                RowLayout { Layout.fillWidth: true; Text { text: "Installed modpack mods"; color: window.ink; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 6; color: window.raised; Text { anchors.centerIn: parent; text: "×"; color: window.muted; font.pixelSize: 20 } MouseArea { anchors.fill: parent; onClicked: window.modListModalOpen = false } } }
                Text { text: launcher.modsStatus; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                Text { visible: !launcher.modsScanning && launcher.mods.length === 0; text: "No installed mods were found in this modpack."; color: window.muted; font.pixelSize: 13; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
                ListView {
                    visible: launcher.mods.length > 0
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 6
                    model: launcher.mods
                    delegate: Rectangle { required property var modelData; width: ListView.view.width; height: 54; radius: 6; color: window.raised; border.color: window.outline; border.width: 1
                        RowLayout { anchors.fill: parent; anchors.margins: 10; spacing: 10; Image { Layout.preferredWidth: 22; Layout.preferredHeight: 22; source: window.icon("crafting_table_top.png"); smooth: false } ColumnLayout { Layout.fillWidth: true; spacing: 1; Text { text: modelData.name; color: window.ink; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: modelData.id ? modelData.id + " · " + modelData.file : modelData.file; color: window.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true } } Text { text: modelData.loader; color: window.muted; font.pixelSize: 11 } }
                    }
                }
                RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 78; Layout.preferredHeight: 36; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "CLOSE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: window.modListModalOpen = false } } }
            }
        }
    }

    Item {
        visible: window.accountModalOpen
        anchors.fill: parent
        z: 24
        Rectangle { anchors.fill: parent; color: "#070A0D"; opacity: 0.72; MouseArea { anchors.fill: parent; onClicked: { if (!launcher.accountAuth.busy) window.accountModalOpen = false } } }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 72, 580)
            height: window.accountProvider === "Microsoft" ? 390 : (window.accountProvider === "Ely.by" ? 350 : (window.accountProvider === "Offline" ? 300 : 245))
            radius: 8
            color: window.surface
            border.color: window.outline
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12
                RowLayout { Layout.fillWidth: true; Text { text: "Add account"; color: window.ink; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 6; color: window.raised; Text { anchors.centerIn: parent; text: "×"; color: window.muted; font.pixelSize: 20 } MouseArea { anchors.fill: parent; enabled: !launcher.accountAuth.busy; onClicked: window.accountModalOpen = false } } }
                Text { text: window.accountProvider === "" ? "Choose the account type you want to add." : "You can switch accounts at any time from the account manager."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                RowLayout { Layout.fillWidth: true; spacing: 8
                    Repeater { model: ["Offline", "Microsoft", "Ely.by"]; delegate: Rectangle { required property string modelData; property bool selected: window.accountProvider === modelData; Layout.preferredWidth: modelData === "Microsoft" ? 108 : 84; Layout.preferredHeight: 36; radius: 6; color: selected ? window.primaryTint : window.raised; border.color: selected ? window.primary : window.outline; border.width: 1; Text { anchors.centerIn: parent; text: modelData; color: selected ? window.ink : window.muted; font.pixelSize: 11; font.weight: Font.DemiBold } MouseArea { anchors.fill: parent; enabled: !launcher.accountAuth.busy; onClicked: window.accountProvider = modelData } } }
                    Item { Layout.fillWidth: true }
                }
                ColumnLayout { visible: window.accountProvider === "Offline"; Layout.fillWidth: true; spacing: 8
                    Text { text: "Offline player name"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.profileDraft; onTextChanged: window.profileDraft = text; clip: true } }
                    RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 106; Layout.preferredHeight: 38; radius: 6; color: window.primary; Text { anchors.centerIn: parent; text: "ADD ACCOUNT"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: { launcher.createOfflineProfile(window.profileDraft); window.profileDraft = ""; window.accountModalOpen = false } } } }
                }
                ColumnLayout { visible: window.accountProvider === "Ely.by"; Layout.fillWidth: true; spacing: 8
                    Text { text: "Ely.by username or email"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.elyUsernameDraft; onTextChanged: window.elyUsernameDraft = text; clip: true } }
                    Text { text: "Password"; color: window.muted; font.pixelSize: 11; font.weight: Font.DemiBold }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 40; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; TextInput { anchors.fill: parent; anchors.margins: 10; color: window.ink; font.pixelSize: 13; text: window.elyPasswordDraft; onTextChanged: window.elyPasswordDraft = text; echoMode: TextInput.Password; clip: true } }
                    RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } Rectangle { Layout.preferredWidth: 90; Layout.preferredHeight: 38; radius: 6; color: launcher.accountAuth.busy ? "#42505B" : window.primary; Text { anchors.centerIn: parent; text: "SIGN IN"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.accountAuth.busy; onClicked: { launcher.loginElyBy(window.elyUsernameDraft, window.elyPasswordDraft); window.elyPasswordDraft = "" } } } }
                }
                ColumnLayout { visible: window.accountProvider === "Microsoft"; Layout.fillWidth: true; spacing: 9
                    Text { text: "Microsoft account"; color: window.ink; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Text { text: "Microsoft opens the sign-in page. Enter the one-time code there; your password is never handled by the launcher."; color: window.muted; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    RowLayout { spacing: 8
                        Rectangle { Layout.preferredWidth: 118; Layout.preferredHeight: 38; radius: 6; color: launcher.accountAuth.busy ? "#42505B" : window.primary; Text { anchors.centerIn: parent; text: launcher.accountAuth.busy ? "WAITING…" : "START SIGN-IN"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.accountAuth.busy; onClicked: launcher.startMicrosoftLogin() } }
                        Rectangle { visible: launcher.accountAuth.deviceCode !== ""; Layout.preferredWidth: 142; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "OPEN SIGN-IN PAGE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: Qt.openUrlExternally(launcher.accountAuth.verificationUrl) } }
                        Rectangle { visible: launcher.accountAuth.busy; Layout.preferredWidth: 70; Layout.preferredHeight: 38; radius: 6; color: "transparent"; border.color: window.error; border.width: 1; Text { anchors.centerIn: parent; text: "CANCEL"; color: window.error; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.cancelMicrosoftLogin() } }
                    }
                    RowLayout { visible: launcher.accountAuth.deviceCode !== ""; Layout.fillWidth: true; spacing: 8; Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 42; radius: 6; color: window.primaryTint; border.color: window.primary; border.width: 1; Text { anchors.centerIn: parent; text: launcher.accountAuth.deviceCode; color: window.ink; font.pixelSize: 19; font.weight: Font.Bold; font.letterSpacing: 1.5 } } Rectangle { Layout.preferredWidth: 96; Layout.preferredHeight: 42; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "COPY CODE"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: launcher.copyMicrosoftCode() } } }
                }
                Text { visible: window.accountProvider !== ""; text: launcher.accountStatus; color: window.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Item { Layout.fillHeight: true }
            }
        }
    }

    Item {
        visible: window.modrinthDetailsOpen
        anchors.fill: parent
        z: 22
        Rectangle { anchors.fill: parent; color: "#070A0D"; opacity: 0.72; MouseArea { anchors.fill: parent; onClicked: window.modrinthDetailsOpen = false } }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 72, 680)
            height: Math.min(parent.height - 72, 470)
            radius: 8
            color: window.surface
            border.color: window.outline
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12
                RowLayout { Layout.fillWidth: true
                    Rectangle { Layout.preferredWidth: 58; Layout.preferredHeight: 58; radius: 6; color: "#2B3742"; clip: true; Image { anchors.fill: parent; source: launcher.modrinthDetail.iconUrl || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true } }
                    ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: launcher.modrinthDetail.title || "Modrinth project"; color: window.ink; font.pixelSize: 22; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: (launcher.modrinthDetail.author || "Unknown author") + " · " + Number(launcher.modrinthDetail.downloads || 0).toLocaleString() + " downloads"; color: window.muted; font.pixelSize: 12; Layout.fillWidth: true } }
                    Rectangle { Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 6; color: window.raised; Text { anchors.centerIn: parent; text: "×"; color: window.muted; font.pixelSize: 20 } MouseArea { anchors.fill: parent; onClicked: window.modrinthDetailsOpen = false } }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: window.outline }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true; Text { width: parent.availableWidth; text: launcher.modrinthDetail.body || launcher.modrinthDetail.description || "No description was provided by this project."; color: window.ink; font.pixelSize: 14; wrapMode: Text.Wrap } }
                RowLayout { Layout.fillWidth: true; spacing: 8
                    Rectangle { Layout.preferredWidth: 142; Layout.preferredHeight: 38; radius: 6; color: window.raised; border.color: window.outline; border.width: 1; Text { anchors.centerIn: parent; text: "OPEN MODRINTH"; color: window.ink; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; onClicked: Qt.openUrlExternally("https://modrinth.com/" + (launcher.modrinthDetail.projectType || "mod") + "/" + (launcher.modrinthDetail.slug || launcher.modrinthDetail.id || "")) } }
                    Item { Layout.fillWidth: true }
                    Rectangle { visible: !launcher.modrinthDetail.installed; Layout.preferredWidth: launcher.modrinthDetail.projectType === "modpack" ? 96 : 82; Layout.preferredHeight: 38; radius: 6; color: launcher.modrinthBusy ? "#42505B" : window.primary; Text { anchors.centerIn: parent; text: launcher.modrinthDetail.projectType === "modpack" ? "INSTALL" : "ADD"; color: window.bg; font.pixelSize: 10; font.weight: Font.Bold } MouseArea { anchors.fill: parent; enabled: !launcher.modrinthBusy; onClicked: { launcher.installModrinth(launcher.modrinthDetail, window.modrinthCategory); window.modrinthDetailsOpen = false } } }
                }
            }
        }
    }

    Rectangle {
        id: downloadToast
        visible: launcher.modrinthDownloading
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 24
        anchors.bottomMargin: 24
        width: 328
        height: 86
        z: 30
        radius: 6
        color: window.surface
        border.color: window.primary
        border.width: 1
        opacity: visible ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 7
            RowLayout {
                Layout.fillWidth: true
                Text { text: launcher.modrinthProgressLabel || "Preparing download…"; color: window.ink; font.pixelSize: 12; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                Text { text: launcher.modrinthProgress + "%"; color: window.primary; font.pixelSize: 12; font.weight: Font.DemiBold }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 6
                radius: 3
                color: window.raised
                Rectangle {
                    width: parent.width * launcher.modrinthProgress / 100
                    height: parent.height
                    radius: parent.radius
                    color: window.primary
                    Behavior on width { NumberAnimation { duration: 120 } }
                }
            }
            Text { text: "Downloading in the background"; color: window.muted; font.pixelSize: 11 }
        }
    }
}


