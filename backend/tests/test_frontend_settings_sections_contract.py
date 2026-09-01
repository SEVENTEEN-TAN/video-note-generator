from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_settings_modal_composes_focused_domain_sections() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    modal_source = (ROOT / "frontend" / "src" / "SettingsModal.tsx").read_text(encoding="utf-8")
    transcription_source = (ROOT / "frontend" / "src" / "SettingsTranscriptionSection.tsx").read_text(
        encoding="utf-8"
    )
    local_source = (ROOT / "frontend" / "src" / "SettingsLocalTranscriptionSection.tsx").read_text(
        encoding="utf-8"
    )
    remote_source = (ROOT / "frontend" / "src" / "SettingsRemoteTranscriptionSection.tsx").read_text(
        encoding="utf-8"
    )
    note_source = (ROOT / "frontend" / "src" / "SettingsNoteApiSection.tsx").read_text(encoding="utf-8")

    assert "modal={{" in app_source
    assert "note={{" in app_source
    assert "transcription={{" in app_source
    assert "<SettingsTranscriptionSection" in modal_source
    assert "<SettingsNoteApiSection" in modal_source
    assert "<RuntimeStatusCard" in modal_source

    assert "<SettingsLocalTranscriptionSection" in transcription_source
    assert "<SettingsRemoteTranscriptionSection" in transcription_source
    assert 'transcriptionMode === "local_faster_whisper"' in transcription_source
    assert "性能档位" in local_source
    assert "安装本地转写依赖" in local_source
    assert "安装 CUDA 加速依赖" in local_source
    assert "转写 API Key" in remote_source
    assert "笔记生成 API" in note_source
    assert "笔记 API Key" in note_source

    for presentation_source in (modal_source, transcription_source, local_source, remote_source, note_source):
        assert 'fetch("/api/' not in presentation_source
        assert "useSettings(" not in presentation_source
        assert "useRuntimeTasks(" not in presentation_source


def test_settings_modal_no_longer_owns_domain_specific_field_markup() -> None:
    modal_source = (ROOT / "frontend" / "src" / "SettingsModal.tsx").read_text(encoding="utf-8")

    for moved_marker in (
        "性能档位",
        "本地模型",
        "转写 API Key",
        "笔记 API Key",
        "安装 CUDA 加速依赖",
    ):
        assert moved_marker not in modal_source
